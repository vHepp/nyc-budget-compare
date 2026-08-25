import argparse
import os
from datetime import date
from pathlib import Path
from typing import List, Dict, Any

import numpy as np
import pandas as pd
from openpyxl.utils import get_column_letter
from sodapy import Socrata
from tqdm.auto import tqdm

# --- Configuration & Constants ---
APP_KEY = os.getenv("SOCRATA_APP_KEY", "t2GPRE1GXlktxvqOIFMelPIvT")
VERSION = "7"
EXPENSE_DATASET_ID = "mwzb-yiwb"
RELEASE_NAMES = ["prelim", "exec", "adopt"]
ROOT = Path.cwd()

DATA_CACHE = ROOT / "data_cache"

# Define Categorical Columns

TARGET_CATEGORICAL_COL_CODES = [
    "agency_number", "unit_appropriation_number", 
    "responsibility_center_code",  "budget_code_number", 
     "object_class_number",  "object_code"]
TARGET_CATEGORICAL_COL_NAMES = [
     "agency_name",  "unit_appropriation_name",
     "responsibility_center_name", 
    "budget_code_name", "object_class_name",
     "intra_city_purchase_code", 
    "object_code_name","personal_service_other_than_personal_service_indicator",
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

TARGET_CATEGORICAL_COL_CODES


TARGET_CATEGORICAL_COLS = TARGET_CATEGORICAL_COL_CODES + TARGET_CATEGORICAL_COL_NAMES

ALL_CATEGORICAL_COLS = ["publication_date", "fiscal_year", "release_type"] + TARGET_CATEGORICAL_COLS

CATEGORY_DTYPES_MAP = {col: str for col in ALL_CATEGORICAL_COLS}


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


def safe_pct_change(change_series: pd.Series, base_series: pd.Series) -> pd.Series:
    """Helper function to calculate percent change and avoid division-by-zero errors."""
    return change_series.div(base_series).replace([np.inf, -np.inf], np.nan)


def fetch_data(client: Socrata, all_years_to_query: list) -> pd.DataFrame:
    """Fetches data from Socrata API or loads it from local cache."""
    DATA_CACHE.mkdir(parents=True, exist_ok=True)
    
    
    if len(all_years_to_query)>1:
        fy_range_str = f"{max(all_years_to_query)}_{min(all_years_to_query)}"
        cache_path = DATA_CACHE / f"backup_{fy_range_str}_v{VERSION}.csv"
    else:
        cache_path = DATA_CACHE / f"backup_{max(all_years_to_query)}_v{VERSION}.csv"

    if cache_path.exists():
        print(f"Loading cached data for fiscal years {all_years_to_query} from {cache_path}...")
        return pd.read_csv(cache_path,dtype=CATEGORY_DTYPES_MAP)

    print(f"No cached data from {cache_path} found. Querying Socrata for fiscal years {all_years_to_query}...\n")
    
    s = ""
    for y in all_years_to_query:
        s += f"{y},"
        
    s = s[:-1]
    
    
    where_string = f"fiscal_year IN ({s})"
    
    print(where_string)
    
    count_result = client.get(EXPENSE_DATASET_ID, select="COUNT(*)", where=where_string)
    total_rows = int(count_result[0]['COUNT'])
    print(f"Total rows to fetch: {total_rows}")

    orderby_string = ", ".join([
        "agency_number", "unit_appropriation_number", "responsibility_center_code",
        "budget_code_number", "object_class_number", "object_code", "publication_date DESC"
    ])

    data = []
    offset = 0
    limit = 1000

    with tqdm(total=total_rows, desc="Downloading Data", unit="rows") as pbar:
        while True:
            temp = client.get(
                dataset_identifier=EXPENSE_DATASET_ID,
                
                where=where_string,
                order=orderby_string,
                limit=limit,
                offset=offset
            )
            if not temp:
                break
            
            data.extend(temp)
            pbar.update(len(temp))
            offset += limit

    print(f"End of query. Successfully fetched {len(data)} total rows.")
    df = pd.DataFrame.from_records(data)
    
    
    # adding release_type column
    releases_map = {}
    for y in all_years_to_query:
        y_releases = sorted(df[df["fiscal_year"] == str(y)]["publication_date"].unique().tolist())
        
        y_releases_zip = zip(y_releases, RELEASE_NAMES[:len(y_releases)])
        # print(y_releases_zip)
        
        for y, r in y_releases_zip:
            releases_map.update({y:r})
    
    print(f"releases_map: {releases_map}")
    
    df['release_type'] = df["publication_date"].map(releases_map)
        
    df.to_csv(cache_path, index=False)
    
    return df

def clean(df: pd.DataFrame, verbose:bool = False) -> pd.DataFrame:
    df[TARGET_CATEGORICAL_COLS] = df[TARGET_CATEGORICAL_COLS].astype(str)
    
    for cat_col in TARGET_CATEGORICAL_COLS:
        if cat_col in df.columns:
            df[cat_col] = df[cat_col].str.upper()
    
    #filling empty categorical cells with "(blank)"
    df[TARGET_CATEGORICAL_COLS] = df[TARGET_CATEGORICAL_COLS].fillna("(blank)")
    
    # Explicitly aggregate numerical columns to prevent Pandas 2.0+ TypeErrors
    df = df.groupby(ALL_CATEGORICAL_COLS, dropna=False)[NUMERICAL_COLS].sum().reset_index()
    
    # sort by hierarchy
    order = TARGET_CATEGORICAL_COL_CODES + ["publication_date"]
    ascending = [True] * len(TARGET_CATEGORICAL_COL_CODES) + [False]
    
    if verbose:
        print(f"column, direction\n")
        for o,a in zip(order, ascending):
            if a:
                print(f"{o}, ascending")
            else:
                print(f"{o}, descending")
                
    return df.sort_values(by=order, ascending=ascending).reset_index(drop=True)

def collapse(clean_df: pd.DataFrame, verbose:bool = False) -> pd.DataFrame:
    
    collapsed_df = clean_df[TARGET_CATEGORICAL_COLS].drop_duplicates().reset_index(drop=True)
    
    years_arr = sorted(clean_df['fiscal_year'].unique())
    
    if verbose:
        print(f"num_years: {len(years_arr)}")
        print(years_arr)

    for fy in years_arr:
        if verbose:
            print(f"FY {fy}")
            
        fy_df = clean_df[clean_df['fiscal_year'] == fy]
        
        releases_arr = sorted(fy_df['release_type'].unique(),reverse=True)
        
        # present_releases = [r for r in RELEASE_NAMES if r in fy_df['release_type'].unique()]

        num_releases = len(releases_arr)

        if verbose:
            print(f"num_releases: {num_releases}")
            print(releases_arr)
        # print()
        
        for j, release_type in enumerate(releases_arr):
            if verbose:
                print(f"Release {j}: {release_type}")

            fy_release_df = fy_df[fy_df['release_type'] == release_type]
            
            fy_release_df = fy_release_df.drop(columns=["publication_date", "fiscal_year", "release_type"])
            
            
            
            fy_release_rename_map = rename_cols(fy, release_type)
            
            fy_release_renamed_df = fy_release_df.rename(columns=fy_release_rename_map)
            # print("DEBUG 2")

            if j < num_releases - 1:
                drop_cols = [
                    'adopted_budget_amount',
                    'current_modified_budget_amount',
                    'adopted_budget_position',
                    'current_modified_budget_position',
                    'adopted_budget_number_of_contracts',
                    'current_modified_budget_number_of_contracts']
                fy_release_renamed_df = fy_release_renamed_df.drop(columns=[fy_release_rename_map.get(col_name) for col_name in drop_cols])
            # print("DEBUG 3")

            # fy_release_renamed_df
            collapsed_df = collapsed_df.merge(right=fy_release_renamed_df,on=TARGET_CATEGORICAL_COLS, how='left')
    
        if verbose:
            print()
            print(collapsed_df.columns)    
            print()
    
    new_numeric_cols = list(set(collapsed_df.columns) - set(TARGET_CATEGORICAL_COLS))
    new_numeric_cols = sorted(new_numeric_cols)
    print(new_numeric_cols)
    
    collapsed_df[new_numeric_cols] = collapsed_df[new_numeric_cols].fillna(0)
    collapsed_df = collapsed_df[OUTPUT_ORDER + new_numeric_cols]
    
    return collapsed_df, new_numeric_cols

def rename_cols(fy:str, release_type:str) -> dict:
    return {
    'adopted_budget_amount' : f'FY{int(fy) - 1}_adopted_budget_amount',
    'current_modified_budget_amount' : f'FY{int(fy) - 1}_current_modified_budget_amount',

    'adopted_budget_position' : f'FY{int(fy) - 1}_adopted_budget_position',
    'current_modified_budget_position' : f'FY{int(fy) - 1}_current_modified_budget_position',
    
    'adopted_budget_number_of_contracts' : f'FY{int(fy) - 1}_adopted_budget_number_of_contracts',
    'current_modified_budget_number_of_contracts' : f'FY{int(fy) - 1}_current_modified_budget_number_of_contracts',
    
    'financial_plan_amount' : f'FY{fy}_{release_type}_financial_plan_amount',
    'financial_plan_position' : f'FY{fy}_{release_type}_financial_plan_position',
    'financial_plan_number_of_contracts' : f'FY{fy}_{release_type}_financial_plan_number_of_contracts'
    }

def pivot_by_cols(df: pd.DataFrame, group_by_cols: list, numeric_cols: list) -> pd.DataFrame:
    
    return df[group_by_cols + numeric_cols].groupby(by = group_by_cols, dropna=False).sum().reset_index()
    

def calculate_differences(df: pd.DataFrame, num_pubs_this_year: int, current_fy_name: str, 
                          str_sum_financial_plan_amount: str, str_sum_financial_plan_position: str, 
                          str_sum_financial_plan_number_of_contracts: str, 
                          str_sum_current_adopted_amount: str, str_sum_current_modified_amount: str,
                          str_sum_current_adopted_position: str, str_sum_current_modified_position: str,
                          str_sum_current_adopted_number_of_contracts: str, str_sum_current_modified_number_of_contracts: str,
                          include_contracts: bool) -> pd.DataFrame:
    """Adds difference and percentage change columns to the dataframe."""
    diff_df = df.copy()

    for i in range(num_pubs_this_year):
        i_amount_name = f"{str_sum_financial_plan_amount}_{RELEASE_NAMES[i]}"
        i_position_name = f"{str_sum_financial_plan_position}_{RELEASE_NAMES[i]}"
        i_contracts_name = f"{str_sum_financial_plan_number_of_contracts}_{RELEASE_NAMES[i]}"

        # Amount Changes vs Adopted/Modified
        diff_df[f"{str_sum_financial_plan_amount}_change_{RELEASE_NAMES[i]}-{current_fy_name}_adopt"] = df[i_amount_name] - df[str_sum_current_adopted_amount]
        diff_df[f"{str_sum_financial_plan_amount}_%change_{RELEASE_NAMES[i]}-{current_fy_name}_adopt"] = safe_pct_change(diff_df[f"{str_sum_financial_plan_amount}_change_{RELEASE_NAMES[i]}-{current_fy_name}_adopt"], df[str_sum_current_adopted_amount])

        diff_df[f"{str_sum_financial_plan_amount}_change_{RELEASE_NAMES[i]}-{current_fy_name}_modified"] = df[i_amount_name] - df[str_sum_current_modified_amount]
        diff_df[f"{str_sum_financial_plan_amount}_%change_{RELEASE_NAMES[i]}-{current_fy_name}_modified"] = safe_pct_change(diff_df[f"{str_sum_financial_plan_amount}_change_{RELEASE_NAMES[i]}-{current_fy_name}_modified"], df[str_sum_current_modified_amount])

        # Position Changes vs Adopted/Modified
        diff_df[f"{str_sum_financial_plan_position}_change_{RELEASE_NAMES[i]}-{current_fy_name}_adopt"] = df[i_position_name] - df[str_sum_current_adopted_position]
        diff_df[f"{str_sum_financial_plan_position}_change_{RELEASE_NAMES[i]}-{current_fy_name}_modified"] = df[i_position_name] - df[str_sum_current_modified_position]

        # Contract Changes vs Adopted/Modified
        if include_contracts:
            diff_df[f"{str_sum_financial_plan_number_of_contracts}_change_{RELEASE_NAMES[i]}-{current_fy_name}_adopt"] = df[i_contracts_name] - df[str_sum_current_adopted_number_of_contracts]
            diff_df[f"{str_sum_financial_plan_number_of_contracts}_change_{RELEASE_NAMES[i]}-{current_fy_name}_modified"] = df[i_contracts_name] - df[str_sum_current_modified_number_of_contracts]

        # Release-to-Release comparisons (e.g., exec vs prelim)
        for j in range(i):
            j_amount_name = f"{str_sum_financial_plan_amount}_{RELEASE_NAMES[j]}"
            j_position_name = f"{str_sum_financial_plan_position}_{RELEASE_NAMES[j]}"
            j_contracts_name = f"{str_sum_financial_plan_number_of_contracts}_{RELEASE_NAMES[j]}"

            diff_df[f"{str_sum_financial_plan_amount}_change_{RELEASE_NAMES[i]}-{RELEASE_NAMES[j]}"] = df[i_amount_name] - df[j_amount_name]
            diff_df[f"{str_sum_financial_plan_amount}_%change_{RELEASE_NAMES[i]}-{RELEASE_NAMES[j]}"] = safe_pct_change(diff_df[f"{str_sum_financial_plan_amount}_change_{RELEASE_NAMES[i]}-{RELEASE_NAMES[j]}"], df[j_amount_name])

            diff_df[f"{str_sum_financial_plan_position}_change_{RELEASE_NAMES[i]}-{RELEASE_NAMES[j]}"] = df[i_position_name] - df[j_position_name]
            
            if include_contracts:
                diff_df[f"{str_sum_financial_plan_number_of_contracts}_change_{RELEASE_NAMES[i]}-{RELEASE_NAMES[j]}"] = df[i_contracts_name] - df[j_contracts_name]

    return diff_df


def export_to_excel(sheets_to_write: Dict[str, pd.DataFrame], output_filename: str, diff_kwargs: dict):
    """Writes standard and collapsed dataframes to an Excel file with formatting."""
    with pd.ExcelWriter(output_filename, engine='openpyxl') as writer:
        for k, (sheet_name, df) in enumerate(tqdm(sheets_to_write.items(), desc="Writing to Excel")):
            
            # Apply differences logic to all sheets except "Raw"
            if k > 0:
                df = calculate_differences(df, **diff_kwargs)
            
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            
            # Formatting for non-raw sheets
            if sheet_name != "Raw":
                worksheet = writer.sheets[sheet_name]
                for col_idx, col_name in enumerate(df.columns, start=1):
                    if col_name not in ALL_CATEGORICAL_COLS:
                        col_lower = col_name.lower()
                        if "position" in col_lower or "contract" in col_lower:
                            num_format = '#,##0'
                        elif "%" in col_lower or "percent" in col_lower:
                            num_format = '0.0%'
                        elif "amount" in col_lower:
                            num_format = '$#,##0'
                        else:
                            num_format = '#,##0'
                        
                        for row in range(2, worksheet.max_row + 1):
                            worksheet.cell(row=row, column=col_idx).number_format = num_format
                        
                        col_letter = get_column_letter(col_idx)
                        worksheet.column_dimensions[col_letter].width = 22

    print(f"Successfully saved and formatted multiple sheets to {output_filename}!")


def main(args):
    print(f"args: {args}")
    
    # Pull args
    planned_fy = args.fiscal_year
    num_prev_years = args.num_prev_years
    no_diffs=args.no_diffs
    include_contracts=args.include_contracts
    
    
    all_years_to_query = [int(planned_fy) - i for i in range(num_prev_years+1)]
    data_range = (max(all_years_to_query), min(all_years_to_query) - 1)
    
    # Connect to client using app api key
    client = Socrata("data.cityofnewyork.us", APP_KEY, timeout=180)
    
    # Create shorthand FY names
    planned_fy_name = f"FY{planned_fy % 100}"
    current_fy_name = f"FY{(planned_fy - 1) % 100}"
    
    
    
    
    print(f"Analysis for:")
    # print(f"\tPlanned fiscal year:\t\t{planned_fy_name}")
    print(f"\tAll fiscal years to query:\t{all_years_to_query}")
    print(f"\tData range:\t\t\t{data_range}")
    

    # 1. Fetch Data
    raw_df = fetch_data(client, all_years_to_query) 
    
    raw_df = clean(raw_df)
    
    collapsed_df, new_numeric_cols = collapse(raw_df, verbose=True)
    
    print()
    for c in collapsed_df.columns:
        print(c)
    print()
   
    
    
    # 5. Build Aggregation Dictionaries
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
        # "Agency": Agency_collapsed_df,
        # "Unit of Appropriation": UoA_collapsed_df,
        # "Responsibility Center": RC_collapsed_df,
        # "Budget Code": budget_code_collapsed_df,
        # "Object Class": object_class_collapsed_df,
        # "Object Code": object_code_collapsed_df,
    }
    
    for level in agg_levels.keys():
        print(level)
    
        agg_df = pivot_by_cols(collapsed_df, agg_levels[level], numeric_cols = new_numeric_cols)
        # agg_df = pivot_by_cols(collapsed_df, agg_levels[level] + ["financial_plan_savings_flag"], numeric_cols = new_numeric_cols)
        
        sheets_to_write.update({level:agg_df})
    
    print(sheets_to_write.keys())
    
    # UoA_df = pivot_by_cols(collapsed_df, agg_levels['Unit of Appropriation'] + ["financial_plan_savings_flag"], numeric_cols = new_numeric_cols)
    
    # RC_df = pivot_by_cols(collapsed_df, agg_levels['Responsibility Center'] + ["financial_plan_savings_flag"], numeric_cols = new_numeric_cols)
    
    # budget_df = pivot_by_cols(collapsed_df, agg_levels['Budget Code'] + ["financial_plan_savings_flag"], numeric_cols = new_numeric_cols)
    
    # object_class_df = pivot_by_cols(collapsed_df, agg_levels['Object Class'] + ["financial_plan_savings_flag"], numeric_cols = new_numeric_cols)
    
    # object_code_df = pivot_by_cols(collapsed_df, agg_levels['Object Code'] + ["financial_plan_savings_flag"], numeric_cols = new_numeric_cols)
    
    # print(object_code_df)
    
    
    # object_code_df.to_excel("object_code_df.xlsx", index=False)
    # print("saved temp.xlsx")
    
    output_filename = f"{planned_fy_name}_expenses_v{VERSION}_{date.today()}.xlsx"
    
    

    with pd.ExcelWriter(output_filename, engine='openpyxl') as writer:
        for k, (sheet_name, df) in enumerate(tqdm(sheets_to_write.items())):
            
            # print(k)
            
            # ---> APPLY DIFFERENCES HERE <---
            # Only apply if no_diffs is False and it's not the Raw sheet
            if k > 0 and not args.no_diffs:
                # Warning: You need to define the diff_kwargs variables for this to run!
                # df = calculate_differences(df, **diff_kwargs) 
                pass 
            
            # A. Write the dataframe to the current sheet
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            
            
            # Formating
            if sheet_name != "Raw":
                
                # B. Access the active openpyxl worksheet object pandas just generated
                worksheet = writer.sheets[sheet_name]
                
                # C. Loop through the columns of the DataFrame
                # (enumerate start=1 because Excel columns are 1-indexed: A=1, B=2...)
                for col_idx, col_name in enumerate(df.columns, start=1):
                    
                    # Check if this column is one of your targets
                    if col_name not in ALL_CATEGORICAL_COLS:
                        
                        # Assign formatting style: Currency vs Headcount Positions
                        # if "position" in col_name.lower() or "contract" in col_name.lower():
                        #     num_format = '#,##0'   
                        # elif "%" in col_name.lower():
                        #     num_format = '#,##0'   
                        # elif "amount" in col_name.lower():
                        #     num_format = '$#,##0'  
                        # else:
                        #     num_format = '#,##0'   
                        
                        # --- FORMATTING BLOCK ---
                        if "position" in col_name.lower() or "contract" in col_name.lower():
                            num_format = '#,##0'   
                        elif "%" in col_name.lower() or "percent" in col_name.lower():
                            num_format = '0.0%'  
                        elif "amount" in col_name.lower():
                            num_format = '$#,##0'  
                        else:
                            num_format = '#,##0'   
                        # -----------------------------------
                        
                        # Apply the format to every cell in this column, skipping the header (row 1)
                        for row in range(2, worksheet.max_row + 1):
                            worksheet.cell(row=row, column=col_idx).number_format = num_format
                        
                        # BONUS: Set a wider column width so Excel doesn't clip numbers into '###'
                        col_letter = get_column_letter(col_idx)
                        worksheet.column_dimensions[col_letter].width = 22
                            
    print(f"Successfully saved and formatted multiple sheets to {output_filename}!")


    return

    
    diff_kwargs = {
        "num_pubs_this_year": num_pubs_this_year,
        "current_fy_name": current_fy_name,
        "str_sum_financial_plan_amount": str_sum_financial_plan_amount,
        "str_sum_financial_plan_position": str_sum_financial_plan_position,
        "str_sum_financial_plan_number_of_contracts": str_sum_financial_plan_number_of_contracts,
        "str_sum_current_adopted_amount": str_sum_current_adopted_amount,
        "str_sum_current_modified_amount": str_sum_current_modified_amount,
        "str_sum_current_adopted_position": str_sum_current_adopted_position,
        "str_sum_current_modified_position": str_sum_current_modified_position,
        "str_sum_current_adopted_number_of_contracts": str_sum_current_adopted_number_of_contracts,
        "str_sum_current_modified_number_of_contracts": str_sum_current_modified_number_of_contracts,
        "include_contracts": args.include_contracts
    }

    export_to_excel(sheets_to_write, output_filename, diff_kwargs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NYC Expense Budget Pipeline")
    parser.add_argument("--fiscal_year", type=int, default=2027, help="Target fiscal year for analysis. (Default: 2027)")
    parser.add_argument("--num_prev_years", type=int, default=0, help="Number of previous fiscal years for analysis. (Default: 0)")
    parser.add_argument("--no_diffs", action="store_true", help="Skips calculating differences between financial plans.")
    parser.add_argument("--include_contracts", action="store_true", help="Includes number of contracts columns in analysis.")
    
    args = parser.parse_args()
    main(args)