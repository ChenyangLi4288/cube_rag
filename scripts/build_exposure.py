"""Build the monthly exposure series (STUDENT_START task 5, issue #4).

Reads the frozen downloads in data/vaers/exposure/raw/ (CDC; scripts/download_exposure.py) and
data/asrs/exposure/raw/ (FAA OPSNET, BTS T-100; browser downloads) and writes

  exposure/vaers.csv, exposure/asrs.csv   columns: period (YYYY-MM), series, value, source
  exposure/coverage.csv                   per series: first/last month, months present, gaps
  exposure/BUILD.json                     git commit, input sha256, rules

Rules (exposure/README.md):
- A row is a complete calendar month. Months a source does not cover are absent (never 0).
- Daily sources are summed by month. Weekly sources are spread evenly over the 7 days of each
  week, then summed by month. Cumulative sources are differenced first.
- The first month of each reporting period is complete: doses before the first reported week are
  either in the first cumulative value (IQVIA flu) or zero because the vaccine was not yet
  available (COVID-19 Dec 2020, Sep 2023). The last month is kept only if fully covered.

Usage:
  python scripts/build_exposure.py
"""

import hashlib
import json
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "exposure"
VAERS_RAW = ROOT / "data" / "vaers" / "exposure" / "raw"
ASRS_RAW = ROOT / "data" / "asrs" / "exposure" / "raw"

VAERS_WINDOW = ("2019-01", "2023-12")  # VAERS data: 2019, 2021-2023
ASRS_WINDOW = ("2018-01", "2023-12")
COLUMNS = ["period", "series", "value", "source"]


# ---------------------------------------------------------------- helpers

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cdc_file(ds_id: str) -> Path:
    (path,) = VAERS_RAW.glob(f"*__{ds_id}.csv")
    return path


def months_fully_covered(start: pd.Timestamp, end: pd.Timestamp, first_month_complete: bool) -> pd.PeriodIndex:
    """Months whose every day lies in [start, end]; the start month counts if first_month_complete."""
    first = start.to_period("M") if first_month_complete or start.day == 1 else start.to_period("M") + 1
    last = end.to_period("M") if end == end.to_period("M").end_time.normalize() else end.to_period("M") - 1
    return pd.period_range(first, last, freq="M") if first <= last else pd.PeriodIndex([], freq="M")


def intervals_to_monthly(start: pd.Series, end: pd.Series, increment: pd.Series) -> pd.Series:
    """Spread each increment evenly over the days start..end (inclusive); sum by month."""
    n_days = ((end.values - start.values) / pd.Timedelta(days=1)).astype(int) + 1
    assert (n_days >= 1).all()
    days = pd.DataFrame({"start": start.values, "inc": increment.values / n_days})
    days = days.loc[days.index.repeat(n_days)].copy()
    days["day"] = days["start"] + pd.to_timedelta(days.groupby(level=0).cumcount(), unit="D")
    return days.groupby(days["day"].dt.to_period("M"))["inc"].sum()


def season_cumulative_to_monthly(df: pd.DataFrame, season_col: str, week_end_col: str, cum_col: str,
                                 scale: float = 1.0, start_col: str | None = None) -> pd.Series:
    """Weekly cumulative-by-season series -> monthly totals over the fully covered months.

    Each increment covers the days after the previous period's end up to this period's end; the
    first period starts at start_col if given, else 6 days before its end (a 7-day week). Rows
    whose end does not move forward (overlapping re-statements) are dropped.
    """
    parts = []
    for _, g in df.groupby(season_col):
        g = g.sort_values([week_end_col, cum_col])
        g = g[~g[week_end_col].duplicated(keep="last")]
        inc = g[cum_col].diff().fillna(g[cum_col]) * scale  # first increment = first cumulative value
        assert (inc >= 0).all(), "cumulative series decreases"
        first_start = (g[start_col].iloc[0] if start_col else g[week_end_col].iloc[0] - pd.Timedelta(days=6))
        start = (g[week_end_col].shift() + pd.Timedelta(days=1)).fillna(first_start)
        monthly = intervals_to_monthly(start, g[week_end_col], inc)
        keep = months_fully_covered(first_start, g[week_end_col].iloc[-1], first_month_complete=True)
        parts.append(monthly.reindex(keep))
    out = pd.concat(parts)
    return out.groupby(level=0).sum()  # a month in two seasons (not in our windows) is summed


