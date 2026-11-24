# Data fields

Field tables for each dataset (STUDENT_START.md, task 3). Raw data is not in git; see each `MANIFEST.json`.
Fill rates and leakage numbers come from `scripts/profile_fields.py`, which writes `data/<ds>/field_profile.csv`
(every column) and `data/<ds>/leakage_checks.json`. Profiled on 2026-11-19.

## Layout

```
data/<ds>/
  raw/                     downloads as received; never modified (sha256 in MANIFEST.json)
  processed/               what the method may read: key + text + filter fields
  hidden/                  ground truth (core + leak fields); never give to the method
  MANIFEST.json            raw files: source, date, sha256, row counts
  PROCESSED_MANIFEST.json  processed tables: version, rules applied, git commit, row counts, checks
  field_profile.csv, leakage_checks.json   per-column profile (scripts/profile_fields.py)
```

Built by `scripts/build_tables.py`, version **v1** (decisions of 2026-11-20 applied, issue #2; rules and counts in
each `PROCESSED_MANIFEST.json`). Parquet, zstd.

| Dataset | processed/ | hidden/ |
|---|---|---|
| VAERS | `reports.parquet` (1 row per primary report; `vax_types` list), `vaccines.parquet` (1 row per vaccine) | `labels.parquet` (outcome flags from the primary row, plus `<flag>_any_order` sensitivity labels), `symptoms.parquet` (MedDRA PTs, long), `lattice_vaers_clusters_support.csv`, `lattice_vaers_meddra_support.csv` |
| ASRS | `reports.parquet` (1 row per ACN, 2018–2023 by incident month; `narrative_1`, `narrative_2`, filters; `outside_query_year` = moved to its incident year) | `labels.parquet` (anomaly list, primary problem, synopsis, analyst-coded fields), `anomaly_nodes.parquet` |
| MAUDE | `reports/part-00..15.parquet` (1 row per report; `text_event_description`, `text_mfr_narrative` with embedded code blocks stripped; filters; `sample_rate`; `has_embedded_codes`) | `labels.parquet` (event type, flags, patient outcome), `device_problems.parquet`, `patient_problems.parquet` (code + term, long), lattice support/coverage files, `crosswalk_trend_check.csv` |

Rules applied in v1 (STATE.md):

- **MAUDE M2:** 12 product codes, received 2018–2025, sampled with one fixed rate per product code, the same every
  year (seeded hash of `MDR_REPORT_KEY`). LWS, NIK, MDS and QLG are kept whole; the other 8 codes share one rate,
  chosen so the expected total is 10⁶. `sample_rate` is stored per report: weight = 1 / `sample_rate`.
  **Any count pooled across product codes must use this weight** (an unweighted pooled count over-represents the
  whole-kept codes LWS, NIK, QLG, MDS about 11×). Counts within one product code need no weight: its rate is constant.
- **MAUDE M5:** embedded code blocks (IMDRF codes with terms, `ANNEX A: …` lists, `PROBLEM CODE - 3191`,
  `TYPE OF REPORTABLE EVENT: …`, FDA codes in brackets) are removed from both text fields; `has_embedded_codes`
  marks changed reports, so "drop these reports" is one filter. The build fails if any report still contains one of
  its own hidden codes; `ERROR CODE 1260`-style device messages are kept (signal). Tests: `tests/test_build_tables.py`.
- **MAUDE M6:** the 496 summary reports are dropped; candidates without a master row are dropped too.
- **VAERS V1:** `ORDER = 1` only; `<flag>_any_order` = true if any row of the VAERS_ID (in the four year files) says so.
- **ASRS A3:** year = incident month; the 2 reports dated 2002 and 2012 are dropped.

VAERS lattices (local, never committed — MSSO terms; STATE.md V4/V5): `data/vaers/MedDRA_29_1_English_v2/` is the
licensed MedDRA 29.1 release (frozen like `raw/`). `scripts/build_vaers_meddra.py` builds the main VAERS lattice in
`data/vaers/lattice_meddra/` (SOC ≤ … ≤ PT DAG, mapping, unmapped terms); `build_vaers_clusters.py` and
`build_vaers_anchored.py` build the alternative lattices in `lattice_clusters/` and `lattice_clusters_anchored/`.

