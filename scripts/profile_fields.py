"""Profile every field of the raw datasets and run leakage checks (STUDENT_START task 3).

Outputs, per dataset:
  data/<ds>/field_profile.csv   one row per (file, column): fill %, distinct count, top values, examples
  data/<ds>/leakage_checks.json checks of fields that may reveal the hidden labels

Subsets profiled (the ones we will use):
  VAERS  primary reports only (ORDER = 1), 2019 and 2021-2023            (STATE.md V1)
  ASRS   all six yearly exports, 2018-2023
  MAUDE  reports with a candidate product code, received 2018-2025      (STATE.md M2)

Usage: python scripts/profile_fields.py [vaers|asrs|maude ...]
"""

import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path("data")
DISTINCT_CAP = 100_000  # stop counting distinct values above this
TOP_CAP = 30  # keep a value histogram only for columns with at most this many distinct values
MAUDE_CODES = ["FRN", "LZG", "QFG", "OYC", "OZP", "OZO", "MDS", "PQF", "QBJ", "QLG", "LWS", "NIK"]
MAUDE_YEARS = range(2018, 2026)
CHUNK = 500_000


class ColumnProfile:
    def __init__(self):
        self.rows = 0
        self.filled = 0
        self.hashes: set | None = set()
        self.top: Counter | None = Counter()
        self.examples: list[str] = []

    def update(self, s: pd.Series) -> None:
        s = s.fillna("").astype(str).str.strip()
        nonempty = s[s != ""]
        self.rows += len(s)
        self.filled += len(nonempty)
        if not len(nonempty):
            return
        uniq = pd.Series(nonempty.unique())
        if self.hashes is not None:
            self.hashes.update(pd.util.hash_pandas_object(uniq, index=False).tolist())
            if len(self.hashes) > DISTINCT_CAP:
                self.hashes = None
        if self.top is not None:
            self.top.update(nonempty.value_counts().to_dict())
            if len(self.top) > TOP_CAP:
                self.top = None
        for v in uniq[: 3 - len(self.examples)]:
            self.examples.append(v[:80])

    def row(self) -> dict:
        return {
            "rows": self.rows,
            "filled": self.filled,
            "fill_pct": round(100 * self.filled / self.rows, 1) if self.rows else 0.0,
            "distinct": len(self.hashes) if self.hashes is not None else f">{DISTINCT_CAP}",
            "top_values": "; ".join(f"{k}:{v}" for k, v in self.top.most_common(TOP_CAP)) if self.top else "",
            "examples": " | ".join(self.examples),
        }


class FileProfile:
    def __init__(self):
        self.cols: dict[str, ColumnProfile] = {}

    def update(self, df: pd.DataFrame) -> None:
        for c in df.columns:
            self.cols.setdefault(c, ColumnProfile()).update(df[c])

    def rows(self, dataset: str, file: str) -> list[dict]:
        return [{"dataset": dataset, "file": file, "column": c, **p.row()} for c, p in self.cols.items()]


def write(ds: str, profiles: dict[str, FileProfile], checks: dict) -> None:
    rows = [r for f, p in profiles.items() for r in p.rows(ds, f)]
    pd.DataFrame(rows).to_csv(DATA / ds / "field_profile.csv", index=False)
    (DATA / ds / "leakage_checks.json").write_text(json.dumps(checks, indent=2, default=str))
    print(f"[{ds}] {len(rows)} columns profiled -> data/{ds}/field_profile.csv, leakage_checks.json", flush=True)


def rate(mask_a: pd.Series, mask_b: pd.Series) -> dict:
    """P(b | a) with counts."""
    n = int(mask_a.sum())
    return {"n": n, "p": round(float((mask_a & mask_b).sum() / n), 4) if n else None}


