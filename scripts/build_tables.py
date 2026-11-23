"""Build processed tables from the raw downloads (version v1, decisions of 2026-11-20 applied; issue #2).

For each dataset:
  data/<ds>/processed/   what the method may read: key + text + filter fields
  data/<ds>/hidden/      ground truth (core + leak fields) — never give these to the method
  data/<ds>/PROCESSED_MANIFEST.json   rules applied, row counts, git commit, integrity checks

Field roles follow data/README.md. Rules (STATE.md):
  MAUDE  M2  12 product codes, 2018-2025, one fixed sampling rate per product code (same every year), ~1M reports
         M4  EVENT_TYPE, problem codes and leak fields in hidden/
         M5  embedded code blocks stripped from the text; flag has_embedded_codes; build fails if a report's own
             code survives in its text
         M6  summary reports dropped
  VAERS  V1  primary reports only (ORDER = 1); sensitivity labels <flag>_any_order
         V3  leak fields in hidden/
  ASRS   A3  year = incident month; incident months outside 2018-2023 dropped
         A4  Synopsis, Callbacks and analyst-coded fields in hidden/

Usage: python scripts/build_tables.py [vaers|asrs|maude ...]
"""

import json
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
VERSION = "v1"
STR = "string[pyarrow]"


def git_commit() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                             cwd=ROOT).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "scripts/build_tables.py"], capture_output=True,
                               text=True, cwd=ROOT).stdout.strip()
        return sha + ("+uncommitted-script" if dirty else "")
    except OSError:
        return "unknown"


def fresh_dirs(ds: str) -> tuple[Path, Path]:
    out = {}
    for name in ("processed", "hidden"):
        d = DATA / ds / name
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        out[name] = d
    return out["processed"], out["hidden"]


def save(df: pd.DataFrame, path: Path) -> int:
    df.to_parquet(path, index=False, compression="zstd")
    return len(df)


def write_manifest(ds: str, rules: dict, outputs: dict, checks: dict) -> None:
    m = {
        "dataset": ds,
        "version": VERSION,
        "built_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": git_commit(),
        "script": "scripts/build_tables.py",
        "field_roles": "data/README.md",
        "rules": rules,
        "outputs": outputs,
        "checks": checks,
    }
    def plain(o):  # numpy keys/values -> JSON-safe
        if isinstance(o, dict):
            return {str(k): plain(v) for k, v in o.items()}
        if isinstance(o, np.generic):
            return o.item()
        return o

    (DATA / ds / "PROCESSED_MANIFEST.json").write_text(json.dumps(plain(m), indent=2, default=str))
    print(f"[{ds}] done: {outputs}", flush=True)


def yflag(s: pd.Series) -> pd.Series:
    return s.str.strip().str.upper().eq("Y")


def blank_to_na(s: pd.Series) -> pd.Series:
    s = s.astype(STR).str.strip()
    return s.mask(s == "")


# ====================================================================== VAERS
VAERS_YEARS = (2019, 2021, 2022, 2023)
VAERS_FLAGS = ["DIED", "HOSPITAL", "ER_ED_VISIT", "X_STAY", "L_THREAT", "DISABLE", "BIRTH_DEFECT", "OFC_VISIT",
               "ER_VISIT"]


