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

There is also a **web explorer** (`web/`) built from the same pipeline: drill from citywide down to object codes, compare any two releases, see the largest cuts and increases as charts, download CSVs, and copy a link to the exact view for testimony or a brief. See [Web explorer](#web-explorer).

## Repo layout

- **`apiv8.py`**: the pipeline script and Excel CLI.
- **`scripts/build_site_data.py`**: turns the pipeline's output into static JSON for the web explorer.
- **`web/`**: the web explorer (React + Vite, static, hosted on GitHub Pages).
- **`tests/`**: pipeline tests (`pytest`).
- **`data_cache/`**: local cache of raw API pulls, one file per fiscal year (gitignored; rebuilt automatically as needed).

## Setup

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
2. (Optional) A Socrata app token raises the API's rate limit; the program runs fine without one. To add one, get a token at the [NYC Open Data developer settings page](https://data.cityofnewyork.us/profile/edit/developer_settings), then:

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

| `--verbose`             | Print low-level debug detail.                                         | off     |

Each run produces a dated `.xlsx` file (e.g. `FY27_FY26_expenses_v9_2026-09-06.xlsx`) in the working directory.

## Reading the output

The workbook has one sheet per aggregation level (plus `Raw` and `Collapsed`). Unless `--no_diffs` is set, each sheet (other than `Raw`) includes change columns named:

- `FY{year}_{later}_vs_{earlier}_{family}_change` / `_pct_change`: comparing two releases within the target year, e.g. `FY2027_exec_vs_prelim_amount_pct_change`.
- `FY{year}_{release}_vs_FY{year-1}_{adopted|modified}_{family}_change` / `_pct_change`: comparing a release against the prior year's adopted or current-modified baseline, e.g. `FY2027_adopt_vs_FY2026_adopted_amount_pct_change`.

`{family}` is `amount`, `position` (headcount), or `number_of_contracts`; `%change` is only computed for dollar amounts.

## Web explorer

The explorer is a static site, so there is no server to run. A build script precomputes the data, and GitHub Actions rebuilds and redeploys it every week, so new budget releases appear without manual work.

### Run it locally

```
pip install -r requirements.txt
python scripts/build_site_data.py --fiscal_years 2026 2027 --no_xlsx   # writes web/public/data/
cd web
npm install
npm run dev
```

Leave out `--no_xlsx` to also publish each year's full Excel workbook as a download on the site (slower). `--latest 2` builds the newest fiscal year in the dataset and the one before it.

### Deploy to GitHub Pages

1. In the repo settings, go to **Pages** and set the source to **GitHub Actions**.
2. (Optional) Add a `SOCRATA_APP_KEY` repository secret.
3. Push to `main`, or run the **Build and deploy site** workflow by hand. It also runs every Monday. The `NUM_FISCAL_YEARS` setting in `.github/workflows/deploy.yml` controls how many years are published.

### Sharing a view

Everything on screen is stored in the URL: fiscal year, the drill-down path, the comparison, the measure (dollars, positions or contracts), sorting and search. **Copy link** gives a link that opens exactly that view, e.g. `…/#/2027/agency/040?cmp=adopt~exec&sort=pct`.

