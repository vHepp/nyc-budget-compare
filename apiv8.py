import argparse
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv
from openpyxl.utils import get_column_letter
from sodapy import Socrata
from tqdm.auto import tqdm

# --- Configuration & Constants ---
VERSION = "8"
EXPENSE_DATASET_ID = "mwzb-yiwb"
RELEASE_NAMES = ["prelim", "exec", "adopt"]

ROOT = Path(__file__).resolve().parent
DATA_CACHE = ROOT / "data_cache"
ENV_PATH = ROOT / ".env"

MAX_WORKERS_DEFAULT = 6
FETCH_PAGE_LIMIT = 50000

# Define Categorical Columns

TARGET_CATEGORICAL_COL_CODES = [
    "agency_number", "unit_appropriation_number",
    "responsibility_center_code", "budget_code_number",
    "object_class_number", "object_code"]
TARGET_CATEGORICAL_COL_NAMES = [
    "agency_name", "unit_appropriation_name",
    "responsibility_center_name",
    "budget_code_name", "object_class_name",
    "intra_city_purchase_code",
    "object_code_name", "personal_service_other_than_personal_service_indicator",
    "financial_plan_savings_flag"
]

OUTPUT_ORDER = [
    "agency_number",
    "agency_name",
    "unit_appropriation_number",
    "unit_appropriation_name",
    "responsibility_center_code",
    "responsibility_center_name",
    "budget_code_number",
    "budget_code_name",
    "object_class_number",
    "object_class_name",
    "object_code",
    "object_code_name",
    "intra_city_purchase_code",
    "personal_service_other_than_personal_service_indicator",
    "financial_plan_savings_flag"
]

TARGET_CATEGORICAL_COLS = TARGET_CATEGORICAL_COL_CODES + TARGET_CATEGORICAL_COL_NAMES

ALL_CATEGORICAL_COLS = ["publication_date", "fiscal_year", "release_type"] + TARGET_CATEGORICAL_COLS

# Numeric "families": the suffix shared by each adopted/modified/financial_plan column trio.
NUMERIC_FAMILIES = ["amount", "position", "number_of_contracts"]

# Only dollar amounts get a %change column; raw position/contract counts get $ change only.
PCT_CHANGE_FAMILIES = {"amount"}

# Maps a prior-year baseline column's raw field prefix to the short label used in diff column names.
BASELINE_LABELS = {
    "adopted_budget": "adopted",
    "current_modified_budget": "modified",
}

NUMERICAL_COLS = [
    "adopted_budget_amount",
    "current_modified_budget_amount",
    "financial_plan_amount",

    "adopted_budget_position",
    "current_modified_budget_position",
    "financial_plan_position",

    "adopted_budget_number_of_contracts",
    "current_modified_budget_number_of_contracts",
    "financial_plan_number_of_contracts",
]

ALL_COLS = ALL_CATEGORICAL_COLS + NUMERICAL_COLS

# release_type is computed locally from publication_date after fetching; it isn't a real
# column in the Socrata dataset, so it must be excluded from any remote $select clause.
REMOTE_SELECT_COLS = [c for c in ALL_COLS if c != "release_type"]


def safe_pct_change(change_series: pd.Series, base_series: pd.Series) -> pd.Series:
    """Helper function to calculate percent change and avoid division-by-zero errors."""
    return change_series.div(base_series).replace([np.inf, -np.inf], np.nan)


# --- Authentication ---

def get_app_key() -> Optional[str]:
    """
    Loads SOCRATA_APP_KEY from .env and validates it against Socrata. An app token is
    optional for reading this public dataset (it just raises the rate limit), so a
    missing, blank, or rejected token falls back to None (unauthenticated) instead of
    stopping the program.
    """
    load_dotenv(dotenv_path=ENV_PATH)
    key = os.getenv("SOCRATA_APP_KEY")
    if not key:
        print("SOCRATA_APP_KEY is not set; continuing without an app token "
              "(unauthenticated requests are subject to Socrata's stricter rate limits).")
        return None

    try:
        _build_client(key).get(EXPENSE_DATASET_ID, select="COUNT(*)", limit=1)
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code in (401, 403):
            print("SOCRATA_APP_KEY was rejected by Socrata (invalid or expired); "
                  "continuing without an app token.")
            return None
        raise

    return key


def _build_client(app_key: Optional[str]) -> Socrata:
    return Socrata("data.cityofnewyork.us", app_key, timeout=180)