# ---------------------------------------------------------------- VAERS
def vaers() -> None:
    prof = {k: FileProfile() for k in ("VAERSDATA", "VAERSSYMPTOMS", "VAERSVAX")}
    data_all = []
    for y in (2019, 2021, 2022, 2023):
        with zipfile.ZipFile(DATA / "vaers/raw" / f"{y}VAERSData.zip") as z:
            for kind in prof:
                df = pd.read_csv(z.open(f"{y}{kind}.csv"), dtype=str, encoding="latin-1", keep_default_na=False)
                df = df[df["ORDER"] == "1"]
                prof[kind].update(df)
                if kind == "VAERSDATA":
                    data_all.append(df)
    d = pd.concat(data_all)
    Y = lambda c: d[c].eq("Y")  # noqa: E731
    F = lambda c: d[c].str.strip().ne("")  # noqa: E731
    checks = {
        "P(DIED=Y | DATEDIED filled)": rate(F("DATEDIED"), Y("DIED")),
        "P(DIED=Y | DATEDIED empty)": rate(~F("DATEDIED"), Y("DIED")),
        "P(HOSPITAL=Y | HOSPDAYS filled)": rate(F("HOSPDAYS"), Y("HOSPITAL")),
        "P(HOSPITAL=Y | HOSPDAYS empty)": rate(~F("HOSPDAYS"), Y("HOSPITAL")),
        "P(HOSPITAL=Y | X_STAY=Y)": rate(Y("X_STAY"), Y("HOSPITAL")),
        "P(DIED=Y | L_THREAT=Y)": rate(Y("L_THREAT"), Y("DIED")),
        "P(HOSPITAL=Y | L_THREAT=Y)": rate(Y("L_THREAT"), Y("HOSPITAL")),
        "P(HOSPITAL=Y | all)": rate(pd.Series(True, index=d.index), Y("HOSPITAL")),
        "P(DIED=Y | all)": rate(pd.Series(True, index=d.index), Y("DIED")),
        "text mentions death: P(DIED=Y | SYMPTOM_TEXT matches died|death|deceased|passed away)": rate(
            d["SYMPTOM_TEXT"].str.contains(r"\b(?:died|death|deceased|passed away)\b", case=False, regex=True), Y("DIED")
        ),
        "text mentions hospital: P(HOSPITAL=Y | SYMPTOM_TEXT matches hospitali[sz]ed|admitted)": rate(
            d["SYMPTOM_TEXT"].str.contains(r"\bhospitali[sz]ed\b|\badmitted\b", case=False, regex=True), Y("HOSPITAL")
        ),
    }
    write("vaers", prof, checks)


# ---------------------------------------------------------------- ASRS
def asrs() -> None:
    prof = {"ASRS_YYYY.csv": FileProfile()}
    parts = []
    for y in range(2018, 2024):
        df = pd.read_csv(DATA / "asrs/raw" / f"ASRS_{y}.csv", header=[0, 1], dtype=str, encoding="latin-1",
                         keep_default_na=False)
        df.columns = ["|".join(p for p in cols if p.strip() and not p.startswith("Unnamed")) for cols in df.columns]
        df = df.loc[:, df.columns != ""]
        prof["ASRS_YYYY.csv"].update(df)
        parts.append(df)
    d = pd.concat(parts).drop_duplicates("ACN")
    checks = {}
    # Does the analyst-written Synopsis name the coded anomaly more often than the reporter's narrative does?
    probes = {
        "Ground Incursion Runway": r"incursion",
        "Conflict NMAC": r"\bNMAC\b|near mid ?air",
        "Deviation - Altitude": r"altitude",
        "Inflight Event / Encounter Bird / Animal": r"\bbird|\banimal|wildlife",
        "Aircraft Equipment Problem Critical": r"critical|malfunction|fail",
    }
    narr = d["Report 1|Narrative"] + " " + d["Report 2|Narrative"]
    for anomaly, pat in probes.items():
        has = d["Events|Anomaly"].str.contains(anomaly, regex=False)
        syn = d["Report 1|Synopsis"].str.contains(pat, case=False, regex=True)
        nar = narr.str.contains(pat, case=False, regex=True)
        checks[f"anomaly '{anomaly}' (n={int(has.sum())}), pattern /{pat}/"] = {
            "P(pattern in Synopsis | anomaly)": round(float(syn[has].mean()), 3) if has.any() else None,
            "P(pattern in Narrative | anomaly)": round(float(nar[has].mean()), 3) if has.any() else None,
            "P(anomaly | pattern in Synopsis)": round(float(has[syn].mean()), 3) if syn.any() else None,
            "P(anomaly | pattern in Narrative)": round(float(has[nar].mean()), 3) if nar.any() else None,
        }
    checks["reports with a second narrative"] = int((d["Report 2|Narrative"] != "").sum())
    checks["unique ACNs"] = len(d)
    write("asrs", prof, checks)


