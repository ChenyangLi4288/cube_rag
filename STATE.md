# Project state

Decisions and status for the data work (STUDENT_START.md, tasks 2–5). Newest first within each section.
Status values: **decided** (follow it), **proposed** (default in use, needs Chenyang), **open** (not decided).

## Data on disk

All raw data is under `data/` (gitignored). Each dataset has a `MANIFEST.json` with source URL, date, sha256 and row counts.

| Dataset | Location | Years | How obtained | Manifest |
|---|---|---|---|---|
| MAUDE | `data/maude/raw/` (5.0 GB, 22 zips) | 2018–2025 received | `scripts/download_maude.py` (FDA bulk files) | `data/maude/MANIFEST.json` |
| VAERS | `data/vaers/raw/` (4 zips) | 2019, 2021, 2022, 2023 | Manual, vaers.hhs.gov/data/datasets.html (CAPTCHA) | `data/vaers/MANIFEST.json` (`scripts/make_manifest.py`) |
| ASRS | `data/asrs/raw/` (6 CSVs, `ASRS_YYYY.csv`) | 2018–2023 incident date | Manual CSV export, ASRS Database Online, one per year (cap 10,000/export) | `data/asrs/MANIFEST.json` (`make_manifest.py --header-rows 2`) |

**Processed tables (v0-draft, 2026-11-19):** `scripts/build_tables.py` reads the raw files (never modifies them) and
writes `data/<ds>/processed/` (key + text + filters, what the method may read) and `data/<ds>/hidden/` (ground truth,
separate folder). Open decisions are flag columns, not applied; only VAERS V1 is applied. Layout and table list in
`data/README.md`. Becomes v1 when the open decisions are signed off and the data is frozen.
Build checks (in each `PROCESSED_MANIFEST.json`): MAUDE 6,829,664 reports, raw rows parsed = manifest line counts
except `device2023` (2 lines skipped as malformed); 1 report has no master row, 184 have no text. VAERS 1,154,318
reports, 6 without MedDRA terms. ASRS 31,680 reports.
Cost note: 51% of MAUDE event descriptions are exact duplicates (templated manufacturer text, e.g. "signal loss over
one hour"), so extraction should be cached by text hash — roughly halves LLM calls.

Reference docs: `data/asrs/docs/` (ASRS coding taxonomy, abbreviations), `data/vaers/docs/` (VAERS Data Use Guide, March 2025),
`data/maude/product_code_counts.tsv` (openFDA counts per product code and year, 2026-11-19).

## Decisions

### MAUDE

- **M1. Raw download covers all codes, 2018–2025.** *decided, 2026-11-19.* FDA bulk files (master `mdrfoiThru2025`, yearly
  `device`/`foitext`, device and patient problem codes). Filtering to product codes happens after download, so code choice stays open.
  2026 (partial year) is not included.
- **M2. Candidate product codes.** *proposed, 2026-11-19.* From openFDA counts:
  infusion FRN; insulin pumps LZG, QFG, OYC, OZP, OZO; CGM MDS, PQF, QBJ, QLG; ICD LWS (non-CRT), NIK (CRT-D).
  Together they are far above the ~10⁶ reports in EXPERIMENTS.md (e.g. QBJ ≈ 380k in 2025 alone; FRN has an 888k spike in 2022).
  **Needs Chenyang:** final codes and years.
- **M3. No external exposure for MAUDE.** *decided (STUDENT_START §7.3).* Second measure = share of all reports for the same product code.
- **M4. Field roles:** see `data/README.md`. Hidden: `EVENT_TYPE`, device and patient problem codes, plus leak fields
  `ADVERSE_EVENT_FLAG`, `PRODUCT_PROBLEM_FLAG` (≈ copies of `EVENT_TYPE`: AEF=Y ⇒ IN/D in 96.3%), patient outcome and
  treatment. *proposed, 2026-11-19.*
- **M5. Coded fields embedded in text.** 59,955 of 6.83M candidate reports (0.88%) have `FOI_TEXT` with a table of
  coded fields (Device Problem Code, Health Effect, IMDRF), almost all in manufacturer narratives. Proposed: strip those
  blocks before extraction, or drop those reports from evaluation. *open.*
- **M6. Summary reports.** 496 reports have `SUMMARY_REPORT = Y` and bundle several events (`NOE_SUMMARIZED`). Drop, or
  count with weight. *open.*
- **Not done:** recall / safety-notice dates for the chosen codes (change-points, STUDENT_START §7.2).

### VAERS

- **V1. Unit = primary report: keep `ORDER = 1` rows only.** *proposed, 2026-11-19.*
  - Since May 2025 the VAERS files also contain "secondary reports" (`ORDER ≥ 2`). VAERS says they are "related to already
    reported events and do not represent additional reports of adverse events" (vaers.hhs.gov/data/datasets.html).
    `ORDER` is not described in the Data Use Guide (March 2025).
  - Checked on our files: under this rule every `VAERS_ID` occurs once across all four years; SYMPTOMS and VAX join to
    DATA on `(VAERS_ID, ORDER)` with no orphans.
  - Year files also hold secondary rows for reports first received in other years (e.g. 1,668 IDs in the 2022 file whose
    primary is in 2021). The rule drops them, so each report is counted in the year of its primary `RECVDATE`.
  - Text, filters and hidden labels all come from the primary row, so the labels describe the same report as the text.
    (Secondary rows differ: text 90%, MedDRA PT set ~85–93%, `DIED` 1%, `HOSPITAL` 6% of multi-row IDs.)
  - Counts after the rule: 2019 48,436 · 2021 752,972 · 2022 246,787 · 2023 106,123.
  - **Needs Chenyang:** agree to primary-only; alternative is hidden labels = OR over all orders.
- **V2. Domestic only:** use the yearly files, not `NonDomesticVAERSData.zip`. *decided.*
- **V3. Field roles:** see `data/README.md`. Hidden: `DIED`, `HOSPITAL`, `ER_ED_VISIT`, MedDRA `SYMPTOM1–5`, plus leak
  fields `DATEDIED` (filled ⇒ DIED=Y 100%), `HOSPDAYS` (filled ⇒ HOSPITAL=Y 100%), `X_STAY`, `L_THREAT`, `DISABLE`,
  `BIRTH_DEFECT`, `OFC_VISIT`, `ER_VISIT`, `RECOVD`. Text = `SYMPTOM_TEXT` only. *proposed, 2026-11-19.*
- **V4. Hierarchy: MedDRA, fallback symptom clusters.** *open, licence requested 2026-11-19.*
  - Licence requested 2026-11-19 (after the Nov 2 deadline), awaiting MSSO. Per STUDENT_START §7.1, build clusters of
    symptom terms now; switch to MedDRA if the licence arrives in time.
  - MedDRA is free for educational institutions ("Non-Profit / Non-Commercial" subscription, form at
    meddra.org/subscription/subscription-form; needs a link or signed statement proving non-profit status).
  - Terms: the subscriber "shall not … publish, or otherwise distribute MedDRA Terminology to a third party" → never put
    hierarchy files in the repo or benchmark; ship a build script only.
  - Terms in the data span MedDRA versions 23.1–26.0; any PT→HLT→SOC mapping must handle that.
  - **Fallback clustering, method not decided** (decide later with Chenyang). The repo fixes only: cluster the VAERS
    `SYMPTOM1–5` terms (public), output (child, parent) pairs with a top node (task 4). Proposed default: embed each
    term (optionally plus report co-occurrence), hierarchical clustering cut at two levels (term → group → top group;
    ~27 top groups to mirror the 27 MedDRA SOCs), fixed embedding model version and seed recorded in the manifest.
  - Caveat: EXPERIMENTS X5 uses "clusters from embeddings" as the *alternative* lattice. If clusters become the main
    VAERS lattice, X5 has no contrast for VAERS (still valid for MAUDE/ASRS, or VAERS once MedDRA arrives).

### ASRS

- **A1. ASRS = NASA Aviation Safety Reporting System**, 2018–2023, used only for the exposure case study (PROPOSAL.md).
- **A2. Download done, 2026-11-19.** Query "Date of Incident between January-YYYY and December-YYYY", CSV export, one
  file per year (export cap is 10,000 reports). Site total for 2018-01..2023-12 = 31,680 ACNs = sum of the six files;
  no duplicate ACNs; no empty narratives. Per file: 2018 5,660 · 2019 6,427 · 2020 4,992 · 2021 4,563 · 2022 5,452 · 2023 4,586.
  CSV has two header rows (group, field) and 125 fields, including UAS-specific fields; flatten as `Group|Field`.
- **A3. Report year = incident month (`Time|Date`, YYYYMM).** *proposed.* A few rows fall outside the queried year
  (ASRS filter behaviour): by incident year the unique ACNs are 2018 5,660 · 2019 6,427 · 2020 4,982 · 2021 4,571 ·
  2022 5,451 · 2023 4,587, plus 2 outliers dated 2002 and 2012 → drop those two.
- **A4. Fields.** Text: `Report 1|Narrative`, `Report 2|Narrative` (second reporter, often empty), `Report 1|Synopsis`.
  Filter: `Time|Date`, `Place|State Reference`, `Aircraft 1|Make Model Name`, `Aircraft 1|Flight Phase`.
  Hidden: `Events|Anomaly`, `Assessments|Primary Problem` (also `Events|Result`, contributing factors).
  Synopsis is written by ASRS analysts and leaks the taxonomy: for `Conflict NMAC` reports it says "NMAC/near mid-air"
  in 74% vs 5% for the narrative. Proposed: Synopsis and Callbacks hidden; all analyst-coded `Events|…`,
  `Assessments|…`, `Human Factors`, `Component|…` fields hidden too. Details in `data/README.md`.

### Method (from STUDENT_START §7.4)

- **Boolean predicates:** exact formulas from ALGEBRA.md §2 (facts independent, no independence between predicates),
  audit-set correction of the combined cell, Gaussian copula only as ablation, Fréchet–Hoeffding bounds as a check.

## Open items

1. Chenyang: final MAUDE codes/years (M2), VAERS primary-only rule (V1), MedDRA vs clusters (V4), ASRS year rule and
   Synopsis visibility (A3, A4).
2. ~~ASRS export and manifest~~ done 2026-11-19.
3. ~~Field tables (task 3)~~ done 2026-11-19: `data/README.md` (`.gitignore` now `data/*` + `!data/README.md`).
   Per-column profiles: `scripts/profile_fields.py` → `data/<ds>/field_profile.csv`, `leakage_checks.json`.
   Chenyang to confirm the leak-field roles (M4–M6, V3, A4).
4. Exposure data (task 5): CDC doses (VAERS), FAA/BTS flight operations (ASRS).
5. Concept hierarchies (task 4).
