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

**Processed tables v1 (2026-11-23, issue #2):** `scripts/build_tables.py` reads the raw files (never modifies them) and
writes `data/<ds>/processed/` (key + text + filters, what the method may read) and `data/<ds>/hidden/` (ground truth).
All 2026-11-20 decisions are applied; rules, counts and checks are in each `PROCESSED_MANIFEST.json` (version `v1`).
- MAUDE 1,000,054 reports: 6,829,664 candidates − 496 summary reports (M6) − 1 without a master row, then sampled (M2,
  seed 20261120): LWS 171,966, QLG 145,061, NIK 80,610, MDS 44,087 whole; the other 8 codes at rate 0.087402 each.
  M5: 3,776 reports had code blocks stripped; 0 reports still contain one of their own hidden codes (build-time check).
  Event types M 783,561 · IN 212,661 · D 3,771 · O 30 · missing 31. 34 reports have no text.
- VAERS 1,154,318 primary reports; sensitivity labels `<flag>_any_order` (e.g. died 19,257 primary vs 19,534 any row).
- ASRS 31,678 reports (2 outliers dropped; 12 moved to their incident year).
Note: the manifests show git commit `bf776f8+uncommitted-script`; the script was committed right after the build
without further changes.
Cost note: 51% of MAUDE event descriptions are exact duplicates (templated manufacturer text, e.g. "signal loss over
one hour"), so extraction should be cached by text hash — roughly halves LLM calls.

Reference docs: `data/asrs/docs/` (ASRS coding taxonomy, abbreviations), `data/vaers/docs/` (VAERS Data Use Guide, March 2025),
`data/maude/product_code_counts.tsv` (openFDA counts per product code and year, 2026-11-19).

## Decisions

### Meeting 2026-11-20 (Chenyang) — summary

Decided by Chenyang on 2026-11-20. Open work is now tracked in GitHub Issues (#1–#14); the data issues are #1 (push and
merge), #2 (apply decisions and freeze v1), #3 (VAERS lattice) and #6 (crosswalk).

| ID | Decision | Issue |
|---|---|---|
| M2 | All 4 device groups, 2018–2025; one fixed sampling rate per product code, the same every year, to ~10⁶ reports in total; LWS and NIK kept whole; no per-year cap; rates and seed in the manifest | #2 |
| V1 | `ORDER = 1` only, everything from that row; "true if any row says so" kept as a sensitivity check | #2 |
| V3 / M4 / A4 | Leak fields hidden, as proposed | #2 |
| M5 | Strip the embedded code block, keep `has_embedded_codes`, test that no code terms survive | #2 |
| M6 | Drop the 496 summary reports; record the count | #2 |
| A3 | Year = incident month; drop the 2 outliers | #2 |
| V4 | MedDRA as main VAERS lattice if licensed; build symptom clusters now either way (X5 alternative) | #3 |
| L7 | Hierarchies are DAGs: IMDRF secondary placements join the lattice; same for MedDRA | #2 |
| L8 | Apply high-confidence crosswalk rows only; run 2018–2020 trends with and without them | #6 |
| Tasks 6–7 | Toy cube done (ALGEBRA §9); task 6 replaced by a review of ALGEBRA §10–11 (#7) | — |

### Lattices (task 4)

- **L1. Storage:** `lattices/<name>/` at repo root, committed (small, public, part of the benchmark). Per-node report
  counts stay in `data/<ds>/hidden/` because they reveal true answers. *decided (user), 2026-11-19.*
- **L2. MAUDE = two lattices:** `maude_device` (IMDRF Annex A, main MAUDE lattice, matches the ALGEBRA toy) and
  `maude_patient` (IMDRF Annex E). *decided (user), 2026-11-19.*
- **L3. Legacy FDA codes without IMDRF code:** name match, else own leaf under `UNMAPPED`; no report dropped.
  *decided (user), 2026-11-19.*
- **L4. Built 2026-11-19, revised after independent review** (`scripts/build_hierarchies.py`, IMDRF release 2026 in
  `data/maude/docs/imdrf/` with MANIFEST): `maude_device` 882 nodes (99.71% rows in IMDRF tree), `maude_patient` 1,181
  (99.75%), `asrs_anomaly` 83 (v0 numbers; v1: L7, L8 and `lattices/README.md`). All pass checks. Review fixes applied: `.gitignore` exception for `lattices/**/*.csv`
  (they were ignored by `*.csv`); parents from IMDRF `CodeHierarchy` (fixes `E1707` → `E23`); labels from the primary
  row; ASRS taxonomy hard-coded from the coding form (no hidden data or write-in text in public files); generic
  Other/Unknown codes mapped to `A26/A27/E2401/E2402`; support files list every node; IMDRF provenance manifest; docs
  corrected. Details: `lattices/README.md`.
- **L5. Patient "no effect" codes** go under IMDRF `E24`; real health effects are `E01`–`E23`. Note `Death` (FDA 1802)
  has no IMDRF Annex E code (death is an Annex F health *impact*) and sits under `UNMAPPED`. *proposed.*
- **L7. Annex E poly-hierarchy: tree (primary placement) or DAG (+ `edges_secondary.csv`, 202 edges)?** Tree in use.
  With DAG, e.g. `↓E20 Injury` would add terms like Concussion and Burns (≈30k more reports than the 15.8k in the tree).
  Decide once together with MedDRA for VAERS (also multi-axial). **Decided 2026-11-20: DAG** (secondary placements
  become lattice edges; same for MedDRA; roll-up counts each report once, ALGEBRA §10 D4). *decided (Chenyang), #2.*
  **Implemented 2026-11-23:** `edges.csv` has a `placement` column (primary/secondary); `maude_patient` has 1,332
  edges (166 secondary, after dropping 36 that repeat a primary edge); `maude_device` and `asrs_anomaly` stay trees.
  `level` = depth along the primary path (IMDRF also places level-2 terms under level-2 terms, e.g. Headache ≤ Pain).
  `tests/test_lattices.py` loads every lattice into `cuberag.Lattice`.
- **L8. Crosswalk of FDA legacy codes → IMDRF** (`lattices/crosswalk_fda_imdrf.csv`): 7 approved (generic codes),
  35 proposed (e.g. Bent → A040609, Blood Loss → E0506, Shock, Insulin → E233602), 17 no target (e.g. Death,
  Device Inoperable). Proposed rows fix most of the 2018–2020 trend jump (2018 device unmapped 4.98% → 2.74%).
  **Decided 2026-11-20: apply high-confidence rows only** (22 of 35); medium rows and the 17 no-target codes stay under
  `UNMAPPED`; report 2018–2020 trends with and without the crosswalk. Chenyang does a first-pass review. *decided, #6.*
  **Applied 2026-11-23:** 22 rows set to `approved`. Unmapped share 2018/2019/2020 on v1: device 3.19%/0/0 (3.98%
  without crosswalk); patient 2.86%/2.37%/1.64% (4.70%/4.31%/6.75% without). Per-year, per-group comparison in
  `data/maude/hidden/crosswalk_trend_check.csv`; largest effect in patient E01 Nervous System (Seizures, Syncope).
- **L6b. Internal IMDRF nodes carry their own reports** (91 device, 65 patient), so reconciliation needs the
  parent's own term (ALGEBRA §5). Documented in `lattices/README.md`.
- **L6. ASRS Ground Conflict severity** (`Critical` / `Less Severe` exported as separate values) is a third level under
  Ground Conflict; checked on all 1,902 reports. *decided (data check).*
- **Open:** IMDRF reuse terms not verified (needed before public release). VAERS lattice waits for V4.
  For V4: IMDRF Annex E lists a MedDRA code for many terms — a possible public partial grouping for VAERS PTs.

### MAUDE

- **M1. Raw download covers all codes, 2018–2025.** *decided, 2026-11-19.* FDA bulk files (master `mdrfoiThru2025`, yearly
  `device`/`foitext`, device and patient problem codes). Filtering to product codes happens after download.
  2026 (partial year) is not included.
- **M2. Product codes and years.** *decided (Chenyang) 2026-11-20.* From openFDA counts:
  infusion FRN; insulin pumps LZG, QFG, OYC, OZP, OZO; CGM MDS, PQF, QBJ, QLG; ICD LWS (non-CRT), NIK (CRT-D).
  Together they are far above the ~10⁶ reports in EXPERIMENTS.md (e.g. QBJ ≈ 380k in 2025 alone; FRN has an 888k spike in 2022).
  **Decided 2026-11-20:** keep all 4 groups (all 12 codes), 2018–2025; downsample with one fixed rate per product code,
  the same in every year, to ~10⁶ reports in total; keep LWS and NIK whole; no per-year cap (it would flatten real
  spikes such as FRN 2022); record rates and seed in the manifest. *decided (Chenyang), #2.*
- **M3. No external exposure for MAUDE.** *decided (STUDENT_START §7.3).* Second measure = share of all reports for the same product code.
- **M4. Field roles:** see `data/README.md`. Hidden: `EVENT_TYPE`, device and patient problem codes, plus leak fields
  `ADVERSE_EVENT_FLAG`, `PRODUCT_PROBLEM_FLAG` (≈ copies of `EVENT_TYPE`: AEF=Y ⇒ IN/D in 96.3%), patient outcome and
  treatment. *decided (Chenyang) 2026-11-20, #2.*
- **M5. Coded fields embedded in text.** 59,955 of 6.83M candidate reports (0.88%) have `FOI_TEXT` with a table of
  coded fields (Device Problem Code, Health Effect, IMDRF), almost all in manufacturer narratives. Proposed: strip those
  blocks before extraction, or drop those reports from evaluation. **Decided 2026-11-20: strip**, keep the
  `has_embedded_codes` flag (drop-run = one filter), add a test that no code terms survive. *decided, #2.*
- **M6. Summary reports.** 496 reports have `SUMMARY_REPORT = Y` and bundle several events (`NOE_SUMMARIZED`). Drop, or
  count with weight. **Decided 2026-11-20: drop**, record the count. *decided, #2.*
- **Not done:** recall / safety-notice dates for the chosen codes (change-points, STUDENT_START §7.2).

### VAERS

- **V1. Unit = primary report: keep `ORDER = 1` rows only.** *decided (Chenyang) 2026-11-20, #2.* Sensitivity check:
  hidden labels = true if any row says so.
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
- **V2. Domestic only:** use the yearly files, not `NonDomesticVAERSData.zip`. *decided.*
- **V3. Field roles:** see `data/README.md`. Hidden: `DIED`, `HOSPITAL`, `ER_ED_VISIT`, MedDRA `SYMPTOM1–5`, plus leak
  fields `DATEDIED` (filled ⇒ DIED=Y 100%), `HOSPDAYS` (filled ⇒ HOSPITAL=Y 100%), `X_STAY`, `L_THREAT`, `DISABLE`,
  `BIRTH_DEFECT`, `OFC_VISIT`, `ER_VISIT`, `RECOVD`. Text = `SYMPTOM_TEXT` only. *decided (Chenyang) 2026-11-20.*
- **V4. Hierarchy: MedDRA (main) + symptom clusters (built either way).** *decided (Chenyang) 2026-11-20, #3.*
  Clusters are built now regardless, because X5 needs them as the alternative lattice. Open within V4: MedDRA
  version, and the AI-use restriction below.
  - 2026-11-20: MSSO replied that Columbia University already has an enterprise-wide MedDRA subscription; no separate
    licence needed. Credentials (MedDRA ID, password) come from the MSSO Self-Service Application
    (apps.meddra.org/selfservice) with a @columbia.edu address. So MedDRA can be the VAERS lattice; clusters are no
    longer needed as the fallback (they stay available as the X5 alternative lattice).
  - Still to check: that the Columbia subscription covers this research use, and which MedDRA version to download
    (data span 23.1–26.0).
  - **AI use (MSSO statement "AI Use and MedDRA Licensing Considerations", read 2026-11-20):** MedDRA must not be
    loaded into public AI tools; it may be used only in non-public, internally controlled AI tools of the subscribing
    organisation, with a data-processing agreement that forbids training on it and forbids passing it to unauthorised
    sub-processors. Consequences: (1) do not put MedDRA files or term lists into hosted LLM APIs or coding assistants
    (including Claude Code) unless Columbia confirms such a tool is authorised; (2) an extractor that sees MedDRA terms in
    its prompt must run on a Columbia-controlled model (e.g. local GPU); (3) validate any AI-produced MedDRA term against
    the licensed files. *open — ask Chenyang / Columbia DBMI.*
  - MedDRA is free for educational institutions ("Non-Profit / Non-Commercial" subscription, form at
    meddra.org/subscription/subscription-form; needs a link or signed statement proving non-profit status).
  - Terms: the subscriber "shall not … publish, or otherwise distribute MedDRA Terminology to a third party" → never put
    hierarchy files in the repo or benchmark; ship a build script only.
  - Terms in the data span MedDRA versions 23.1–26.0; any PT→HLT→SOC mapping must handle that.
  - **Clustering method** (issue #3 fixes: embed each term, hierarchical clustering cut at two levels, ~27 top
    groups, fixed model and seed).
  - **Clusters built 2026-11-23** (`scripts/build_vaers_clusters.py`): 13,268 distinct VAERS PTs embedded with
    `BAAI/bge-small-en-v1.5` (fastembed/ONNX, normalised), one Ward tree cut at 27 top and 300 mid groups (nested),
    i.e. PT ≤ mid ≤ top ≤ TOP; valid. Output kept local in `data/vaers/lattice_clusters/` (+ MANIFEST with model,
    versions and hashes) until Chenyang confirms the PT names may be committed (MedDRA terms of use). Per-node counts
    in `data/vaers/hidden/lattice_vaers_clusters_support.csv`. *open: commit or not.* The repo fixes only: cluster the VAERS
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
- **A3. Report year = incident month (`Time|Date`, YYYYMM).** *decided (Chenyang) 2026-11-20, #2.* A few rows fall outside the queried year
  (ASRS filter behaviour): by incident year the unique ACNs are 2018 5,660 · 2019 6,427 · 2020 4,982 · 2021 4,571 ·
  2022 5,451 · 2023 4,587, plus 2 outliers dated 2002 and 2012 → drop those two.
- **A4. Fields.** Text: `Report 1|Narrative`, `Report 2|Narrative` (second reporter, often empty), `Report 1|Synopsis`.
  Filter: `Time|Date`, `Place|State Reference`, `Aircraft 1|Make Model Name`, `Aircraft 1|Flight Phase`.
  Hidden: `Events|Anomaly`, `Assessments|Primary Problem` (also `Events|Result`, contributing factors).
  Synopsis is written by ASRS analysts and leaks the taxonomy: for `Conflict NMAC` reports it says "NMAC/near mid-air"
  in 74% vs 5% for the narrative. Proposed: Synopsis and Callbacks hidden; all analyst-coded `Events|…`,
  `Assessments|…`, `Human Factors`, `Component|…` fields hidden too. Details in `data/README.md`.
  *decided (Chenyang) 2026-11-20, #2.*

### Method (from STUDENT_START §7.4)

- **Boolean predicates:** exact formulas from ALGEBRA.md §2 (facts independent, no independence between predicates),
  audit-set correction of the combined cell, Gaussian copula only as ablation, Fréchet–Hoeffding bounds as a check.

## Open items

Open work is tracked in GitHub Issues; this list is kept for history.

0. Push `shubham/data-setup` and open a PR into `main` (#1). Write access granted 2026-11-20 and accepted.
1. ~~Chenyang decisions~~ done 2026-11-20 (summary table above). ~~Apply them and freeze v1 (#2)~~ v1 built
   2026-11-23 (PR from `shubham/data-setup`).
2. ~~ASRS export and manifest~~ done 2026-11-19.
3. ~~Field tables (task 3)~~ done 2026-11-19: `data/README.md` (`.gitignore` now `data/*` + `!data/README.md`).
   Per-column profiles: `scripts/profile_fields.py` → `data/<ds>/field_profile.csv`, `leakage_checks.json`.
   Chenyang to confirm the leak-field roles (M4–M6, V3, A4).
4. Exposure data (task 5): CDC doses (VAERS), FAA/BTS flight operations (ASRS).
5. Concept hierarchies (task 4): MAUDE and ASRS done 2026-11-19 (`lattices/`); switch to DAG (#2); VAERS (#3);
   crosswalk high-confidence rows (#6).