# ---------------------------------------------------------------- MAUDE
def maude_reader(zip_name: str, names: list[str] | None = None, usecols=None):
    z = zipfile.ZipFile(DATA / "maude/raw" / zip_name)
    member = z.namelist()[0]
    return pd.read_csv(
        z.open(member), sep="|", dtype=str, encoding="latin-1", keep_default_na=False, quoting=3,
        on_bad_lines="skip", chunksize=CHUNK, names=names, header=None if names else "infer", usecols=usecols,
        engine="c",
    )


def keys_of(df: pd.DataFrame) -> np.ndarray:
    return pd.to_numeric(df["MDR_REPORT_KEY"], errors="coerce").to_numpy()


def maude() -> None:
    prof = {k: FileProfile() for k in ("deviceYYYY", "mdrfoiThru2025", "foitextYYYY", "foidevproblem_thru2025",
                                       "patientproblemcode_thru2025", "patientthru2025")}
    checks: dict = {"product_codes": MAUDE_CODES, "years_received": f"{MAUDE_YEARS.start}-{MAUDE_YEARS.stop - 1}"}

    # 1. device files -> candidate report keys
    keys = []
    for y in MAUDE_YEARS:
        for ch in maude_reader(f"device{y}.zip"):
            ch = ch[ch["DEVICE_REPORT_PRODUCT_CODE"].isin(MAUDE_CODES)]
            prof["deviceYYYY"].update(ch)
            keys.append(keys_of(ch))
        print(f"  device{y} done", flush=True)
    keys = np.unique(np.concatenate(keys))
    keys = keys[~np.isnan(keys)]
    checks["candidate_reports"] = int(len(keys))

    def filtered(zip_name, names=None):
        for ch in maude_reader(zip_name, names):
            yield ch[np.isin(keys_of(ch), keys)]

    # 2. master records; leakage: flags vs EVENT_TYPE
    ct = Counter()
    for ch in filtered("mdrfoiThru2025.zip"):
        prof["mdrfoiThru2025"].update(ch)
        ct.update(zip(ch["EVENT_TYPE"], ch["ADVERSE_EVENT_FLAG"], ch["PRODUCT_PROBLEM_FLAG"]))
    print("  master done", flush=True)
    checks["EVENT_TYPE x ADVERSE_EVENT_FLAG x PRODUCT_PROBLEM_FLAG"] = {"|".join(k): v for k, v in ct.most_common(25)}

    # 3. narrative text; leakage: embedded coded fields
    pat = re.compile(r"Device Problem Code|Health Effect|Patient Problem Code|Type of Reportable Event|IMDRF",
                     re.IGNORECASE)
    leak_reports, text_reports, by_type = set(), set(), Counter()
    for y in MAUDE_YEARS:
        for ch in filtered(f"foitext{y}.zip"):
            prof["foitextYYYY"].update(ch.drop(columns=["FOI_TEXT"]))
            prof["foitextYYYY"].update(ch[["FOI_TEXT"]].assign(FOI_TEXT=ch["FOI_TEXT"].str.len().astype(str)).rename(
                columns={"FOI_TEXT": "FOI_TEXT_length"}))
            hit = ch["FOI_TEXT"].str.contains(pat)
            by_type.update(ch.loc[hit, "TEXT_TYPE_CODE"].tolist())
            leak_reports.update(ch.loc[hit, "MDR_REPORT_KEY"].tolist())
            text_reports.update(ch["MDR_REPORT_KEY"].tolist())
        print(f"  foitext{y} done", flush=True)
    checks["reports_with_text"] = len(text_reports)
    checks["reports_whose_text_embeds_coded_fields"] = len(leak_reports)
    checks["embedded_code_text_rows_by_TEXT_TYPE_CODE"] = dict(by_type)

    # 4. problem codes and patients
    for ch in filtered("foidevproblem_thru2025.zip", names=["MDR_REPORT_KEY", "DEVICE_PROBLEM_CODE"]):
        prof["foidevproblem_thru2025"].update(ch)
    for ch in filtered("patientproblemcode_thru2025.zip"):
        prof["patientproblemcode_thru2025"].update(ch)
    for ch in filtered("patientthru2025.zip"):
        prof["patientthru2025"].update(ch)
    print("  problem codes and patients done", flush=True)
    write("maude", prof, checks)


if __name__ == "__main__":
    targets = sys.argv[1:] or ["vaers", "asrs", "maude"]
    for t in targets:
        {"vaers": vaers, "asrs": asrs, "maude": maude}[t]()