def vaers() -> None:
    proc, hid = fresh_dirs("vaers")
    data, symp, vax, any_order = [], [], [], []
    for y in VAERS_YEARS:
        with zipfile.ZipFile(DATA / "vaers/raw" / f"{y}VAERSData.zip") as z:
            rd = lambda k: pd.read_csv(z.open(f"{y}{k}.csv"), dtype=str, encoding="latin-1",  # noqa: E731
                                       keep_default_na=False)
            d = rd("VAERSDATA")
            # V1 sensitivity check: outcome flags over all rows (primary and secondary) of a VAERS_ID
            any_order.append(d[["VAERS_ID"]].assign(**{c: yflag(d[c]) for c in VAERS_FLAGS}))
            d = d[d["ORDER"] == "1"].assign(source_file=y)
            s, v = rd("VAERSSYMPTOMS"), rd("VAERSVAX")
            data.append(d)
            symp.append(s[s["ORDER"] == "1"])
            vax.append(v[v["ORDER"] == "1"])
    d, s, v = pd.concat(data), pd.concat(symp), pd.concat(vax)
    assert d["VAERS_ID"].is_unique, "VAERS_ID not unique after ORDER=1 filter"
    any_order = pd.concat(any_order).groupby("VAERS_ID")[VAERS_FLAGS].any()

    date = lambda c: pd.to_datetime(d[c], format="%m/%d/%Y", errors="coerce").dt.date  # noqa: E731
    vax_long = pd.DataFrame({
        "VAERS_ID": v["VAERS_ID"].astype(STR),
        "vax_type": blank_to_na(v["VAX_TYPE"]),
        "vax_manu": blank_to_na(v["VAX_MANU"]),
        "vax_dose_series": blank_to_na(v["VAX_DOSE_SERIES"]),
    })
    vax_types = vax_long.dropna(subset=["vax_type"]).groupby("VAERS_ID")["vax_type"].agg(
        lambda x: sorted(set(x)))

    reports = pd.DataFrame({
        "VAERS_ID": d["VAERS_ID"].astype(STR),
        "recv_date": date("RECVDATE"),
        "state": blank_to_na(d["STATE"]),
        "age_yrs": pd.to_numeric(d["AGE_YRS"], errors="coerce"),
        "sex": blank_to_na(d["SEX"]),
        "vax_date": date("VAX_DATE"),
        "onset_date": date("ONSET_DATE"),
        "numdays": pd.to_numeric(d["NUMDAYS"], errors="coerce"),
        "symptom_text": d["SYMPTOM_TEXT"].astype(STR),
        "source_file": d["source_file"].astype("int16"),
    })
    reports["vax_types"] = reports["VAERS_ID"].map(vax_types)

    labels = pd.DataFrame({"VAERS_ID": d["VAERS_ID"].astype(STR)})
    for c in VAERS_FLAGS:
        labels[c.lower()] = yflag(d[c]).to_numpy()
    labels["date_died"] = date("DATEDIED").to_numpy()
    labels["hosp_days"] = pd.to_numeric(d["HOSPDAYS"], errors="coerce").to_numpy()
    labels["recovd"] = blank_to_na(d["RECOVD"]).to_numpy()
    # sensitivity labels (V1): true if any row of this VAERS_ID, in any of the four year files, says so
    ao = any_order.reindex(d["VAERS_ID"]).fillna(False)
    for c in VAERS_FLAGS:
        labels[f"{c.lower()}_any_order"] = ao[c].to_numpy(dtype=bool)

    terms = []
    for i in range(1, 6):
        t = s[["VAERS_ID", f"SYMPTOM{i}", f"SYMPTOMVERSION{i}"]].set_axis(["VAERS_ID", "pt", "meddra_version"], axis=1)
        terms.append(t[t["pt"].str.strip() != ""])
    terms = pd.concat(terms).astype(STR).drop_duplicates()

    outputs = {
        "processed/reports.parquet": save(reports, proc / "reports.parquet"),
        "processed/vaccines.parquet": save(vax_long, proc / "vaccines.parquet"),
        "hidden/labels.parquet": save(labels, hid / "labels.parquet"),
        "hidden/symptoms.parquet": save(terms, hid / "symptoms.parquet"),
    }
    checks = {
        "reports_by_source_file": reports["source_file"].value_counts().sort_index().to_dict(),
        "reports_without_vaccine_rows": int(reports["vax_types"].isna().sum()),
        "reports_without_symptom_terms": int((~reports["VAERS_ID"].isin(terms["VAERS_ID"])).sum()),
        "recv_date_unparsed": int(reports["recv_date"].isna().sum()),
        "distinct_pt": int(terms["pt"].nunique()),
        "flag_true_primary_vs_any_order": {c.lower(): {"primary": int(labels[c.lower()].sum()),
                                                       "any_order": int(labels[f"{c.lower()}_any_order"].sum())}
                                           for c in VAERS_FLAGS},
    }
    write_manifest("vaers", {"V1": "primary reports only (ORDER = 1); text, filters and labels from that row; "
                                   "sensitivity labels <flag>_any_order = true if any row of the VAERS_ID says so",
                             "V2": "domestic yearly files only",
                             "V3": "leak fields (DATEDIED, HOSPDAYS, other outcome flags, RECOVD) in hidden/"},
                   outputs, checks)


# ====================================================================== ASRS
ASRS_FILTERS = {
    "Time|Local Time Of Day": "time_of_day",
    "Place|State Reference": "state",
    "Aircraft 1|Make Model Name": "aircraft_model",
    "Aircraft 1|Flight Phase": "flight_phase",
    "Aircraft 1|Aircraft Operator": "aircraft_operator",
    "Aircraft 1|Operating Under FAR Part": "far_part",
    "Aircraft 1|Flight Plan": "flight_plan",
    "Aircraft 1|Mission": "mission",
    "Environment|Flight Conditions": "flight_conditions",
    "Environment|Light": "light",
    "Person 1|Reporter Organization": "reporter_organization",
    "Person 1|Function": "reporter_function",
}
ASRS_HIDDEN = {
    "Events|Anomaly": "anomaly",
    "Assessments|Primary Problem": "primary_problem",
    "Report 1|Synopsis": "synopsis",
    "Report 1|Callback": "callback_1",
    "Report 2|Callback": "callback_2",
    "Events|Result": "result",
    "Events|Detector": "detector",
    "Events|When Detected": "when_detected",
    "Events|Miss Distance": "miss_distance",
    "Events|Were Passengers Involved In Event": "passengers_involved",
    "Assessments|Contributing Factors / Situations": "contributing_factors",
    "Person 1|Human Factors": "human_factors_1",
    "Person 2|Human Factors": "human_factors_2",
    "Person 1|Communication Breakdown": "communication_breakdown_1",
    "Person 2|Communication Breakdown": "communication_breakdown_2",
    "Component|Aircraft Component": "component",
    "Component|Problem": "component_problem",
}
ASRS_YEARS = range(2018, 2024)
ASRS_MULTI = {"flight_phase", "anomaly", "result", "detector", "contributing_factors", "human_factors_1",
              "human_factors_2"}