# --- Fetching ---

def _fetch_page(app_key: Optional[str], dataset_id: str, select: str, where: str, order: str,
                 limit: int, offset: int, max_retries: int = 4) -> list:
    """Fetches a single page of results, retrying transient failures with backoff."""
    last_err: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            client = _build_client(app_key)
            return client.get(dataset_id, select=select, where=where, order=order,
                               limit=limit, offset=offset)
        except Exception as e:
            last_err = e
            if attempt < max_retries - 1:
                time.sleep(min(2 ** attempt, 30))
    raise RuntimeError(f"Failed to fetch page at offset {offset} after {max_retries} attempts") from last_err


def _assign_release_types(df: pd.DataFrame, fiscal_years: List[int]) -> pd.DataFrame:
    """Labels each row's publication_date as prelim/exec/adopt, per fiscal year."""
    releases_map = {}
    for y in fiscal_years:
        y_releases = sorted(df.loc[df["fiscal_year"] == str(y), "publication_date"].unique().tolist())
        for pub_date, release_name in zip(y_releases, RELEASE_NAMES[:len(y_releases)]):
            releases_map[pub_date] = release_name
    df["release_type"] = df["publication_date"].map(releases_map)
    return df


def _apply_categorical_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    present_cols = [c for c in ALL_CATEGORICAL_COLS if c in df.columns]
    df[present_cols] = df[present_cols].astype(str)
    return df


def _fetch_year_data(app_key: Optional[str], fiscal_years: List[int], max_workers: int) -> pd.DataFrame:
    """Fetches raw rows for the given fiscal years from Socrata, in parallel, restricted to needed columns."""
    where_string = f"fiscal_year IN ({','.join(str(y) for y in fiscal_years)})"
    select_cols = ", ".join(REMOTE_SELECT_COLS)
    order_string = ", ".join([
        "agency_number", "unit_appropriation_number", "responsibility_center_code",
        "budget_code_number", "object_class_number", "object_code", "publication_date DESC"
    ])

    count_client = _build_client(app_key)
    count_result = count_client.get(EXPENSE_DATASET_ID, select="COUNT(*)", where=where_string)
    total_rows = int(count_result[0]["COUNT"]) if count_result else 0
    print(f"Total rows to fetch for fiscal years {fiscal_years}: {total_rows}")

    if total_rows == 0:
        return pd.DataFrame(columns=ALL_COLS)

    offsets = list(range(0, total_rows, FETCH_PAGE_LIMIT))
    pages: Dict[int, list] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor, \
            tqdm(total=total_rows, desc="Downloading Data", unit="rows") as pbar:
        future_to_offset = {
            executor.submit(
                _fetch_page, app_key, EXPENSE_DATASET_ID, select_cols, where_string,
                order_string, FETCH_PAGE_LIMIT, offset
            ): offset
            for offset in offsets
        }
        for future in as_completed(future_to_offset):
            offset = future_to_offset[future]
            page = future.result()
            pages[offset] = page
            pbar.update(len(page))

    data = []
    for offset in offsets:
        data.extend(pages[offset])

    print(f"End of query. Successfully fetched {len(data)} total rows.")
    df = pd.DataFrame.from_records(data)
    df = _apply_categorical_dtypes(df)
    df = _assign_release_types(df, fiscal_years)
    return df


# --- Per-fiscal-year cache ---

def _cache_path_for_year(fy: int) -> Path:
    return DATA_CACHE / f"fy{fy}_v{VERSION}.parquet"


def _load_cached_year(fy: int) -> Optional[pd.DataFrame]:
    path = _cache_path_for_year(fy)
    if not path.exists():
        return None
    return pd.read_parquet(path)


def _is_year_immutable(df: pd.DataFrame) -> bool:
    """A fiscal year is done changing once its 'adopt' release has been published."""
    if df.empty or "release_type" not in df.columns:
        return False
    return "adopt" in set(df["release_type"].dropna().unique())


def _is_cache_stale(app_key: Optional[str], fy: int, cached_df: pd.DataFrame) -> bool:
    """Cheaply checks whether NYC has published a newer release for this fiscal year."""
    client = _build_client(app_key)
    result = client.get(
        EXPENSE_DATASET_ID,
        select="COUNT(*) as row_count, MAX(publication_date) as max_pub",
        where=f"fiscal_year = {fy}",
    )
    if not result:
        return False

    remote_count = int(result[0].get("row_count", 0))
    remote_max_pub = result[0].get("max_pub")
    cached_count = len(cached_df)
    cached_max_pub = cached_df["publication_date"].max() if not cached_df.empty else None

    if remote_max_pub and cached_max_pub and str(remote_max_pub) > str(cached_max_pub):
        return True
    return remote_count != cached_count


