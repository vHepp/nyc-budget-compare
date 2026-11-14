"""Offline tests for the pure transformation steps of apiv8.py (no network)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import apiv8  # noqa: E402

FY = 2027
DATES = {"prelim": "2026-01-15T00:00:00.000", "exec": "2026-04-25T00:00:00.000", "adopt": "2026-06-30T00:00:00.000"}


def _line(code: str, name: str, **overrides) -> dict:
    row = {c: "X" for c in apiv8.TARGET_CATEGORICAL_COLS}
    row.update({"agency_number": "040", "agency_name": "EDUCATION",
                "object_code": code, "object_code_name": name})
    row.update(overrides)
    return row


def _raw_rows() -> pd.DataFrame:
    """Two object codes x three releases, plus one row with a missing category value."""
    plans = {  # financial_plan_amount per release
        ("100", "SALARIES"): {"prelim": 100.0, "exec": 80.0, "adopt": 120.0},
        ("200", "SUPPLIES"): {"prelim": 0.0, "exec": 50.0, "adopt": 50.0},
    }
    rows = []
    for (code, name), by_release in plans.items():
        for release, amount in by_release.items():
            r = _line(code, name)
            r.update({
                "publication_date": DATES[release], "fiscal_year": str(FY),
                "adopted_budget_amount": "90", "current_modified_budget_amount": "95",
                "financial_plan_amount": str(amount),
                "adopted_budget_position": "1", "current_modified_budget_position": "1",
                "financial_plan_position": "2",
                "adopted_budget_number_of_contracts": "0", "current_modified_budget_number_of_contracts": "0",
                "financial_plan_number_of_contracts": "0",
            })
            rows.append(r)
    return pd.DataFrame(rows)


def test_assign_release_types_positional_per_year():
    df = pd.DataFrame({
        "fiscal_year": ["2027", "2027", "2027", "2026"],
        "publication_date": [DATES["adopt"], DATES["prelim"], DATES["exec"], DATES["prelim"]],
    })
    out = apiv8._assign_release_types(df, [2027, 2026])
    # Same publication date in two fiscal years: each keyed independently.
    assert out["release_type"].tolist() == ["adopt", "prelim", "exec", "prelim"]


def test_clean_fills_blank_instead_of_nan():
    df = _raw_rows()
    df.loc[0, "budget_code_name"] = np.nan
    df = apiv8._assign_release_types(apiv8._apply_categorical_dtypes(df), [FY])
    out = apiv8.clean(df)
    values = set(out["budget_code_name"])
    assert apiv8.BLANK_LABEL in values
    assert "NAN" not in values and "nan" not in values


def test_collapse_and_differences():
    df = apiv8._assign_release_types(apiv8._apply_categorical_dtypes(_raw_rows()), [FY])
    clean = apiv8.clean(df)
    collapsed, numeric_cols = apiv8.collapse(clean)

    assert len(collapsed) == 2
    for release in ("prelim", "exec"):
        assert f"FY{FY}_{release}_financial_plan_amount" in numeric_cols
    # adopt financial plan duplicates the adopted baseline only when names collide; here baseline
    # is FY2026 so the FY2027 adopt plan column must survive.
    assert f"FY{FY}_adopt_financial_plan_amount" in numeric_cols
    assert f"FY{FY - 1}_adopted_budget_amount" in numeric_cols

    diff = apiv8.calculate_differences(collapsed, FY).set_index("object_code")
    assert diff.loc["100", f"FY{FY}_exec_vs_prelim_amount_change"] == -20
    assert diff.loc["100", f"FY{FY}_exec_vs_prelim_amount_pct_change"] == pytest.approx(-0.2)
    # Division by a zero base yields NaN, not inf.
    assert np.isnan(diff.loc["200", f"FY{FY}_exec_vs_prelim_amount_pct_change"])
    assert diff.loc["100", f"FY{FY}_adopt_vs_FY{FY - 1}_adopted_amount_change"] == 30
    # Positions get $ change but no % change.
    assert f"FY{FY}_exec_vs_prelim_position_change" in diff.columns
    assert f"FY{FY}_exec_vs_prelim_position_pct_change" not in diff.columns


def test_safe_pct_change():
    out = apiv8.safe_pct_change(pd.Series([10.0, 5.0, 0.0]), pd.Series([100.0, 0.0, 0.0]))
    assert out.iloc[0] == pytest.approx(0.1)
    assert np.isnan(out.iloc[1]) and np.isnan(out.iloc[2])


def test_agg_levels_are_code_name_prefixes():
    sizes = [len(cols) for cols in apiv8.AGG_LEVELS.values()]
    assert sizes == [2, 4, 6, 8, 10, 12]