def rows(monthly: pd.Series, series: str, source: str, window: tuple[str, str]) -> pd.DataFrame:
    lo, hi = pd.Period(window[0], "M"), pd.Period(window[1], "M")
    m = monthly[(monthly.index >= lo) & (monthly.index <= hi)].dropna()
    return pd.DataFrame({"period": m.index.astype(str), "series": series,
                         "value": m.round().astype("int64").values, "source": source})


# ---------------------------------------------------------------- VAERS (CDC doses)

def vaers_series() -> pd.DataFrame:
    out = []

    # COVID-19, all ages, national, by administration date (daily) - main COVID series.
    t = pd.read_csv(cdc_file("rh2h-3yt2"), usecols=["Date", "date_type", "Location", "Administered_Daily"])
    us = t[(t.Location == "US") & (t.date_type == "Admin")].copy()
    us["Date"] = pd.to_datetime(us["Date"], format="mixed")
    us = us.sort_values("Date")
    assert not us["Date"].duplicated().any() and (us["Date"].diff().dt.days.dropna() == 1).all(), "rh2h: daily gaps"
    monthly = us.groupby(us["Date"].dt.to_period("M"))["Administered_Daily"].sum()
    keep = months_fully_covered(us["Date"].iloc[0], us["Date"].iloc[-1], first_month_complete=True)
    out.append(rows(monthly.reindex(keep), "covid19_doses", "data.cdc.gov/d/rh2h-3yt2", VAERS_WINDOW))

    # COVID-19 by age band, national, by report date (cumulative, differenced at month ends).
    j = pd.read_csv(cdc_file("unsk-b7fc"), low_memory=False,
                    usecols=["Date", "Location", "Administered_5Plus", "Administered_12Plus",
                             "Administered_18Plus", "Administered_65Plus"])
    j = j[j.Location == "US"].copy()
    j["Date"] = pd.to_datetime(j["Date"], format="mixed")
    j = j.sort_values("Date").set_index("Date")
    bands = {
        "covid19_doses_age_65plus": j["Administered_65Plus"],
        "covid19_doses_age_18_64": j["Administered_18Plus"] - j["Administered_65Plus"],
        "covid19_doses_age_12_17": j["Administered_12Plus"] - j["Administered_18Plus"],
        "covid19_doses_age_5_11": j["Administered_5Plus"] - j["Administered_12Plus"],
    }
    first_report = {  # a band exists once every column it uses is reported (> 0)
        "covid19_doses_age_65plus": ["Administered_65Plus"],
        "covid19_doses_age_18_64": ["Administered_18Plus", "Administered_65Plus"],
        "covid19_doses_age_12_17": ["Administered_12Plus", "Administered_18Plus"],
        "covid19_doses_age_5_11": ["Administered_5Plus", "Administered_12Plus"],
    }
    last_full = months_fully_covered(j.index[0], j.index[-1], first_month_complete=True)[-1]
    for name, cum in bands.items():
        start = max(j.index[(j[c] > 0)].min() for c in first_report[name])
        month_end = cum.groupby(cum.index.to_period("M")).last()  # last report on or before month end
        monthly = month_end.diff()
        first_valid = start.to_period("M") + 1  # needs a month-end value before it
        monthly = monthly[(monthly.index >= first_valid) & (monthly.index <= last_full)]
        out.append(rows(monthly, name, "data.cdc.gov/d/unsk-b7fc", VAERS_WINDOW))

    # COVID-19, adults, retail pharmacies + physician offices (IQVIA), from the 2023-24 season.
    e = pd.read_csv(cdc_file("ewpg-rz7g"))
    e["Age_Group"] = e["Age_Group"].str.strip()
    e = e[(e.Setting == "Combined") & (e.Age_Group == "18+")].copy()
    e["week_end"] = pd.to_datetime(e["Week_ID"], format="mixed")
    monthly = season_cumulative_to_monthly(e, "COVID-19_Season", "week_end", "Cumulative_Doses")
    out.append(rows(monthly, "covid19_doses_iqvia_adults", "data.cdc.gov/d/ewpg-rz7g", VAERS_WINDOW))

    # Influenza, adults, retail pharmacies + physician offices (IQVIA), by age group.
    # ysd3-txwj is the current release (May 2026); 83ng-twza is an older release of the same
    # estimates (2-3% lower per season) and is kept in raw/ only for the record.
    a = pd.read_csv(cdc_file("ysd3-txwj"))
    a["Age_Group"] = a["Age_Group"].str.strip()
    a = a[a.Setting == "Combined"].copy()
    a["week_end"] = pd.to_datetime(a["Week_ID"], format="mixed")
    for group, name in [("18+", "flu_doses_iqvia_adults"), ("18-49", "flu_doses_iqvia_age_18_49"),
                        ("50-64", "flu_doses_iqvia_age_50_64"), ("65+", "flu_doses_iqvia_age_65plus")]:
        monthly = season_cumulative_to_monthly(a[a.Age_Group == group], "Influenza_Season", "week_end",
                                               "Cumulative_Doses")
        out.append(rows(monthly, name, "data.cdc.gov/d/ysd3-txwj", VAERS_WINDOW))

    # Influenza doses distributed (supply, all settings), weekly cumulative by season, in millions.
    d = pd.read_csv(cdc_file("ph8r-wzxn"))
    d["week_end"] = pd.to_datetime(d["End_Date"], format="mixed")
    d["week_start"] = pd.to_datetime(d["Start_Date"], format="mixed")  # irregular around New Year
    monthly = season_cumulative_to_monthly(d, "Influenza_Season", "week_end", "Cumulative_Flu_Doses_Distributed",
                                           scale=1e6, start_col="week_start")
    out.append(rows(monthly, "flu_doses_distributed", "data.cdc.gov/d/ph8r-wzxn", VAERS_WINDOW))

    return pd.concat(out, ignore_index=True)


