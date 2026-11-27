"""Tests for the exposure series (scripts/build_exposure.py, exposure/*.csv; issue #4).

The committed CSVs are checked always. The rebuild check needs the raw downloads under
data/<ds>/exposure/raw/ and is skipped without them.
"""
import importlib.util
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("build_exposure", ROOT / "scripts" / "build_exposure.py")
be = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(be)

DATASETS = {"vaers": be.VAERS_WINDOW, "asrs": be.ASRS_WINDOW}


# ---------------------------------------------------------------- committed files

@pytest.fixture(scope="module", params=sorted(DATASETS))
def committed(request):
    return request.param, pd.read_csv(ROOT / "exposure" / f"{request.param}.csv", dtype={"period": str})


def test_columns_and_keys(committed):
    name, df = committed
    assert list(df.columns) == ["period", "series", "value", "source"]
    assert df["period"].str.fullmatch(r"\d{4}-(0[1-9]|1[0-2])").all()
    assert not df.duplicated(["period", "series"]).any()
    assert df["series"].str.fullmatch(r"[a-z0-9_]+").all()
    assert df["source"].notna().all() and (df["source"].str.len() > 0).all()


def test_values_are_counts(committed):
    _, df = committed
    assert pd.api.types.is_integer_dtype(df["value"])
    assert (df["value"] >= 0).all()


def test_periods_inside_window(committed):
    name, df = committed
    lo, hi = DATASETS[name]
    assert (df["period"] >= lo).all() and (df["period"] <= hi).all()


def test_one_source_per_series(committed):
    _, df = committed
    assert (df.groupby("series")["source"].nunique() == 1).all()


def test_coverage_matches(committed):
    name, df = committed
    cov = pd.read_csv(ROOT / "exposure" / "coverage.csv", dtype=str).fillna("")
    cov = cov[cov["dataset"] == name].set_index("series")
    assert set(cov.index) == set(df["series"])
    for series, g in df.groupby("series"):
        assert cov.loc[series, "first"] == g["period"].min()
        assert cov.loc[series, "last"] == g["period"].max()
        assert int(cov.loc[series, "months"]) == len(g)


def test_asrs_series_complete():
    df = pd.read_csv(ROOT / "exposure" / "asrs.csv")
    assert (df.groupby("series").size() == 72).all()  # 2018-01 .. 2023-12, no gaps
    w = df.pivot(index="period", columns="series", values="value")
    parts = ["opsnet_itinerant_air_carrier", "opsnet_itinerant_air_taxi", "opsnet_itinerant_general_aviation",
             "opsnet_itinerant_military"]
    assert (w[parts].sum(axis=1) == w["opsnet_itinerant"]).all()
    assert (w["opsnet_itinerant"] + w["opsnet_local_civil"] + w["opsnet_local_military"] == w["opsnet_total"]).all()
    assert (w["t100_departures_domestic"] <= w["t100_departures"]).all()
    assert (w["t100_departures_us_carriers"] <= w["t100_departures"]).all()


# ---------------------------------------------------------------- helpers

def test_week_split_across_month_end():
    # week 2021-01-28 .. 2021-02-03: 4 days in January, 3 in February
    m = be.intervals_to_monthly(pd.Series(pd.to_datetime(["2021-01-28"])), pd.Series(pd.to_datetime(["2021-02-03"])),
                                pd.Series([70.0]))
    assert m[pd.Period("2021-01", "M")] == pytest.approx(40.0)
    assert m[pd.Period("2021-02", "M")] == pytest.approx(30.0)


def test_months_fully_covered():
    ts = pd.Timestamp
    got = be.months_fully_covered(ts("2020-12-13"), ts("2023-05-09"), first_month_complete=True)
    assert got[0] == pd.Period("2020-12", "M") and got[-1] == pd.Period("2023-04", "M")
    got = be.months_fully_covered(ts("2020-12-13"), ts("2021-03-31"), first_month_complete=False)
    assert list(got.astype(str)) == ["2021-01", "2021-02", "2021-03"]


def test_season_cumulative_first_value_and_restatement():
    df = pd.DataFrame({
        "season": ["s"] * 6,
        "end": pd.to_datetime(["2019-08-10", "2019-08-17", "2019-08-24", "2019-08-24", "2019-08-31", "2019-09-07"]),
        "cum": [10.0, 17.0, 31.0, 31.0, 38.0, 45.0],  # the 4th row re-states the 3rd week
    })
    m = be.season_cumulative_to_monthly(df, "season", "end", "cum")
    # August is kept (first month counts as complete; covered to Aug 31); September ends early -> dropped
    assert list(m.index.astype(str)) == ["2019-08"]
    assert m.iloc[0] == pytest.approx(38.0)  # = cumulative at Aug 31, first value included, nothing double counted


# ---------------------------------------------------------------- reproducibility

@pytest.mark.parametrize("name, fn, raw", [("vaers", be.vaers_series, be.VAERS_RAW), ("asrs", be.asrs_series, be.ASRS_RAW)])
def test_rebuild_matches_committed(name, fn, raw):
    if not raw.exists() or not any(raw.iterdir()):
        pytest.skip(f"no raw exposure downloads in {raw}")
    rebuilt = fn().sort_values(["series", "period"]).reset_index(drop=True)
    committed = pd.read_csv(ROOT / "exposure" / f"{name}.csv", dtype={"period": str})
    pd.testing.assert_frame_equal(rebuilt, committed.sort_values(["series", "period"]).reset_index(drop=True),
                                  check_dtype=False)