def split_multi(s: pd.Series) -> pd.Series:
    return s.map(lambda x: [p.strip() for p in x.split(";") if p.strip()] if isinstance(x, str) and x.strip() else None)


def asrs() -> None:
    proc, hid = fresh_dirs("asrs")
    parts = []
    for y in ASRS_YEARS:
        df = pd.read_csv(DATA / "asrs/raw" / f"ASRS_{y}.csv", header=[0, 1], dtype=str, encoding="latin-1",
                         keep_default_na=False)
        df.columns = ["|".join(p for p in c if p.strip() and not p.startswith("Unnamed")) for c in df.columns]
        parts.append(df.loc[:, df.columns != ""].assign(query_year=y))
    d = pd.concat(parts)
    assert d["ACN"].is_unique, "duplicate ACN across files"

    # A3: report year = incident month; drop reports whose incident month is outside 2018-2023 (2 ACNs: 2002, 2012)
    month = pd.to_datetime(d["Time|Date"], format="%Y%m", errors="coerce")
    in_range = month.dt.year.between(ASRS_YEARS[0], ASRS_YEARS[-1])
    dropped = d.loc[~in_range, ["ACN", "Time|Date"]].astype(str).values.tolist()
    d, month = d[in_range], month[in_range]
    reports = pd.DataFrame({
        "ACN": d["ACN"].astype(STR),
        "month": month.dt.date,
        "year": month.dt.year.astype("Int16"),
        "narrative_1": d["Report 1|Narrative"].astype(STR),
        "narrative_2": blank_to_na(d["Report 2|Narrative"]),
    })
    for src, name in ASRS_FILTERS.items():
        reports[name] = blank_to_na(d[src]).to_numpy()
    reports["flight_phase"] = split_multi(reports["flight_phase"])
    reports["query_year"] = d["query_year"].astype("int16").to_numpy()
    reports["outside_query_year"] = (reports["year"] != reports["query_year"]).to_numpy()

    labels = pd.DataFrame({"ACN": d["ACN"].astype(STR)})
    for src, name in ASRS_HIDDEN.items():
        col = blank_to_na(d[src])
        labels[name] = (split_multi(col) if name in ASRS_MULTI else col).to_numpy()

    outputs = {
        "processed/reports.parquet": save(reports, proc / "reports.parquet"),
        "hidden/labels.parquet": save(labels, hid / "labels.parquet"),
    }
    checks = {
        "reports_by_incident_year": reports["year"].value_counts().sort_index().to_dict(),
        "outside_query_year_moved_to_incident_year": int(reports["outside_query_year"].sum()),
        "dropped_incident_outside_2018_2023": dropped,
        "with_second_narrative": int(reports["narrative_2"].notna().sum()),
        "distinct_anomaly_values": int(labels["anomaly"].explode().nunique()),
    }
    assert reports["year"].between(ASRS_YEARS[0], ASRS_YEARS[-1]).all()
    write_manifest("asrs", {"A3": "year = incident month (Time|Date); reports with incident month outside 2018-2023 "
                                  "dropped (listed in checks)",
                            "A4": "Synopsis, Callbacks and analyst-coded fields are in hidden/"}, outputs, checks)


# ====================================================================== MAUDE
MAUDE_CODES = ["FRN", "LZG", "QFG", "OYC", "OZP", "OZO", "MDS", "PQF", "QBJ", "QLG", "LWS", "NIK"]
MAUDE_YEARS = range(2018, 2026)
NPART = 16
CHUNK = 500_000
IMDRF_XLSX = DATA / "maude/docs/imdrf/imdrf-tech-ae-terminologies-n43-ReleaseNumber2026-Annexes-revisedJune.xlsx"

# ---- M5: embedded code blocks in MAUDE text ------------------------------------------------------------------
# Manufacturers paste coded fields into the narrative, e.g. "OMIT : A1301 - FAILURE TO READ INPUT SIGNAL (1581),
# B21 - ...", "ANNEX A: A1801. ANNEX G: G02005", "H6 MEDICAL DEVICE PROBLEM CODE - 3191 - ...",
# "TYPE OF REPORTABLE EVENT: MALFUNCTION". These reveal hidden labels, so they are removed. Codes:
# long IMDRF codes (A/C/E/F + 4 or 6 digits, G + 5 or 7 digits, D + 4 digits) anywhere; short level-1 codes
# (letter + 2 digits) only in code context (before " - <term>" or in an "ANNEX X:" list).
LONG_CODE = r"(?:[ACEF]\d{4}(?:\d{2})?|G\d{5}(?:\d{2})?|D\d{4})"
SHORT_CODE = r"[A-G]\d{2}"
PREFILTER = re.compile(r"\b[A-G]\d{4}|\b[A-G]\d{2}\s*[-:]|\(\d{4}\)|CODES?\W{0,5}\d{4}|REPORTABLE\s+EVENT|ANNEX\s+[A-G]",
                       re.I)