# ---------------------------------------------------------------- ASRS (FAA / BTS operations)

OPSNET_FILE = "faa_opsnet_airport_operations_monthly_2018-2023.xls"
OPSNET_SERIES = {  # (group, column) in the OPSNET table -> series
    ("", "Total Operations"): "opsnet_total",
    ("Itinerant", "Total"): "opsnet_itinerant",
    ("Itinerant", "Air Carrier"): "opsnet_itinerant_air_carrier",
    ("Itinerant", "Air Taxi"): "opsnet_itinerant_air_taxi",
    ("Itinerant", "General Aviation"): "opsnet_itinerant_general_aviation",
    ("Itinerant", "Military"): "opsnet_itinerant_military",
    ("Local", "Civil"): "opsnet_local_civil",
    ("Local", "Military"): "opsnet_local_military",
}


def read_opsnet() -> pd.DataFrame:
    """OPSNET Airport Operations standard report (HTML table saved as .xls) -> one row per month."""
    (t,) = pd.read_html(ASRS_RAW / OPSNET_FILE)
    t.columns = [(("" if str(g).startswith("Unnamed") else g), ("" if str(c).startswith("Unnamed") else c))
                 for _, g, c in t.columns]
    t = t[[c for c in t.columns if c != ("", "")]]
    t = t.rename(columns={("", "Date"): "date"})
    total = t[t["date"] == "Total:"]
    t = t[t["date"] != "Total:"].copy()
    t["period"] = pd.PeriodIndex(pd.to_datetime(t["date"], format="%m/%Y"), freq="M")
    vals = t.drop(columns=["date"]).set_index("period").astype("int64")
    # internal consistency of the FAA table
    it = vals[("Itinerant", "Total")]
    assert (it == vals[[("Itinerant", c) for c in ["Air Carrier", "Air Taxi", "General Aviation", "Military"]]].sum(axis=1)).all()
    assert (vals[("Local", "Total")] == vals[("Local", "Civil")] + vals[("Local", "Military")]).all()
    assert (vals[("", "Total Operations")] == it + vals[("Local", "Total")]).all()
    assert (vals.sum() == total.drop(columns=["date"]).astype("int64").iloc[0]).all(), "months do not add up to Total row"
    assert len(vals) == 72 and vals.index.is_unique
    return vals


def read_t100() -> pd.DataFrame:
    cols = ["YEAR", "MONTH", "DEPARTURES_PERFORMED", "ORIGIN_COUNTRY", "DEST_COUNTRY", "DATA_SOURCE"]
    parts = []
    for path in sorted(ASRS_RAW.glob("bts_t100_segment_all_carriers_*.zip")):
        with zipfile.ZipFile(path) as z:
            df = pd.read_csv(z.open("T_T100_SEGMENT_ALL_CARRIER.csv"), usecols=cols,
                             dtype={"ORIGIN_COUNTRY": str, "DEST_COUNTRY": str, "DATA_SOURCE": str})
        assert df["YEAR"].nunique() == 1 and str(df["YEAR"].iloc[0]) in path.stem, path.name
        assert df["MONTH"].nunique() == 12, path.name
        parts.append(df)
    df = pd.concat(parts, ignore_index=True)
    df["period"] = pd.PeriodIndex.from_fields(year=df["YEAR"], month=df["MONTH"], freq="M")
    return df