## Roles

| Role | Meaning |
|---|---|
| **text** | Input to the extractor. |
| **filter** | Structured attribute a query may use in σ (ALGEBRA.md). *core* = listed in EXPERIMENTS.md; *optional* = available if a query needs it. |
| **hidden** | Ground truth. Stored in a separate table the method never reads. *core* = listed in EXPERIMENTS.md; *leak* = not a target, but it reveals a target, so it is hidden too. |
| **key** | Join or identity field. |
| **excluded** | Not used. |

Rule of thumb: a field that a coder or analyst filled in *about the outcome* is hidden, even if it is not a query target.

---

## MAUDE

- **Source:** FDA MDR data files (`data/maude/raw/`). Pipe-delimited, latin-1, no quoting.
- **Subset profiled:** reports with a candidate product code (FRN, LZG, QFG, OYC, OZP, OZO, MDS, PQF, QBJ, QLG, LWS,
  NIK), received 2018–2025: **6,829,664 reports**. The final codes and years are not decided (STATE.md M2).
- **Unit:** one report = one `MDR_REPORT_KEY`. Follow-up reports update the same key (`TYPE_OF_REPORT` = I, I,F, …),
  so there is one master row per report.
- **Files:** `mdrfoiThru2025` (master, 1 row per report), `deviceYYYY` (≈1 row per device per report),
  `foitextYYYY` (≈2.4 text rows per report), `foidevproblem_thru2025` (≈1.2 device problem codes per report),
  `patientproblemcode_thru2025`, `patientthru2025`. All join on `MDR_REPORT_KEY`.
- `EVENT_TYPE` in this subset: malfunction `M` 91.8%, injury `IN` 8.1%, death `D` 0.11% (7,686), other `O` < 0.01%.

