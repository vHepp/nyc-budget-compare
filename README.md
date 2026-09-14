# nyc-budget-compare

## Why this exists

New York City's expense budget has three official releases each fiscal year: **Preliminary**, **Executive**, and **Adopted**. Between each release, funding and staffing levels for individual agencies, programs, and object lines can shift. This project gives community and interest groups a way to track and condense those changes, so they can spot funding cuts, restorations, or shifts relevant to their cause, and use hard numbers to petition city government, testify at budget hearings, or brief members on what changed and why it matters.

## What it does

`apiv8.py` is the pipeline:

1. **Fetches** NYC's Expense Budget dataset from [NYC Open Data](https://data.cityofnewyork.us/) (Socrata dataset `mwzb-yiwb`) for a target fiscal year (and optional prior years).
2. **Tracks the release cycle**: labels each row as `prelim`, `exec`, or `adopt` based on its publication date.
3. **Collapses** the data so each budget line becomes one row with a column per release (e.g. `FY2027_prelim_financial_plan_amount`, `FY2027_exec_financial_plan_amount`, `FY2027_adopt_financial_plan_amount`), instead of one row per release.
4. **Computes changes**: dollar and percent differences between releases (e.g. Executive vs. Preliminary) and against the prior year's adopted/modified budget, so a reader can immediately see something like _"Department X's Executive plan cut this program's budget 12% versus the Preliminary plan."_
5. **Aggregates and exports** to a multi-sheet Excel workbook at six levels of detail (Agency, Unit of Appropriation, Responsibility Center, Budget Code, Object Class, and Object Code), so a group can look at the citywide picture or drill into a single line item.

## Repo layout

- **`apiv8.py`**: the pipeline script. This is the one to run.
- **`data_cache/`**: local cache of raw API pulls, one file per fiscal year (gitignored; rebuilt automatically as needed).
- **`Docs/`**: Some official NYC Office of Management and Budget release documents kept for manual reference: `erc*.pdf` (Adopted Expense/Revenue/Contract volume), `perc*.pdf` (Preliminary version of the same), `ss*.pdf` (Supporting Schedules), and `Expense_Budget_Data_Dictionary.xlsx` (field definitions for the Socrata dataset).

## Setup

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
2. Get a Socrata app token at the [NYC Open Data developer settings page](https://data.cityofnewyork.us/profile/edit/developer_settings), then:

   ```
   cp .env.example .env
   ```

   and fill in `SOCRATA_APP_KEY` in `.env`.

## Usage

```
python apiv8.py --fiscal_year 2027
```

| Flag                    | Description                                                           | Default |
| ----------------------- | --------------------------------------------------------------------- | ------- |
| `--fiscal_year`         | Target fiscal year to analyze.                                        | `2027`  |
| `--num_prev_years`      | Number of additional prior fiscal years to include.                   | `0`     |
| `--no_diffs`            | Skip computing $ / % change columns.                                  | off     |
| `--no_amounts`          | Exclude dollar-amount columns.                                        | off     |
| `--no_positions`        | Exclude headcount/position columns.                                   | off     |
| `--no_contracts`        | Exclude number-of-contracts columns.                                  | off     |
| `--latest_interim_only` | For prior years (not the target year), keep only the Adopted release. | off     |
| `--refresh_cache`       | Bypass the local cache and re-fetch all requested fiscal years.       | off     |
| `--max_workers`         | Parallel worker threads for paginated API fetches.                    | `6`     |

Each run produces a dated `.xlsx` file (e.g. `FY27_FY26_expenses_v8_2026-09-06.xlsx`) in the working directory.

## Reading the output

The workbook has one sheet per aggregation level (plus `Raw` and `Collapsed`). Unless `--no_diffs` is set, each sheet (other than `Raw`) includes change columns named:

- `FY{year}_{later}_vs_{earlier}_{family}_change` / `_pct_change`: comparing two releases within the target year, e.g. `FY2027_exec_vs_prelim_amount_pct_change`.
- `FY{year}_{release}_vs_FY{year-1}_{adopted|modified}_{family}_change` / `_pct_change`: comparing a release against the prior year's adopted or current-modified baseline, e.g. `FY2027_adopt_vs_FY2026_adopted_amount_pct_change`.

`{family}` is `amount`, `position` (headcount), or `number_of_contracts`; `%change` is only computed for dollar amounts.