def fetch_data(app_key: Optional[str], all_years_to_query: List[int],
                max_workers: int = MAX_WORKERS_DEFAULT, refresh_cache: bool = False) -> pd.DataFrame:
    """Fetches data for each requested fiscal year, reusing a per-year cache where possible."""
    DATA_CACHE.mkdir(parents=True, exist_ok=True)

    year_frames: Dict[int, pd.DataFrame] = {}
    years_to_fetch: List[int] = []

    for fy in all_years_to_query:
        cached = None if refresh_cache else _load_cached_year(fy)
        if cached is not None:
            if _is_year_immutable(cached):
                print(f"FY{fy} cache is final (adopted), using cached data.")
                year_frames[fy] = cached
                continue
            if not _is_cache_stale(app_key, fy, cached):
                print(f"FY{fy} cache is up to date, using cached data.")
                year_frames[fy] = cached
                continue
            print(f"FY{fy} cache is stale, refetching.")
        years_to_fetch.append(fy)

    if years_to_fetch:
        print(f"Querying Socrata for fiscal years {years_to_fetch}...")
        fresh_df = _fetch_year_data(app_key, years_to_fetch, max_workers)
        for fy in years_to_fetch:
            fy_df = fresh_df[fresh_df["fiscal_year"] == str(fy)].reset_index(drop=True)
            fy_df.to_parquet(_cache_path_for_year(fy), index=False)
            year_frames[fy] = fy_df

    ordered_frames = [year_frames[fy] for fy in all_years_to_query if fy in year_frames]
    return pd.concat(ordered_frames, ignore_index=True)


def clean(df: pd.DataFrame, no_amounts: bool = False, no_positions: bool = False, no_contracts: bool = False, verbose: bool = False) -> pd.DataFrame:
    df[TARGET_CATEGORICAL_COLS] = df[TARGET_CATEGORICAL_COLS].astype(str)

    for cat_col in TARGET_CATEGORICAL_COLS:
        if cat_col in df.columns:
            df[cat_col] = df[cat_col].str.upper()

    # Fill empty categorical cells with "(blank)"
    df[TARGET_CATEGORICAL_COLS] = df[TARGET_CATEGORICAL_COLS].fillna("(blank)")

    # --- FILTER NUMERICAL COLUMNS ---
    active_num_cols = NUMERICAL_COLS.copy()

    if no_amounts:
        active_num_cols = [c for c in active_num_cols if "amount" not in c.lower()]

    if no_positions:
        active_num_cols = [c for c in active_num_cols if "position" not in c.lower()]

    if no_contracts:
        active_num_cols = [c for c in active_num_cols if "contract" not in c.lower()]

    if not active_num_cols:
        raise ValueError("All numerical columns have been filtered out! You must leave at least one numerical column type to aggregate.")

    # --- CAST NUMERIC COLUMNS TO FLOAT/INT ---
    for num_col in active_num_cols:
        if num_col in df.columns:
            df[num_col] = pd.to_numeric(df[num_col], errors='raise').fillna(0)
    # ----------------------------------------

    # Aggregate numerical columns to prevent Pandas 2.0+ TypeErrors
    df = df.groupby(ALL_CATEGORICAL_COLS, dropna=False)[active_num_cols].sum().reset_index()

    # Sort by hierarchy
    order = TARGET_CATEGORICAL_COL_CODES + ["publication_date"]
    ascending = [True] * len(TARGET_CATEGORICAL_COL_CODES) + [False]

    if verbose:
        print(f"column, direction\n")
        for o, a in zip(order, ascending):
            if a:
                print(f"{o}, ascending")
            else:
                print(f"{o}, descending")

    return df.sort_values(by=order, ascending=ascending).reset_index(drop=True)