| Field | File | Role | Fill % | Notes |
|---|---|---|---|---|
| `MDR_REPORT_KEY` | all | key | 100 | |
| `REPORT_NUMBER`, `MDR_TEXT_KEY` | master, text | key | 100 | |
| `FOI_TEXT` | text | **text** | 100 | concatenate all text rows of a report (16.1M rows for 6.83M reports) |
| `TEXT_TYPE_CODE` | text | key | 100 | `D` event description 48%, `N` manufacturer narrative 52% |
| `DATE_RECEIVED` | master | filter (core) | 100 | MM/DD/YYYY; time axis |
| `DEVICE_REPORT_PRODUCT_CODE` | device | filter (core) | 100 | the 12 codes; QBJ 1.81M, FRN 1.49M, QFG 1.02M, OZP 0.81M rows |
| `MANUFACTURER_D_NAME` | device | filter (core) | 100 | 1,031 values |
| `BRAND_NAME` | device | filter (core) | 100 | 6,934 values |
| `GENERIC_NAME`, `MODEL_NUMBER` | device | filter (optional) | 91–100 | |
| `DATE_OF_EVENT` | master | filter (optional) | 87.1 | when the event happened (vs received) |
| `REPORT_SOURCE_CODE` | master | filter (optional) | 100 | `M` manufacturer 99.7% |
| `PATIENT_AGE`, `PATIENT_SEX` | patient | filter (optional) | 70–74 | free-form age (`49 YR`); sex often `Unknown` |
| `EVENT_TYPE` | master | **hidden (core)** | 100 | D / IN / M / O |
| `DEVICE_PROBLEM_CODE` | foidevproblem | **hidden (core)** | 100 | 514 codes in subset; terms in `deviceproblemcodes2025.csv` |
| `PROBLEM_CODE` (patient) | patientproblemcode | **hidden (core)** | 100 | 681 codes in subset; terms in `patientproblemcode.csv` |
| `ADVERSE_EVENT_FLAG` | master | hidden (leak) | 99.9 | `Y` ⇒ `EVENT_TYPE` ∈ {IN, D} in 96.3% (n = 519,750); `N` ⇒ 0.9% |
| `PRODUCT_PROBLEM_FLAG` | master | hidden (leak) | 100 | `N` ⇒ `EVENT_TYPE` ∈ {IN, D} in 93.7% (n = 339,821) |
| `SEQUENCE_NUMBER_OUTCOME` | patient | hidden (leak) | 7.5 | patient outcome codes (death, life-threatening, hospitalised, …) |
| `SEQUENCE_NUMBER_TREATMENT` | patient | hidden (leak) | 9.1 | treatment given |
| `REMEDIAL_ACTION`, `REMOVAL_CORRECTION_NUMBER` | master | excluded | 21 | recall / correction codes; possible source for change-point dates (STATE.md M2 follow-up) |
| `SUMMARY_REPORT`, `NOE_SUMMARIZED` | master | excluded | 100 | 496 summary reports that bundle several events; dropped in v1 (M6) |
| `MANUFACTURER_CONTACT_*` (19 fields) | master | excluded | | names, phone numbers, addresses of manufacturer staff |
| `MANUFACTURER_G1_*`, `MANUFACTURER_D_ADDRESS*`, `…_CITY`, `…_ZIP*`, `…_COUNTRY_CODE` | master, device | excluded | | addresses |
| `DISTRIBUTOR_*`, `MANUFACTURER_NAME/ADDRESS…` (master), `EVENT_KEY`, `NUMBER_*_IN_EVENT`, `DEVICE_EVENT_KEY`, `IMPLANT_FLAG`, `DATE_REMOVED_FLAG`, `DATE_REPORT` (text) | | excluded | 0 | empty in this subset |
| Report admin: `TYPE_OF_REPORT`, `MFR_REPORT_TYPE`, `SOURCE_TYPE`, `DATE_ADDED`, `DATE_CHANGED`, `SUPPL_DATES_*`, `DATE_REPORT`, `DATE_MANUFACTURER_RECEIVED`, `REPORTER_*`, `HEALTH_PROFESSIONAL`, `INITIAL_REPORT_TO_FDA`, `REPORT_TO_FDA`, `EVENT_LOCATION`, `PMA_PMN_NUM`, … | master | excluded | | |
| Device admin: `LOT_NUMBER`, `CATALOG_NUMBER`, `UDI-*`, `DEVICE_AVAILABILITY`, `DEVICE_EVALUATED_BY_MANUFACTUR`, `DATE_RETURNED_TO_MANUFACTURER`, `EXPIRATION_DATE_OF_DEVICE`, `DEVICE_AGE_TEXT`, `IMPLANT_DATE_YEAR`, `DATE_REMOVED_YEAR`, `DEVICE_OPERATOR`, `COMBINATION_PRODUCT_FLAG`, `SERVICED_BY_3RD_PARTY_FLAG` | device | excluded | | |
| Patient admin: `PATIENT_WEIGHT`, `PATIENT_ETHNICITY`, `PATIENT_RACE`, sequence numbers, `DATE_ADDED/CHANGED` | patient, patientproblem | excluded | | |

**Leakage notes**

- `ADVERSE_EVENT_FLAG` and `PRODUCT_PROBLEM_FLAG` are close to a copy of `EVENT_TYPE`, so they are hidden.
- **Coded fields inside the text.** In 59,955 reports (0.88%), `FOI_TEXT` contains a table of coded fields
  ("Device Problem Code", "Health Effect …", "Type of Reportable Event", IMDRF codes). 98% of these rows are
  manufacturer narratives (`N`). Proposed: strip these blocks from the text before extraction, or drop those reports
  from the evaluation set (STATE.md M5).
- The manufacturer narrative (`N`) often states the investigation result in words ("the pump was found to have …").
  That is free text the method is allowed to read; it is not removed.

---

## VAERS

- **Source:** yearly domestic files 2019, 2021, 2022, 2023 (`data/vaers/raw/`). CSV, latin-1.
- **Unit:** one primary report = rows with `ORDER = 1` (STATE.md V1). 1,154,318 reports.
- **Files:** `VAERSDATA` (one row per report), `VAERSSYMPTOMS` (MedDRA terms, 5 per row, several rows per report),
  `VAERSVAX` (one row per vaccine given). All join on `(VAERS_ID, ORDER)`.