def asrs_series() -> pd.DataFrame | None:
    if not (ASRS_RAW / OPSNET_FILE).exists():
        return None
    out = []
    ops = read_opsnet()
    for col, name in OPSNET_SERIES.items():
        out.append(rows(ops[col], name, "FAA OPSNET Airport Operations (aspm.faa.gov/opsnet)", ASRS_WINDOW))

    t = read_t100()
    assert set(t["DATA_SOURCE"]) <= {"DU", "IU", "DF", "IF"}, set(t["DATA_SOURCE"])
    everything = pd.Series(True, index=t.index)
    domestic = (t["ORIGIN_COUNTRY"] == "US") & (t["DEST_COUNTRY"] == "US")
    us_carrier = t["DATA_SOURCE"].str.endswith("U")  # DU / IU = U.S. carriers; DF / IF = foreign carriers
    src = "BTS T-100 Segment (All Carriers), transtats.bts.gov"
    for name, mask in [("t100_departures", everything), ("t100_departures_domestic", domestic),
                       ("t100_departures_us_carriers", us_carrier)]:
        monthly = t.loc[mask].groupby("period")["DEPARTURES_PERFORMED"].sum()
        assert len(monthly) == 72
        out.append(rows(monthly, name, src, ASRS_WINDOW))
    return pd.concat(out, ignore_index=True)


# ---------------------------------------------------------------- output

def coverage(df: pd.DataFrame, dataset: str, window: tuple[str, str]) -> pd.DataFrame:
    recs = []
    for series, g in df.groupby("series"):
        p = pd.PeriodIndex(g["period"], freq="M").sort_values()
        full = pd.period_range(p[0], p[-1], freq="M")
        gaps = sorted(set(full) - set(p))
        recs.append({"dataset": dataset, "series": series, "first": str(p[0]), "last": str(p[-1]),
                     "months": len(p), "months_in_window": len(pd.period_range(*window, freq="M")),
                     "gaps_inside": ";".join(str(x) for x in gaps), "source": g["source"].iloc[0]})
    return pd.DataFrame(recs)


def check(df: pd.DataFrame) -> None:
    assert list(df.columns) == COLUMNS
    assert not df.duplicated(["period", "series"]).any(), "duplicate (period, series)"
    assert df["period"].str.fullmatch(r"\d{4}-\d{2}").all()
    assert (df["value"] >= 0).all(), df[df["value"] < 0]


def main() -> None:
    OUT.mkdir(exist_ok=True)
    built, cov, inputs = [], [], {}
    for dataset, fn, window, raw in [("vaers", vaers_series, VAERS_WINDOW, VAERS_RAW),
                                     ("asrs", asrs_series, ASRS_WINDOW, ASRS_RAW)]:
        df = fn()
        if df is None:
            print(f"{dataset}: no input yet, skipped")
            continue
        df = df.sort_values(["series", "period"]).reset_index(drop=True)
        check(df)
        df.to_csv(OUT / f"{dataset}.csv", index=False)
        cov.append(coverage(df, dataset, window))
        built.append(dataset)
        inputs.update({f"{p.parent.parent.parent.name}/{p.name}": sha256(p) for p in sorted(raw.glob("*")) if p.is_file()})
        print(f"{dataset}: {len(df):,} rows, {df['series'].nunique()} series -> exposure/{dataset}.csv")
    pd.concat(cov).to_csv(OUT / "coverage.csv", index=False)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "scripts/build_exposure.py"], capture_output=True, text=True,
                           cwd=ROOT).stdout.strip()
    (OUT / "BUILD.json").write_text(json.dumps({
        "built_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": commit + ("+uncommitted-script" if dirty else ""),
        "datasets": built,
        "windows": {"vaers": VAERS_WINDOW, "asrs": ASRS_WINDOW},
        "inputs_sha256": inputs,
    }, indent=2))
    print(pd.concat(cov).to_string(index=False))


if __name__ == "__main__":
    main()