def collapse(clean_df: pd.DataFrame, latest_interim_only: bool = False, verbose: bool = False) -> pd.DataFrame:

    collapsed_df = clean_df[TARGET_CATEGORICAL_COLS].drop_duplicates().reset_index(drop=True)

    years_arr = sorted(clean_df['fiscal_year'].unique())
    max_fy = years_arr[-1]  # Identifies the most recent year

    if verbose:
        print(f"num_years: {len(years_arr)}")
        print(years_arr)

    for fy in years_arr:
        if verbose:
            print(f"FY {fy}")

        fy_df = clean_df[clean_df['fiscal_year'] == fy]

        present_releases = [r for r in RELEASE_NAMES if r in fy_df['release_type'].unique()]

        # Filter out interim releases for all historical years
        if latest_interim_only and fy != max_fy:
            present_releases = [r for r in present_releases if r == "adopt"]

        if verbose:
            print(f"num_releases: {len(present_releases)}")
            print(present_releases)

        for j, release_type in enumerate(present_releases):
            if verbose:
                print(f"Release {j}: {release_type}")

            fy_release_df = fy_df[fy_df['release_type'] == release_type].drop(columns=["publication_date", "fiscal_year", "release_type"])

            fy_release_rename_map = rename_cols(fy, release_type)
            if verbose:
                print(fy_release_rename_map)
            fy_release_renamed_df = fy_release_df.rename(columns=fy_release_rename_map)

            # Preserve adopted/modified baseline columns on the final available release of the year.
            # The current_modified_budget columns are the closest to actuals we can get at the moment.
            if j < len(present_releases) - 1:
                drop_cols = [
                    'adopted_budget_amount', 'current_modified_budget_amount',
                    'adopted_budget_position', 'current_modified_budget_position',
                    'adopted_budget_number_of_contracts', 'current_modified_budget_number_of_contracts'
                ]
                to_drop = [fy_release_rename_map[col] for col in drop_cols if col in fy_release_rename_map]
                fy_release_renamed_df = fy_release_renamed_df.drop(columns=to_drop, errors='ignore')

            collapsed_df = collapsed_df.merge(right=fy_release_renamed_df, on=TARGET_CATEGORICAL_COLS, how='left')

        if verbose:
            print()
            print(collapsed_df.columns)
            print()

    # --- Remove duplicate financial-plan columns that just mirror a baseline column ---
    duplicate_cols_to_drop = []
    for col in collapsed_df.columns:
        if "_adopt_financial_plan_" in col:
            equivalent_baseline = col.replace("_adopt_financial_plan_", "_adopted_budget_")
            if equivalent_baseline in collapsed_df.columns:
                duplicate_cols_to_drop.append(col)

    if verbose and duplicate_cols_to_drop:
        print(f"Dropping redundant financial plan columns: {duplicate_cols_to_drop}\n")

    collapsed_df = collapsed_df.drop(columns=duplicate_cols_to_drop)
    # -------------------------------------------

    new_numeric_cols = sorted(list(set(collapsed_df.columns) - set(TARGET_CATEGORICAL_COLS)), reverse=True)

    collapsed_df[new_numeric_cols] = collapsed_df[new_numeric_cols].apply(pd.to_numeric, errors='raise').fillna(0)

    return collapsed_df[OUTPUT_ORDER + new_numeric_cols], new_numeric_cols


def rename_cols(fy: str, release_type: str) -> dict:
    return {
        'adopted_budget_amount': f'FY{int(fy) - 1}_adopted_budget_amount',
        'current_modified_budget_amount': f'FY{int(fy) - 1}_current_modified_budget_amount',

        'adopted_budget_position': f'FY{int(fy) - 1}_adopted_budget_position',
        'current_modified_budget_position': f'FY{int(fy) - 1}_current_modified_budget_position',

        'adopted_budget_number_of_contracts': f'FY{int(fy) - 1}_adopted_budget_number_of_contracts',
        'current_modified_budget_number_of_contracts': f'FY{int(fy) - 1}_current_modified_budget_number_of_contracts',

        'financial_plan_amount': f'FY{fy}_{release_type}_financial_plan_amount',
        'financial_plan_position': f'FY{fy}_{release_type}_financial_plan_position',
        'financial_plan_number_of_contracts': f'FY{fy}_{release_type}_financial_plan_number_of_contracts'
    }


def pivot_by_cols(df: pd.DataFrame, group_by_cols: list, numeric_cols: list) -> pd.DataFrame:
    return df[group_by_cols + numeric_cols].groupby(by=group_by_cols, dropna=False).sum().reset_index()


# --- Differences ---