- Flags (`DIED`, `HOSPITAL`, …) are `Y` or empty. Empty means "not reported", not "no".

| Field | File | Role | Fill % | Notes |
|---|---|---|---|---|
| `VAERS_ID` | all | key | 100 | |
| `ORDER` | all | key | 100 | keep `1` only |
| `SYMPTOM_TEXT` | DATA | **text** | 100 | free-text description of the event |
| `RECVDATE` | DATA | filter (core) | 100 | MM/DD/YYYY; time axis |
| `STATE` | DATA | filter (core) | 83.4 | 82 codes, includes non-US entries |
| `AGE_YRS` | DATA | filter (core) | 87.3 | |
| `SEX` | DATA | filter (core) | 100 | F / M / U |
| `VAX_TYPE` | VAX | filter (core) | 100 | 84 types (COVID19, FLU4, VARZOS, …) |
| `VAX_MANU` | VAX | filter (optional) | 100 | 30 manufacturers |
| `VAX_DOSE_SERIES` | VAX | filter (optional) | 100 | 1, 2, 3, …, UNK |
| `VAX_DATE`, `ONSET_DATE`, `NUMDAYS` | DATA | filter (optional) | 85–91 | vaccination date, onset date, days between |
| `DIED` | DATA | **hidden (core)** | 1.7 | |
| `HOSPITAL` | DATA | **hidden (core)** | 8.1 | |
| `ER_ED_VISIT` | DATA | **hidden (core)** | 11.1 | |
| `SYMPTOM1`–`SYMPTOM5` | SYMPTOMS | **hidden (core)** | 32–100 | MedDRA Preferred Terms; 9,380 distinct in `SYMPTOM1` |
| `SYMPTOMVERSION1`–`5` | SYMPTOMS | hidden | 32–100 | MedDRA version (15 values, 23.1–26.x) |
| `DATEDIED` | DATA | hidden (leak) | 1.5 | filled ⇒ `DIED = Y` in 100% of 16,970 |
| `HOSPDAYS` | DATA | hidden (leak) | 4.8 | filled ⇒ `HOSPITAL = Y` in 100% of 55,000 |
| `X_STAY` | DATA | hidden (leak) | 0.1 | prolonged hospital stay |
| `L_THREAT` | DATA | hidden (leak) | 1.4 | life-threatening; ⇒ `HOSPITAL = Y` in 72% |
| `DISABLE`, `BIRTH_DEFECT`, `OFC_VISIT`, `ER_VISIT` | DATA | hidden (leak) | 0–19.6 | other outcome flags (`ER_VISIT` is the old form's field) |
| `RECOVD` | DATA | hidden (leak) | 87.8 | recovered Y / N / U |
| `CAGE_YR`, `CAGE_MO` | DATA | excluded | | age computed by VAERS; redundant with `AGE_YRS` |
| `RPT_DATE`, `TODAYS_DATE`, `FORM_VERS`, `SPLTTYPE` | DATA | excluded | | form metadata; `SPLTTYPE` is a manufacturer report ID |
| `V_ADMINBY`, `V_FUNDBY` | DATA | excluded | | |
| `LAB_DATA`, `OTHER_MEDS`, `CUR_ILL`, `HISTORY`, `PRIOR_VAX`, `ALLERGIES` | DATA | excluded | 5–56 | other free text; not part of the event description |
| `VAX_LOT`, `VAX_ROUTE`, `VAX_SITE`, `VAX_NAME` | VAX | excluded | | `VAX_NAME` is a longer form of `VAX_TYPE` |

**Leakage notes**

- The outcome dates and durations reveal the outcome flags exactly (`DATEDIED`, `HOSPDAYS`), so they are hidden.
- `SYMPTOM_TEXT` often states the outcome itself: when it mentions death, `DIED = Y` in 77% (n = 17,314); when it
  says hospitalised/admitted, `HOSPITAL = Y` in 84% (n = 40,955). This is the signal the method should extract,
  not a leak.

---

## ASRS

- **Source:** ASRS Database Online CSV exports, one per incident year 2018–2023 (`data/asrs/raw/ASRS_YYYY.csv`).
  Two header rows (group, field); flattened here as `Group|Field`.
- **Unit:** one report = one `ACN`. 31,680 reports. Year = incident month `Time|Date`; drop the two ACNs dated
  2002 and 2012 (STATE.md A3).
- Multi-valued coded fields are `;`-separated (e.g. `Events|Anomaly`).

| Field | Role | Fill % | Notes |
|---|---|---|---|
| `ACN` | key | 100 | |
| `Report 1|Narrative` | **text** | 100 | reporter's own account |
| `Report 2|Narrative` | **text** | 20.6 | second reporter on the same event (e.g. other pilot) |
| `Time|Date` | filter (core) | 100 | YYYYMM; time axis (month resolution only) |
| `Place|State Reference` | filter (core) | 91.1 | 68 values, includes `US` and foreign codes |
| `Aircraft 1|Make Model Name` | filter (core) | 99.8 | 535 values |
| `Aircraft 1|Flight Phase` | filter (core) | 96.1 | multi-valued (364 combinations) |
| `Aircraft 1|Aircraft Operator` | filter (optional) | 93.5 | Air Carrier, Personal, Military, … |
| `Aircraft 1|Operating Under FAR Part` | filter (optional) | 93.8 | Part 121, Part 91, … |
| `Aircraft 1|Flight Plan`, `Aircraft 1|Mission` | filter (optional) | 88–89 | |
| `Time|Local Time Of Day` | filter (optional) | 86.5 | 6-hour bins |
| `Environment|Flight Conditions`, `Environment|Light` | filter (optional) | 52–57 | VMC/IMC; daylight/night |
| `Person 1|Reporter Organization`, `Person 1|Function` | filter (optional) | 96–99 | who reported (pilot, controller, …) |
| `Events|Anomaly` | **hidden (core)** | 100 | 6,229 distinct combinations; taxonomy in `docs/ASRS_CodingTaxonomy.pdf` |
| `Assessments|Primary Problem` | **hidden (core)** | 99.7 | 18 values (Human Factors, Aircraft, Procedure, …) |
| `Report 1|Synopsis` | hidden (leak, proposed) | 100 | written by ASRS analysts; see leakage notes |
| `Report 1|Callback`, `Report 2|Callback` | hidden (leak) | 0–1.5 | analyst's notes from a follow-up call |
| `Events|Result`, `Events|Detector`, `Events|When Detected`, `Events|Miss Distance`, `Events|Were Passengers Involved In Event` | hidden (leak) | 9–97 | analyst-coded event fields |
| `Assessments|Contributing Factors / Situations` | hidden (leak) | 99.7 | analyst-coded |
| `Person 1|Human Factors`, `Person 2|Human Factors`, `Person 1/2|Communication Breakdown` | hidden (leak) | 6–79 | analyst-coded |
| `Component|Aircraft Component`, `Component|Problem` | hidden (leak) | 37 | e.g. "Malfunctioning"; overlaps the equipment anomalies |
| Other `Place|…`, `Environment|…`, `Aircraft 1|…`, `Aircraft 2|…` fields | excluded | | geometry, airspace, maintenance status, cabin, crew counts |
| `…(UAS)` fields (24) | excluded | < 1 | drone-specific |
| `Person 1/2|…` other fields, `Person 1/2|ASRS Report Number.Accession Number` | excluded | | location, qualification, experience; per-reporter IDs |

**Leakage notes**

- The Synopsis uses the taxonomy's own words. For reports coded `Conflict NMAC`, the Synopsis contains "NMAC" or
  "near mid-air" in 74% of cases, the narrative in 5%; a Synopsis with that phrase is an NMAC report 98% of the time.
  For runway incursions, the Synopsis says "incursion" in 26% vs 17% for the narrative.
  So the method sees only the narratives; the Synopsis is hidden (STATE.md A4, proposed).
- All `Events|…`, `Assessments|…` and `… Human Factors` fields are coded by analysts after reading the report, so
  they are treated like the targets.