EVENT_TYPES = r"(?:DEATH|SERIOUS\s+INJURY|INJURY|MALFUNCTION|OTHER|NO\s+ANSWER\s+PROVIDED)"


def term_alternation(terms) -> str:
    """Regex alternation of code terms (longest first); spaces match any whitespace, '/' may have spaces."""
    ts = sorted({t.strip() for t in terms if isinstance(t, str) and len(t.strip()) >= 3}, key=len, reverse=True)
    return "(?:" + "|".join(re.escape(t).replace(r"\ ", r"\s+").replace("/", r"\s*/\s*") for t in ts) + ")"


# "CODE NNNN" is a hidden FDA code unless the word before it marks a device message (ERROR CODE 1110, ALERT CODE ...).
KEEP_BEFORE_CODE = {"ERROR", "ALERT", "ALARM", "FAULT", "A", "AN", "THE", "OF", "IN", "METHOD", "BIOMED", "FINDINGS",
                    "CONCLUSION", "RESULT", "RESULTS", "EXHIBITED", "DECLARED", "RECORDED", "DISPLAYED", "DISPLAY",
                    "SERVICE", "SYSTEM", "PUMP", "STATUS", "WARNING", "MESSAGE", "ZIP", "POSTAL"}


class CodeStripper:
    """M5: removes embedded code items from MAUDE text (see the comment above LONG_CODE)."""

    def __init__(self, terms=(), fda_codes=()):
        self.fda_codes = {str(c).strip() for c in fda_codes if str(c).strip().isdigit()}
        term = term_alternation(terms) if len(terms) else r"(?!)"
        sep = r"\s*[-:]\s*"
        fda = r"\d{4}(?:\s*[,;/&]\s*\d{4})*"
        any_item = rf"\b(?:{LONG_CODE}|{SHORT_CODE})\b(?:{sep}{term}\b)?(?:\s*\(\d{{4}}\))?"
        self.patterns = [re.compile(p, re.I) for p in (
            rf"ANNEX\s+[A-G]\s*[:\-]\s*{any_item}(?:\s*,\s*{any_item})*",          # ANNEX A: A1801, A0601
            rf"TYPE\s+OF\s+REPORTABLE\s+EVENT\s*[:\-]?\s*{EVENT_TYPES}\b",
            rf"\bH6\s*\(\s*{fda}\s*\)",                                                  # SECTION H6 (2978)
            rf"\b{LONG_CODE}\b(?:{sep}{term}\b)?(?:\s*\(\d{{4}}\))?",                # A1301 - TERM (1581)
            rf"\b{SHORT_CODE}\b{sep}{term}\b(?:\s*\(\d{{4}}\))?",                    # B21 - TERM
        )]
        self.code_word = re.compile(rf"(?:\b(\w+)(\W{{0,6}}))?\bCODE[DS]?[^\w\n]{{0,8}}{fda}\b\)?(?:{sep}{term}\b)?\"?",
                                    re.I)
        # "<FDA or IMDRF term> (NNNN)": suffix lookup instead of a 3,000-way alternation at every position
        self.terms = {" ".join(t.upper().split()) for t in terms if isinstance(t, str) and len(t.strip()) >= 3}
        self.lens = sorted({len(t) for t in self.terms}, reverse=True)

    def _term_paren(self, t: str) -> str:
        for m in reversed(list(re.finditer(r"\(\d{4}\)", t))):
            head = t[:m.start()].rstrip()
            up = " ".join(head[-200:].upper().split())
            for n in self.lens:
                if len(up) >= n and up[-n:] in self.terms and (len(up) == n or not up[-n - 1].isalnum()):
                    hit = re.search(re.escape(up[-n:]).replace(r"\ ", r"\s+") + r"\s*$", head, re.I)
                    if hit:
                        t = t[:hit.start()] + " " + t[m.end():]
                    break
        return t

    def __call__(self, text: str) -> str:
        t = text
        for p in self.patterns:
            t = p.sub(" ", t)
        t = self.code_word.sub(lambda m: m.group(0) if (m.group(1) or "").upper() in KEEP_BEFORE_CODE
                               else (m.group(1) or "") + (m.group(2) or ""), t)
        if self.terms:
            t = self._term_paren(t)
        if self.fda_codes:  # bare "(2978)" / "[4014]" holding a valid FDA problem code (years left alone)
            t = re.sub(r"[(\[]\s*(\d{4})\s*[)\]]", lambda m: " " if m.group(1) in self.fda_codes
                       and not 1990 <= int(m.group(1)) <= 2030 else m.group(0), t)
        if t != text:
            t = re.sub(r"\b(OMIT|ANNEX\s+[A-G])\s*:\s*(?=[,.;]|$)", " ", t, flags=re.I | re.M)
            t = re.sub(r"\s*[,;](?:\s*[,;])+", ",", t)       # ", ," left by removed list items
            t = re.sub(r"(?m)^[ \t]*[,;.][ \t]*", "", t)
            t = re.sub(r"[ \t]{2,}", " ", t).strip()
        return t