def calculate_differences(df: pd.DataFrame, target_fy: int) -> pd.DataFrame:
    """
    Adds $ change (and, for dollar amounts, %change) columns for the target fiscal year, comparing:
      - each pair of budget releases present that year (e.g. exec vs. prelim), and
      - each release against the prior fiscal year's adopted and current-modified baselines.

    Columns are discovered from `df` by name (as produced by `collapse()`/`rename_cols()`), so this
    works unchanged whether amounts/positions/contracts were filtered out upstream in `clean()`.
    """
    release_alt = "|".join(RELEASE_NAMES)
    family_alt = "|".join(NUMERIC_FAMILIES)
    baseline_alt = "|".join(BASELINE_LABELS.keys())

    fin_plan_re = re.compile(rf"^FY{target_fy}_(?P<release>{release_alt})_financial_plan_(?P<family>{family_alt})$")
    baseline_re = re.compile(rf"^FY{target_fy - 1}_(?P<kind>{baseline_alt})_(?P<family>{family_alt})$")

    fin_plan_cols: Dict[tuple, str] = {}
    baseline_cols: Dict[tuple, str] = {}

    for col in df.columns:
        m = fin_plan_re.match(col)
        if m:
            fin_plan_cols[(m.group("release"), m.group("family"))] = col
            continue
        m = baseline_re.match(col)
        if m:
            baseline_cols[(m.group("kind"), m.group("family"))] = col

    diff_df = df.copy()
    families_present = sorted({family for (_, family) in fin_plan_cols})

    for family in families_present:
        releases_present = [r for r in RELEASE_NAMES if (r, family) in fin_plan_cols]

        # Release-to-release comparisons (e.g. exec vs. prelim)
        for i in range(len(releases_present)):
            for j in range(i):
                later, earlier = releases_present[i], releases_present[j]
                later_col, earlier_col = fin_plan_cols[(later, family)], fin_plan_cols[(earlier, family)]

                change_col = f"FY{target_fy}_{later}_vs_{earlier}_{family}_change"
                diff_df[change_col] = df[later_col] - df[earlier_col]

                if family in PCT_CHANGE_FAMILIES:
                    pct_col = f"FY{target_fy}_{later}_vs_{earlier}_{family}_pct_change"
                    diff_df[pct_col] = safe_pct_change(diff_df[change_col], df[earlier_col])

        # Vs. prior fiscal year's adopted/modified baselines
        for kind, label in BASELINE_LABELS.items():
            if (kind, family) not in baseline_cols:
                continue
            baseline_col = baseline_cols[(kind, family)]

            for release in releases_present:
                release_col = fin_plan_cols[(release, family)]

                change_col = f"FY{target_fy}_{release}_vs_FY{target_fy - 1}_{label}_{family}_change"
                diff_df[change_col] = df[release_col] - df[baseline_col]

                if family in PCT_CHANGE_FAMILIES:
                    pct_col = f"FY{target_fy}_{release}_vs_FY{target_fy - 1}_{label}_{family}_pct_change"
                    diff_df[pct_col] = safe_pct_change(diff_df[change_col], df[baseline_col])

    return diff_df


# --- Excel export ---

def _number_format_for_column(col_name: str) -> str:
    col_lower = col_name.lower()
    if "position" in col_lower or "contract" in col_lower:
        return '#,##0'
    if "%" in col_lower or "pct" in col_lower or "percent" in col_lower:
        return '0.0%'
    if "amount" in col_lower:
        return '$#,##0'
    return '#,##0'


def _apply_number_formats(worksheet, df: pd.DataFrame) -> None:
    """Applies number formats and column widths in a single sequential pass over the sheet."""
    format_map: Dict[int, str] = {}
    for col_idx, col_name in enumerate(df.columns, start=1):
        if col_name in ALL_CATEGORICAL_COLS:
            continue
        format_map[col_idx] = _number_format_for_column(col_name)
        worksheet.column_dimensions[get_column_letter(col_idx)].width = 22

    if not format_map:
        return

    for row in worksheet.iter_rows(min_row=2):
        for col_idx, num_format in format_map.items():
            row[col_idx - 1].number_format = num_format


def export_to_excel(sheets_to_write: Dict[str, pd.DataFrame], output_filename: str,
                     no_diffs: bool, target_fy: int) -> None:
    """Writes each sheet to Excel, adding diff columns (unless no_diffs) and applying formatting."""
    with pd.ExcelWriter(output_filename, engine='openpyxl') as writer:
        for sheet_name, df in tqdm(sheets_to_write.items(), desc="Writing to Excel"):
            if sheet_name != "Raw" and not no_diffs:
                df = calculate_differences(df, target_fy=target_fy)

            df.to_excel(writer, sheet_name=sheet_name, index=False)

            if sheet_name != "Raw":
                _apply_number_formats(writer.sheets[sheet_name], df)

    print(f"Successfully saved and formatted multiple sheets to {output_filename}!")


