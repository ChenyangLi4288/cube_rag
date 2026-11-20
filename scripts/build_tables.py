"""Build processed tables from the raw downloads (version v0, draft — not frozen).

For each dataset:
  data/<ds>/processed/   what the method may read: key + text + filter fields
  data/<ds>/hidden/      ground truth (core + leak fields) — never give these to the method
  data/<ds>/PROCESSED_MANIFEST.json   row counts, rules applied, git commit, raw-file integrity checks

Field roles follow data/README.md. Decisions still open are kept as flag columns, not applied:
  MAUDE  product codes (M2)  -> column product_code (all 12 candidates kept)
         embedded codes (M5) -> has_embedded_codes
         summary reports (M6)-> summary_report, noe_summarized
  ASRS   year rule (A3)      -> outside_query_year, before_2018
Applied rule:
  VAERS  primary reports only, ORDER = 1 (V1, proposed)

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

DATA = Path("data")
VERSION = "v0-draft"
STR = "string[pyarrow]"


def git_commit() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "scripts/build_tables.py"], capture_output=True,
                               text=True).stdout.strip()
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
    data, symp, vax = [], [], []
    for y in VAERS_YEARS:
        with zipfile.ZipFile(DATA / "vaers/raw" / f"{y}VAERSData.zip") as z:
            rd = lambda k: pd.read_csv(z.open(f"{y}{k}.csv"), dtype=str, encoding="latin-1",  # noqa: E731
                                       keep_default_na=False)
            d = rd("VAERSDATA")
            d = d[d["ORDER"] == "1"].assign(source_file=y)
            s, v = rd("VAERSSYMPTOMS"), rd("VAERSVAX")
            data.append(d)
            symp.append(s[s["ORDER"] == "1"])
            vax.append(v[v["ORDER"] == "1"])
    d, s, v = pd.concat(data), pd.concat(symp), pd.concat(vax)
    assert d["VAERS_ID"].is_unique, "VAERS_ID not unique after ORDER=1 filter"

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
    }
    write_manifest("vaers", {"V1": "primary reports only (ORDER = 1)", "V2": "domestic yearly files only"},
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
ASRS_MULTI = {"flight_phase", "anomaly", "result", "detector", "contributing_factors", "human_factors_1",
              "human_factors_2"}


def split_multi(s: pd.Series) -> pd.Series:
    return s.map(lambda x: [p.strip() for p in x.split(";") if p.strip()] if isinstance(x, str) and x.strip() else None)


def asrs() -> None:
    proc, hid = fresh_dirs("asrs")
    parts = []
    for y in range(2018, 2024):
        df = pd.read_csv(DATA / "asrs/raw" / f"ASRS_{y}.csv", header=[0, 1], dtype=str, encoding="latin-1",
                         keep_default_na=False)
        df.columns = ["|".join(p for p in c if p.strip() and not p.startswith("Unnamed")) for c in df.columns]
        parts.append(df.loc[:, df.columns != ""].assign(query_year=y))
    d = pd.concat(parts)
    assert d["ACN"].is_unique, "duplicate ACN across files"

    month = pd.to_datetime(d["Time|Date"], format="%Y%m", errors="coerce")
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
    reports["before_2018"] = (reports["year"] < 2018).to_numpy()

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
        "outside_query_year": int(reports["outside_query_year"].sum()),
        "before_2018": int(reports["before_2018"].sum()),
        "with_second_narrative": int(reports["narrative_2"].notna().sum()),
        "distinct_anomaly_values": int(labels["anomaly"].explode().nunique()),
    }
    write_manifest("asrs", {"A3": "not applied; flags outside_query_year and before_2018 (2 ACNs dated 2002, 2012)",
                            "A4": "Synopsis, Callbacks and analyst-coded fields are in hidden/"}, outputs, checks)


# ====================================================================== MAUDE
MAUDE_CODES = ["FRN", "LZG", "QFG", "OYC", "OZP", "OZO", "MDS", "PQF", "QBJ", "QLG", "LWS", "NIK"]
MAUDE_YEARS = range(2018, 2026)
NPART = 16
CHUNK = 500_000
EMBEDDED = re.compile(r"Device Problem Code|Health Effect|Patient Problem Code|Type of Reportable Event|IMDRF",
                      re.IGNORECASE)


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
    rep_dir, lab_parts = proc / "reports", []
    rep_dir.mkdir()
    n_reports = n_embedded = n_no_text = 0
    for p in range(NPART):
        pk = keys[keys % NPART == p]
        t = pq.read_table(tmp / f"text_{p:02d}.parquet").to_pandas() if (tmp / f"text_{p:02d}.parquet").exists() \
            else pd.DataFrame(columns=schema.names)
        t = t.drop_duplicates("MDR_TEXT_KEY", keep="last").sort_values(["MDR_REPORT_KEY", "MDR_TEXT_KEY"])
        t["FOI_TEXT"] = t["FOI_TEXT"].str.strip()
        t = t[t["FOI_TEXT"] != ""]
        txt = t.groupby(["MDR_REPORT_KEY", "TEXT_TYPE_CODE"])["FOI_TEXT"].agg("\n\n".join).unstack()
        r = pd.DataFrame(index=pd.Index(pk, name="MDR_REPORT_KEY"))
        r = r.join(master[["REPORT_NUMBER", "DATE_RECEIVED", "DATE_OF_EVENT", "REPORT_SOURCE_CODE", "SUMMARY_REPORT",
                           "NOE_SUMMARIZED"]])
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
            "summary_report": yflag(r["SUMMARY_REPORT"].fillna("")).to_numpy(),
            "noe_summarized": pd.to_numeric(r["NOE_SUMMARIZED"], errors="coerce").astype("Int32").to_numpy(),
        })
        both = out["text_event_description"].fillna("") + "\n" + out["text_mfr_narrative"].fillna("")
        out["has_embedded_codes"] = both.str.contains(EMBEDDED).to_numpy()
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
    checks = {
        "candidate_reports": int(len(keys)),
        "reports_missing_master_row": int((~pd.Index(keys).isin(master.index)).sum()),
        "reports_without_text": n_no_text,
        "reports_with_embedded_codes": n_embedded,
        "event_type_counts": labels["event_type"].value_counts(dropna=False).to_dict(),
        "reports_by_product_code": dev["DEVICE_REPORT_PRODUCT_CODE"].value_counts().to_dict(),
        "unmatched_device_problem_terms": int(dp_out["term"].isna().sum()),
        "unmatched_patient_problem_terms": int(pp_out["term"].isna().sum()),
        "raw_rows_parsed_vs_manifest_lines": {k: {"parsed": v, "manifest": manifest_rows.get(k)}
                                              for k, v in rows_read.items()},
    }
    write_manifest("maude", {"M2": "not applied; all 12 candidate codes kept (column product_code)",
                             "M5": "not applied; flag has_embedded_codes",
                             "M6": "not applied; flags summary_report, noe_summarized",
                             "years": "received 2018-2025 (device files of those years)"}, outputs, checks)


if __name__ == "__main__":
    for t in sys.argv[1:] or ["vaers", "asrs", "maude"]:
        {"vaers": vaers, "asrs": asrs, "maude": maude}[t]()