def strip_codes(s: pd.Series, stripper: CodeStripper | None = None) -> tuple[pd.Series, np.ndarray]:
    """Remove embedded code items; return the cleaned text and a mask of changed rows."""
    stripper = stripper or CodeStripper()
    out = s.copy()
    cand = s.fillna("").str.contains(PREFILTER)
    changed = np.zeros(len(s), dtype=bool)
    for i in np.flatnonzero(cand.to_numpy()):
        t = stripper(s.iat[i])
        if t != s.iat[i]:
            out.iat[i] = t if t else None
            changed[i] = True
    return out, changed


def code_leftovers(out: pd.DataFrame, dp_codes: pd.DataFrame, pp_codes: pd.DataFrame) -> int:
    """Number of reports whose text still contains one of their own hidden codes: an IMDRF code as a token, an FDA
    code as '(NNNN)' / '[NNNN]', or 'CODE NNNN' not preceded by a device-message word (ERROR CODE 1260 is signal)."""
    text = out["text_event_description"].fillna("") + "\n" + out["text_mfr_narrative"].fillna("")
    pat = re.compile(r"\b([AE]\d{4,6})\b|[(\[](\d{4})[)\]]|(?:\b(\w+)\W{0,6})?\bCODE[DS]?\W{0,6}(\d{4})\b", re.I)
    n = 0
    for key, s in zip(out["MDR_REPORT_KEY"], text):
        toks = set()
        for m in pat.finditer(s):
            imdrf, paren, word, num = m.groups()
            if num and (word or "").upper() in KEEP_BEFORE_CODE:
                continue
            toks.add((imdrf or "").upper() or paren or num)
        if not toks:
            continue
        own = set()
        for tab in (dp_codes, pp_codes):
            if key in tab.index:
                own |= {c for c in tab.at[key, "fda"] | tab.at[key, "imdrf"] if isinstance(c, str) and len(c) >= 4}
        n += bool(own & toks)
    return n


SAMPLE_SEED = 20261120
SAMPLE_TARGET = 1_000_000
KEEP_WHOLE = {"LWS", "NIK"}  # decided (issue #2)
WHOLE_MAX = 150_000          # codes with at most this many reports are also kept whole (MDS, QLG)