def main(args):
    verbose = args.verbose
    if verbose:
        print(f"args: {args}")

    planned_fy = args.fiscal_year
    num_prev_years = args.num_prev_years
    no_diffs = args.no_diffs
    no_amounts = args.no_amounts
    no_positions = args.no_positions
    no_contracts = args.no_contracts
    latest_interim_only = args.latest_interim_only
    refresh_cache = args.refresh_cache
    max_workers = args.max_workers

    all_years_to_query = [planned_fy - i for i in range(num_prev_years + 1)]
    data_range = (max(all_years_to_query), min(all_years_to_query) - 1)

    app_key = get_app_key()

    # Create shorthand FY names
    planned_fy_name = f"FY{planned_fy % 100}"
    min_fy_name = f"FY{(min(all_years_to_query) - 1) % 100}"

    print("Analysis for:")
    print(f"\tAll fiscal years to query:\t{all_years_to_query}")
    print(f"\tData range:\t\t\t{data_range}")

    # 1. Fetch Data
    raw_df = fetch_data(app_key, all_years_to_query, max_workers=max_workers, refresh_cache=refresh_cache)

    raw_df = clean(raw_df, no_amounts=no_amounts, no_positions=no_positions, no_contracts=no_contracts, verbose=verbose)

    collapsed_df, new_numeric_cols = collapse(raw_df, latest_interim_only=latest_interim_only, verbose=verbose)

    if verbose:
        print()
        for c in collapsed_df.columns:
            print(c)
        print()

    # 2. Build Aggregation Dictionaries
    agg_levels = {
        "Agency": OUTPUT_ORDER[:2],
        "Unit of Appropriation": OUTPUT_ORDER[:4],
        "Responsibility Center": OUTPUT_ORDER[:6],
        "Budget Code": OUTPUT_ORDER[:8],
        "Object Class": OUTPUT_ORDER[:10],
        "Object Code": OUTPUT_ORDER[:12],
    }

    sheets_to_write = {
        "Raw": raw_df,
        "Collapsed": collapsed_df,
    }

    for level, group_by_cols in agg_levels.items():
        agg_df = pivot_by_cols(collapsed_df, group_by_cols, numeric_cols=new_numeric_cols)
        sheets_to_write[level] = agg_df

    if verbose:
        print(sheets_to_write.keys())

    if planned_fy_name != min_fy_name:
        output_filename = f"{planned_fy_name}_{min_fy_name}_expenses_v{VERSION}_{date.today()}.xlsx"
    else:
        output_filename = f"{planned_fy_name}_expenses_v{VERSION}_{date.today()}.xlsx"

    # 3. Write Excel workbook (diffs computed here, gated on --no_diffs)
    export_to_excel(sheets_to_write, output_filename, no_diffs=no_diffs, target_fy=planned_fy)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NYC Expense Budget Pipeline")
    parser.add_argument("--fiscal_year", type=int, default=2027, help="Target fiscal year for analysis. (Default: 2027)")
    parser.add_argument("--num_prev_years", type=int, default=0, help="Number of previous fiscal years for analysis. (Default: 0)")
    parser.add_argument("--no_diffs", action="store_true", help="Skips calculating differences between financial plans.")
    parser.add_argument("--no_amounts", action="store_true", help="Removes amount columns from analysis.")
    parser.add_argument("--no_positions", action="store_true", help="Removes position columns from analysis.")
    parser.add_argument("--no_contracts", action="store_true", help="Removes number of contract columns from analysis.")
    parser.add_argument("--latest_interim_only", action="store_true", help="Keeps prelim and exec releases only for the most recent fiscal year.")
    parser.add_argument("--refresh_cache", action="store_true", help="Bypasses the local per-fiscal-year cache and re-fetches all requested fiscal years from Socrata.")
    parser.add_argument("--max_workers", type=int, default=MAX_WORKERS_DEFAULT, help=f"Number of parallel worker threads for paginated API fetches. (Default: {MAX_WORKERS_DEFAULT})")
    parser.add_argument("--verbose", action="store_true", help="Print low-level debug detail (raw args, full column lists, per-release internals).")

    args = parser.parse_args()
    main(args)
