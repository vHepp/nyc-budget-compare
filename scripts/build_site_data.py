"""
Builds the static JSON data the web explorer (web/) reads, reusing apiv8.py's pipeline.

    python scripts/build_site_data.py --fiscal_years 2026 2027 --out web/public/data
    python scripts/build_site_data.py --latest 2      # newest FY in the dataset + the one before

Output layout (all JSON is columnar: {"columns": [...], "rows": [[...], ...]}):

    index.json                          FYs, releases + publication dates, value keys, build time
    fy{FY}/agency.json                  Agency level
    fy{FY}/uoa.json                     Unit of Appropriation level
    fy{FY}/rc.json                      Responsibility Center level
    fy{FY}/by_agency/{agency}.json      {"bc": ..., "oclass": ..., "ocode": ...} for one agency
    fy{FY}/FY{yy}_expenses.xlsx         full workbook (same as the CLI produces), unless --no_xlsx

Rows hold the *codes* of every ancestor level plus the row's own code and name, followed by the
value columns. Value columns use short keys like "exec.amount" or "prior_adopted.position"
(see VALUE_KEY_RE); the frontend computes changes from these with the same formula as
apiv8.calculate_differences / safe_pct_change.
"""
import argparse
import json
import math
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import apiv8  # noqa: E402

DATASET_URL = f"https://data.cityofnewyork.us/d/{apiv8.EXPENSE_DATASET_ID}"

# (short level key, AGG_LEVELS sheet name, code column, name column)
LEVELS = [
    ("agency", "Agency", "agency_number", "agency_name"),
    ("uoa", "Unit of Appropriation", "unit_appropriation_number", "unit_appropriation_name"),
    ("rc", "Responsibility Center", "responsibility_center_code", "responsibility_center_name"),
    ("bc", "Budget Code", "budget_code_number", "budget_code_name"),
    ("oclass", "Object Class", "object_class_number", "object_class_name"),
    ("ocode", "Object Code", "object_code", "object_code_name"),
]
WHOLE_FILE_LEVELS = {"agency", "uoa", "rc"}  # small; the rest are sharded per agency

BASELINE_KEYS = {"adopted_budget": "prior_adopted", "current_modified_budget": "prior_modified"}
RELEASE_LABELS = {"prelim": "Preliminary", "exec": "Executive", "adopt": "Adopted"}


def value_key_map(numeric_cols: List[str], fy: int) -> Dict[str, str]:
    """Maps apiv8's collapsed column names to short keys ("exec.amount", "prior_adopted.amount")."""
    rel = "|".join(apiv8.RELEASE_NAMES)
    fam = "|".join(apiv8.NUMERIC_FAMILIES)
    base = "|".join(BASELINE_KEYS)
    plan_re = re.compile(rf"^FY{fy}_(?P<r>{rel})_financial_plan_(?P<f>{fam})$")
    base_re = re.compile(rf"^FY{fy - 1}_(?P<k>{base})_(?P<f>{fam})$")

    out = {}
    for col in numeric_cols:
        if m := plan_re.match(col):
            out[col] = f"{m['r']}.{m['f']}"
        elif m := base_re.match(col):
            out[col] = f"{BASELINE_KEYS[m['k']]}.{m['f']}"
        else:
            raise ValueError(f"Unrecognized numeric column {col!r}; update value_key_map()")
    return out


def _num(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    r = round(float(v), 2)
    return int(r) if r.is_integer() else r


def to_columnar(df: pd.DataFrame, dim_cols: List[str], value_cols: List[str], key_map: Dict[str, str]) -> dict:
    sub = df[dim_cols + value_cols]
    rows = [
        [*(str(x) for x in rec[:len(dim_cols)]), *(_num(x) for x in rec[len(dim_cols):])]
        for rec in sub.itertuples(index=False, name=None)
    ]
    return {"columns": dim_cols + [key_map[c] for c in value_cols], "rows": rows}


def write_json(path: Path, obj) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, separators=(",", ":"), allow_nan=False)
    path.write_text(text)
    return len(text)