def unit_hash(keys: np.ndarray, seed: int) -> np.ndarray:
    """Deterministic uniform [0, 1) per report key (splitmix64), so the sample does not depend on row order."""
    with np.errstate(over="ignore"):
        x = keys.astype(np.uint64) + np.uint64(seed) * np.uint64(0x9E3779B97F4A7C15)
        x = (x ^ (x >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        x = (x ^ (x >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        x = x ^ (x >> np.uint64(31))
    return (x >> np.uint64(11)).astype(np.float64) / float(2 ** 53)


def sampling_rates(counts: pd.Series) -> tuple[dict, pd.DataFrame]:
    """M2: small codes and LWS/NIK whole; one common rate for the rest so the expected total is SAMPLE_TARGET."""
    whole = counts.index.isin(sorted(KEEP_WHOLE)) | (counts <= WHOLE_MAX)
    rest_rate = (SAMPLE_TARGET - counts[whole].sum()) / counts[~whole].sum()
    assert 0 < rest_rate < 1, rest_rate
    rates = {c: (1.0 if w else round(float(rest_rate), 6)) for c, w in zip(counts.index, whole)}
    return rates, pd.DataFrame({"before": counts})


def maude_chunks(zip_name: str, rows_read: dict, names=None, usecols=None):
    z = zipfile.ZipFile(DATA / "maude/raw" / zip_name)
    it = pd.read_csv(z.open(z.namelist()[0]), sep="|", dtype=str, encoding="latin-1", keep_default_na=False,
                     quoting=3, on_bad_lines="skip", chunksize=CHUNK, names=names,
                     header=None if names else "infer", usecols=usecols)
    n = 0
    for ch in it:
        n += len(ch)
        ch["MDR_REPORT_KEY"] = pd.to_numeric(ch["MDR_REPORT_KEY"], errors="coerce").astype("Int64")
        yield ch
    rows_read[zip_name] = n


def maude() -> None:
    proc, hid = fresh_dirs("maude")
    tmp = DATA / "maude/_tmp_text"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    rows_read: dict[str, int] = {}

    # 1. devices -> candidate keys (first candidate device per report, plus device count)
    dev_cols = ["MDR_REPORT_KEY", "DEVICE_SEQUENCE_NO", "DEVICE_REPORT_PRODUCT_CODE", "MANUFACTURER_D_NAME",
                "BRAND_NAME", "GENERIC_NAME", "MODEL_NUMBER"]
    dev = []
    for y in MAUDE_YEARS:
        for ch in maude_chunks(f"device{y}.zip", rows_read, usecols=dev_cols):
            dev.append(ch[ch["DEVICE_REPORT_PRODUCT_CODE"].isin(MAUDE_CODES)].astype(
                {c: STR for c in dev_cols[1:]}))
        print(f"  device{y}", flush=True)
    dev = pd.concat(dev)
    dev["seq"] = pd.to_numeric(dev["DEVICE_SEQUENCE_NO"], errors="coerce")
    dev = dev.sort_values(["MDR_REPORT_KEY", "seq"])
    n_dev = dev.groupby("MDR_REPORT_KEY").size().rename("n_candidate_devices")
    dev = dev.drop_duplicates("MDR_REPORT_KEY").set_index("MDR_REPORT_KEY").join(n_dev)
    keys = dev.index.to_numpy(dtype="int64")
    print(f"  candidate reports: {len(keys)}", flush=True)

    def keep(ch):
        return ch[ch["MDR_REPORT_KEY"].isin(keys)]

    # 2. master
    m_cols = ["MDR_REPORT_KEY", "REPORT_NUMBER", "DATE_RECEIVED", "DATE_OF_EVENT", "REPORT_SOURCE_CODE",
              "SUMMARY_REPORT", "NOE_SUMMARIZED", "EVENT_TYPE", "ADVERSE_EVENT_FLAG", "PRODUCT_PROBLEM_FLAG"]
    master = pd.concat(keep(ch).astype({c: STR for c in m_cols[1:]})
                       for ch in maude_chunks("mdrfoiThru2025.zip", rows_read, usecols=m_cols))
    master = master.drop_duplicates("MDR_REPORT_KEY").set_index("MDR_REPORT_KEY")
    print("  master", flush=True)

    # M6: drop summary reports; also drop candidates without a master row (no date, no labels)
    n_candidates = len(keys)
    no_master = ~pd.Index(keys).isin(master.index)
    summary = yflag(master["SUMMARY_REPORT"]).reindex(keys, fill_value=False).to_numpy()
    keys = keys[~no_master & ~summary]
    # M2: one fixed sampling rate per product code, the same in every year
    code = dev["DEVICE_REPORT_PRODUCT_CODE"].reindex(keys).to_numpy()
    rates, per_code = sampling_rates(pd.Series(code).value_counts())
    u = unit_hash(keys, SAMPLE_SEED)
    sampled = u < pd.Series(code).map(rates).to_numpy()
    keys = keys[sampled]
    dev = dev.loc[keys]
    master = master.loc[keys]
    sample_info = {"seed": SAMPLE_SEED, "target_total": SAMPLE_TARGET, "keep_whole": sorted(KEEP_WHOLE),
                   "keep_whole_if_at_most": WHOLE_MAX, "rates": rates, "reports_before_after": per_code.assign(
                       after=pd.Series(code[sampled]).value_counts()).fillna(0).astype(int).to_dict("index")}
    drop_info = {"candidates": n_candidates, "no_master_row": int(no_master.sum()),
                 "summary_reports": int((summary & ~no_master).sum()), "after_sampling": len(keys)}
    print(f"  sampled {len(keys)} of {n_candidates} candidate reports", flush=True)

    # 3. patients (first patient per report)
    p_cols = ["MDR_REPORT_KEY", "PATIENT_SEQUENCE_NUMBER", "PATIENT_AGE", "PATIENT_SEX", "SEQUENCE_NUMBER_OUTCOME",
              "SEQUENCE_NUMBER_TREATMENT"]
    pat = pd.concat(keep(ch).astype({c: STR for c in p_cols[1:]})
                    for ch in maude_chunks("patientthru2025.zip", rows_read, usecols=p_cols))
    pat = pat.sort_values(["MDR_REPORT_KEY", "PATIENT_SEQUENCE_NUMBER"]).drop_duplicates("MDR_REPORT_KEY")
    pat = pat.set_index("MDR_REPORT_KEY")
    print("  patients", flush=True)

    # 4. problem codes (hidden, long format, with terms)
    def code_terms(zip_name):
        with zipfile.ZipFile(DATA / "maude/raw" / zip_name) as z:
            t = pd.read_csv(z.open(z.namelist()[0]), dtype=str, encoding="utf-8-sig", keep_default_na=False)
        return t.set_index("FDA_CODE")[["TERM", "IMDRF_CODE"]]

    dterms = code_terms("deviceproblemcodes2025.zip")
    dp = pd.concat(keep(ch) for ch in maude_chunks("foidevproblem_thru2025.zip", rows_read,
                                                   names=["MDR_REPORT_KEY", "DEVICE_PROBLEM_CODE"]))
    dp = dp.drop_duplicates().join(dterms, on="DEVICE_PROBLEM_CODE")
    pterms = code_terms("patientproblemdata.zip")
    pp = pd.concat(keep(ch)[["MDR_REPORT_KEY", "PROBLEM_CODE"]]
                   for ch in maude_chunks("patientproblemcode_thru2025.zip", rows_read))
    pp = pp.drop_duplicates().join(pterms, on="PROBLEM_CODE")
    print("  problem codes", flush=True)
    imdrf_terms = []
    for sheet in "ABCDEFG":
        a = pd.read_excel(IMDRF_XLSX, sheet, dtype=str, header=7)
        imdrf_terms += a.filter(regex=r"^Level \d Term$").stack().tolist()
    code_patterns = CodeStripper(list(dterms["TERM"]) + list(pterms["TERM"]) + imdrf_terms,
                                 fda_codes=list(dterms.index) + list(pterms.index))

    # 5. text rows -> partitions by key
    writers: dict[int, pq.ParquetWriter] = {}
    schema = pa.schema([("MDR_REPORT_KEY", pa.int64()), ("MDR_TEXT_KEY", pa.int64()),
                        ("TEXT_TYPE_CODE", pa.string()), ("FOI_TEXT", pa.string())])
    for y in MAUDE_YEARS:
        for ch in maude_chunks(f"foitext{y}.zip", rows_read,
                               usecols=["MDR_REPORT_KEY", "MDR_TEXT_KEY", "TEXT_TYPE_CODE", "FOI_TEXT"]):
            ch = keep(ch).copy()
            ch["MDR_TEXT_KEY"] = pd.to_numeric(ch["MDR_TEXT_KEY"], errors="coerce").astype("Int64")
            part = (ch["MDR_REPORT_KEY"] % NPART).astype(int)
            for p, g in ch.groupby(part):
                if p not in writers:
                    writers[p] = pq.ParquetWriter(tmp / f"text_{p:02d}.parquet", schema, compression="zstd")
                writers[p].write_table(pa.Table.from_pandas(g, schema=schema, preserve_index=False))
        print(f"  foitext{y}", flush=True)
    for w in writers.values():
        w.close()

    # 6. assemble per partition
    rep_dir = proc / "reports"
    rep_dir.mkdir()
    n_reports = n_embedded = n_no_text = n_leftover = 0
    dp_codes = dp.groupby("MDR_REPORT_KEY").agg(fda=("DEVICE_PROBLEM_CODE", set), imdrf=("IMDRF_CODE", set))
    pp_codes = pp.groupby("MDR_REPORT_KEY").agg(fda=("PROBLEM_CODE", set), imdrf=("IMDRF_CODE", set))
    for p in range(NPART):
        pk = keys[keys % NPART == p]
        t = pq.read_table(tmp / f"text_{p:02d}.parquet").to_pandas() if (tmp / f"text_{p:02d}.parquet").exists() \
            else pd.DataFrame(columns=schema.names)
        t = t.drop_duplicates("MDR_TEXT_KEY", keep="last").sort_values(["MDR_REPORT_KEY", "MDR_TEXT_KEY"])
        t["FOI_TEXT"] = t["FOI_TEXT"].str.strip()
        t = t[t["FOI_TEXT"] != ""]
        txt = t.groupby(["MDR_REPORT_KEY", "TEXT_TYPE_CODE"])["FOI_TEXT"].agg("\n\n".join).unstack()
        r = pd.DataFrame(index=pd.Index(pk, name="MDR_REPORT_KEY"))
        r = r.join(master[["REPORT_NUMBER", "DATE_RECEIVED", "DATE_OF_EVENT", "REPORT_SOURCE_CODE"]])
        r = r.join(dev[["DEVICE_REPORT_PRODUCT_CODE", "MANUFACTURER_D_NAME", "BRAND_NAME", "GENERIC_NAME",
                        "MODEL_NUMBER", "n_candidate_devices"]])
        r = r.join(pat[["PATIENT_AGE", "PATIENT_SEX"]])
        r = r.join(txt.reindex(columns=["D", "N"]))
        out = pd.DataFrame({
            "MDR_REPORT_KEY": r.index.to_numpy(),
            "report_number": r["REPORT_NUMBER"].to_numpy(),
            "date_received": pd.to_datetime(r["DATE_RECEIVED"], format="%m/%d/%Y", errors="coerce").dt.date.to_numpy(),
            "date_of_event": pd.to_datetime(r["DATE_OF_EVENT"], format="%m/%d/%Y", errors="coerce").dt.date.to_numpy(),
            "report_source": blank_to_na(r["REPORT_SOURCE_CODE"]).to_numpy(),
            "product_code": r["DEVICE_REPORT_PRODUCT_CODE"].to_numpy(),
            "manufacturer": blank_to_na(r["MANUFACTURER_D_NAME"]).to_numpy(),
            "brand_name": blank_to_na(r["BRAND_NAME"]).to_numpy(),
            "generic_name": blank_to_na(r["GENERIC_NAME"]).to_numpy(),
            "model_number": blank_to_na(r["MODEL_NUMBER"]).to_numpy(),
            "n_candidate_devices": r["n_candidate_devices"].astype("int16").to_numpy(),
            "patient_age": blank_to_na(r["PATIENT_AGE"]).to_numpy(),
            "patient_sex": blank_to_na(r["PATIENT_SEX"]).to_numpy(),
            "text_event_description": r["D"].astype(STR).to_numpy(),
            "text_mfr_narrative": r["N"].astype(STR).to_numpy(),
            "sample_rate": r["DEVICE_REPORT_PRODUCT_CODE"].map(rates).astype("float64").to_numpy(),
        })
        # M5: strip embedded code blocks; the flag marks reports whose text was changed
        flags = np.zeros(len(out), dtype=bool)
        for col in ("text_event_description", "text_mfr_narrative"):
            stripped, changed = strip_codes(out[col], code_patterns)
            out[col] = stripped
            flags |= changed
        out["has_embedded_codes"] = flags
        leftover = code_leftovers(out, dp_codes, pp_codes)
        assert leftover == 0, f"M5: partition {p}: {leftover} reports still contain one of their own hidden codes"
        n_leftover += leftover
        save(out, rep_dir / f"part-{p:02d}.parquet")
        n_reports += len(out)
        n_embedded += int(out["has_embedded_codes"].sum())
        n_no_text += int((out["text_event_description"].isna() & out["text_mfr_narrative"].isna()).sum())
        print(f"  partition {p:02d}: {len(out)} reports", flush=True)
    shutil.rmtree(tmp)

    lab = master[["EVENT_TYPE", "ADVERSE_EVENT_FLAG", "PRODUCT_PROBLEM_FLAG"]].join(
        pat[["SEQUENCE_NUMBER_OUTCOME", "SEQUENCE_NUMBER_TREATMENT"]]).reindex(keys)
    labels = pd.DataFrame({
        "MDR_REPORT_KEY": keys,
        "event_type": blank_to_na(lab["EVENT_TYPE"].fillna("")).to_numpy(),
        "adverse_event_flag": blank_to_na(lab["ADVERSE_EVENT_FLAG"].fillna("")).to_numpy(),
        "product_problem_flag": blank_to_na(lab["PRODUCT_PROBLEM_FLAG"].fillna("")).to_numpy(),
        "patient_outcome": blank_to_na(lab["SEQUENCE_NUMBER_OUTCOME"].fillna("")).to_numpy(),
        "patient_treatment": blank_to_na(lab["SEQUENCE_NUMBER_TREATMENT"].fillna("")).to_numpy(),
    })
    dp_out = dp.rename(columns={"DEVICE_PROBLEM_CODE": "code", "TERM": "term", "IMDRF_CODE": "imdrf_code"})
    pp_out = pp.rename(columns={"PROBLEM_CODE": "code", "TERM": "term", "IMDRF_CODE": "imdrf_code"})

    manifest_rows = {k: v["members"][0]["rows"] for k, v in
                     json.loads((DATA / "maude/MANIFEST.json").read_text())["files"].items()}
    outputs = {
        "processed/reports/ (16 parts)": n_reports,
        "hidden/labels.parquet": save(labels, hid / "labels.parquet"),
        "hidden/device_problems.parquet": save(dp_out, hid / "device_problems.parquet"),
        "hidden/patient_problems.parquet": save(pp_out, hid / "patient_problems.parquet"),
    }
    assert n_leftover == 0, f"M5: {n_leftover} reports still contain one of their own hidden codes after stripping"
    checks = {
        "report_selection": drop_info,
        "sampling": sample_info,
        "reports_without_text": n_no_text,
        "reports_with_embedded_codes_stripped": n_embedded,
        "reports_with_own_code_in_text_after_strip": n_leftover,
        "event_type_counts": labels["event_type"].value_counts(dropna=False).to_dict(),
        "reports_by_product_code": dev["DEVICE_REPORT_PRODUCT_CODE"].value_counts().to_dict(),
        "unmatched_device_problem_terms": int(dp_out["term"].isna().sum()),
        "unmatched_patient_problem_terms": int(pp_out["term"].isna().sum()),
        "raw_rows_parsed_vs_manifest_lines": {k: {"parsed": v, "manifest": manifest_rows.get(k)}
                                              for k, v in rows_read.items()},
    }
    write_manifest("maude", {"M2": "12 product codes (4 groups); one fixed rate per product code, the same every year "
                                   "(seeded hash of MDR_REPORT_KEY); LWS, NIK and codes with <= 150k reports whole; "
                                   "rate per report in column sample_rate (weight = 1 / sample_rate)",
                             "M4": "EVENT_TYPE, problem codes and leak fields in hidden/",
                             "M5": "embedded code blocks stripped from both text fields; has_embedded_codes marks "
                                   "changed reports; build fails if a report's own code survives in its text",
                             "M6": "summary reports dropped (count in checks.report_selection)",
                             "years": "received 2018-2025 (device files of those years)"}, outputs, checks)


if __name__ == "__main__":
    for t in sys.argv[1:] or ["vaers", "asrs", "maude"]:
        {"vaers": vaers, "asrs": asrs, "maude": maude}[t]()