def release_dates(raw_df: pd.DataFrame, fy: int) -> Dict[str, str]:
    sub = raw_df[raw_df["fiscal_year"] == str(fy)][["release_type", "publication_date"]].dropna()
    pairs = sub.drop_duplicates().sort_values("publication_date")
    return {r: pd.to_datetime(str(d)).date().isoformat()  # Socrata gives "20260512"
            for r, d in zip(pairs["release_type"], pairs["publication_date"])
            if r in apiv8.RELEASE_NAMES}


def build_fy(fy: int, out_dir: Path, app_key, write_xlsx: bool, refresh_cache: bool) -> dict:
    sheets, numeric_cols = apiv8.build_tables(fy, 0, app_key=app_key, refresh_cache=refresh_cache)
    key_map = value_key_map(numeric_cols, fy)
    value_cols = sorted(numeric_cols, key=lambda c: key_map[c])
    fy_dir = out_dir / f"fy{fy}"
    if fy_dir.exists():
        shutil.rmtree(fy_dir)

    sizes = {}
    shards: Dict[str, Dict[str, dict]] = {}
    for i, (key, sheet, code_col, name_col) in enumerate(LEVELS):
        ancestor_codes = [lv[2] for lv in LEVELS[:i]]
        dims = ancestor_codes + [code_col, name_col]
        df = sheets[sheet]
        if key in WHOLE_FILE_LEVELS:
            sizes[f"{key}.json"] = write_json(fy_dir / f"{key}.json", to_columnar(df, dims, value_cols, key_map))
        else:
            for agency, grp in df.groupby("agency_number", sort=True):
                shards.setdefault(str(agency), {})[key] = to_columnar(grp, dims, value_cols, key_map)

    shard_sizes = [write_json(fy_dir / "by_agency" / f"{a}.json", s) for a, s in shards.items()]
    sizes["by_agency (max)"] = max(shard_sizes, default=0)
    sizes["by_agency (total)"] = sum(shard_sizes)

    xlsx_name = None
    if write_xlsx:
        xlsx_name = f"FY{fy % 100}_expenses.xlsx"
        apiv8.export_to_excel(sheets, str(fy_dir / xlsx_name), no_diffs=False, target_fy=fy)

    print(f"FY{fy} output sizes (bytes): " + ", ".join(f"{k}={v:,}" for k, v in sizes.items()))
    present = sorted({k.split(".")[0] for k in key_map.values()})
    return {
        "fiscal_year": fy,
        "releases": release_dates(sheets["Raw"], fy),
        "series": present,
        "families": sorted({k.split(".")[1] for k in key_map.values()}),
        "xlsx": xlsx_name,
        "rows": {k: len(sheets[s]) for k, s, *_ in LEVELS},
    }


def latest_fiscal_year(app_key) -> int:
    result = apiv8._build_client(app_key).get(apiv8.EXPENSE_DATASET_ID, select="MAX(fiscal_year) AS fy")
    return int(result[0]["fy"])


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    years = p.add_mutually_exclusive_group(required=True)
    years.add_argument("--fiscal_years", type=int, nargs="+", help="Explicit fiscal years to build.")
    years.add_argument("--latest", type=int, metavar="N",
                       help="Build the newest fiscal year in the dataset plus the N-1 before it.")
    p.add_argument("--out", type=Path, default=ROOT / "web" / "public" / "data")
    p.add_argument("--no_xlsx", action="store_true", help="Skip writing the per-FY Excel workbook.")
    p.add_argument("--refresh_cache", action="store_true")
    args = p.parse_args()

    app_key = apiv8.get_app_key()
    if args.latest:
        newest = latest_fiscal_year(app_key)
        wanted = [newest - i for i in range(args.latest)]
        print(f"Newest fiscal year in dataset: FY{newest}; building {wanted}")
    else:
        wanted = args.fiscal_years
    fys = [build_fy(fy, args.out, app_key, not args.no_xlsx, args.refresh_cache)
           for fy in sorted(set(wanted), reverse=True)]

    index = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": DATASET_URL,
        "pipeline_version": apiv8.VERSION,
        "release_labels": RELEASE_LABELS,
        "levels": [{"key": k, "label": s, "code": c, "name": n} for k, s, c, n in LEVELS],
        "sharded_levels": [k for k, *_ in LEVELS if k not in WHOLE_FILE_LEVELS],
        "fiscal_years": fys,
    }
    write_json(args.out / "index.json", index)
    print(f"Wrote {args.out / 'index.json'}")


if __name__ == "__main__":
    main()
