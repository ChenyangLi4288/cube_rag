# Concept lattices

Concept hierarchies for STUDENT_START task 4, built by `scripts/build_hierarchies.py` (last built 2026-11-23 on the v1
data). VAERS lattices are not here: their nodes are MedDRA terms, which may not be redistributed, so only the build
scripts are committed and the files stay local (STATE.md V4/V5, issue #3). Main lattice: MedDRA 29.1,
`scripts/build_vaers_meddra.py` → `data/vaers/lattice_meddra/` (SOC ≤ HLGT ≤ HLT ≤ PT, DAG). X5 alternative: symptom
clusters, `scripts/build_vaers_clusters.py` → `data/vaers/lattice_clusters/`.

Each hierarchy is a finite partial order (a DAG of (child, parent) pairs) with one top node `TOP` (decision L7,
2026-11-20). A concept can have several parents when the source taxonomy places it in several groups (IMDRF Annex E:
*Headache* is under Nervous System and under *Pain*). ALGEBRA §10 (D4) allows this: `↓ℓ` is ℓ and all its descendants
over every parent, and roll-up counts each report once. `cuberag.Lattice` loads `edges.csv` directly
(`tests/test_lattices.py`).

These files are public: the method may know the taxonomy. They are built only from public sources (FDA code lists,
IMDRF annexes, the ASRS coding form). Which report has which concept is ground truth and lives in `data/<ds>/hidden/`,
together with per-node report counts (`lattice_<name>_support.csv`), which would reveal true answers.

## Files

| File | Columns | Meaning |
|---|---|---|
| `<name>/edges.csv` | `child, parent, placement` | the (child, parent) pairs; `placement` = `primary` (exactly one per node: the IMDRF primary placement) or `secondary` (IMDRF secondary placements) |
| `<name>/nodes.csv` | `node_id, label, level, source, status` | `level` = depth along the primary path (0 = `TOP`); `status` from IMDRF (e.g. `Retired (2025)`, `Not selectable`) |
| `<name>/mapping.csv` | MAUDE: `fda_code, fda_term, node_id, method, proposed_node`; ASRS: `raw_value, node_id, method` | how values in the data map to nodes |
| `<name>/checks.json` | | unique ids, single top, one primary parent each, no duplicate edges, no cycles, every node reaches `TOP`, primary child level = parent level + 1 |
| `crosswalk_fda_imdrf.csv` | `lattice, fda_code, fda_term, target_node, target_label, status, confidence, rationale` | manual map of FDA legacy codes to IMDRF; only `status = approved` is applied |

## Lattices

| Name | Source | Nodes | Structure | Data rows in IMDRF tree |
|---|---|---|---|---|
| `maude_device` | IMDRF Annex A *Medical Device Problem*, release 2026 | 874 = 491 IMDRF + 381 FDA legacy leaves + `UNMAPPED` + `TOP` | 27 level-1 groups, 3 levels; a tree (no secondary placements) | 99.78% (99.73% without the crosswalk) |
| `maude_patient` | IMDRF Annex E *Health Effects – Clinical Signs, Symptoms and Conditions*, release 2026 | 1,167 = 812 IMDRF + 352 FDA legacy leaves + `UNMAPPED` + `NO_EFFECT` + `TOP` | 24 level-1 groups (E01–E18 body systems; E19–E24 infections, injury, procedural, investigations, generalized, other), 3 levels; DAG: 1,332 edges, 166 secondary | 99.53% (98.76% without the crosswalk) |
| `asrs_anomaly` | ASRS Coding Form, April 2024 (`data/asrs/docs/ASRS_CodingTaxonomy.pdf` p.13) | 83 | 15 categories → 65 subcategories; Ground Conflict → Critical / Less Severe; 66 leaves | all 31,671 reports with an anomaly (7 reports have none) |

`maude_device` is the main MAUDE lattice. Example chains: `Failure to Infuse (A140802) ≤ No Flow (A1408) ≤ Infusion or
Flow Problem (A14) ≤ TOP`; `Gas/Air Leak (A050402) ≤ Leak/Splash (A0504) ≤ Mechanical Problem (A05) ≤ TOP`;
`Runway ≤ Ground Incursion ≤ TOP`. Note: in IMDRF, occlusion/obstruction sits under A14 *Infusion or Flow Problem*,
not under *Mechanical* as in ALGEBRA.md's toy lattice.

## Rules

**MAUDE — structure**

- Parents come from IMDRF's `CodeHierarchy` column (primary placement), not from the code prefix. They agree for all
  codes except `E1707` *Impaired Healing*, which IMDRF places under `E23` *Generalized Disorders*.
- **Poly-hierarchy (DAG).** Annex E places some terms in a second group too (e.g. *Concussion* under Nervous System
  and under *Injury*; *Headache* under Nervous System and under *Pain*). These secondary placements are edges with
  `placement = secondary`, so `↓E20 Injury` includes Concussion. Level-3 terms under a multi-placed level-2 term follow
  their parent. 36 of IMDRF's 202 secondary rows repeat an existing primary edge and are not duplicated. Annex A
  (devices) has no secondary placements, so `maude_device` is a tree.
- **Internal nodes have their own reports.** Many FDA codes map to a level-1 or level-2 IMDRF code (e.g. `A0401`
  *Break*). 87 device and 62 patient internal nodes have reports coded directly to them (v1 data), so a parent's count is not the
  sum of its children: reconciliation must include the parent's own term (ALGEBRA.md §5, `x[ℓ-own]`).
- **Multi-valued reports.** A report can have several codes (21% of device reports, 7% patient, 83% of ASRS reports),
  so sibling counts overlap; roll-ups count distinct reports.
- All taxonomy nodes are kept, including codes no report uses and IMDRF codes marked retired or *Not selectable*
  (historical reports still use them).

**MAUDE — mapping FDA codes to nodes** (`method` in `mapping.csv`, in this order)

1. `fda_imdrf_code`: FDA gives the IMDRF code (1:1; all exist in release 2026).
2. `manual_crosswalk`: approved row in `crosswalk_fda_imdrf.csv`: the 7 generic "Other / Unknown / No information"
   codes (→ `A26`, `A27`, `E2401`, `E2402`, `NO_EFFECT`) and, by decision L8 (2026-11-20), the 22 high-confidence
   mappings (8 device, 14 patient; e.g. Bent → `A040609`, Seizures → `E0109`). Chenyang does a first-pass review (#6).
3. `name_match`: exact case-insensitive name match to an IMDRF term (3 device, 11 patient codes).
4. `no_effect_rule` (patient): "No Consequences Or Impact To Patient", "No Known Impact…", "No Patient Involvement" →
   `NO_EFFECT` under IMDRF `E24`, which also holds `E2403` *No Clinical Signs* and `E2401` *Insufficient Information*.
   **Real health effects are `E01`–`E23`.**
5. `unmapped_fda_leaf`: own leaf (`FDA-DEV:<code>` / `FDA-PAT:<code>`) under `UNMAPPED`, so no report is lost.

The legacy codes are almost all in 2018–2020, so IMDRF-node trends jump if they are not mapped. On the v1 sample, the
unmapped share of rows by year (2018 / 2019 / 2020; ~0% from 2021):

| | with crosswalk (applied) | without crosswalk | if the 13 remaining medium-confidence rows were applied |
|---|---|---|---|
| device | 3.19% / 0% / 0% | 3.98% / 0% / 0% | 2.53% / 0% / 0% |
| patient | 2.86% / 2.37% / 1.64% | 4.70% / 4.31% / 6.75% | 2.29% / 1.86% / 1.26% |

Per decision L8, trend results for 2018–2020 are reported with and without the crosswalk; the per-year, per-group
comparison is in `data/maude/hidden/crosswalk_trend_check.csv` (hidden: it holds counts). The largest effect is in
patient groups such as E01 *Nervous System* (Seizures, Syncope). The 17 `no_target` codes stay under `UNMAPPED`
(e.g. *Device Operates Differently Than Expected*, *Device Inoperable*, *Death*); `mapping.csv` column
`proposed_node` previews the medium-confidence rows.

**ASRS**

- The taxonomy is hard-coded from the coding form (spelled as in the CSV export); the build fails on any anomaly value
  outside it.
- An anomaly value is `<category> <subcategory>`; the category is the longest matching category name.
- The export splits "Conflict Ground Conflict, Critical" into `Conflict Ground Conflict` followed by `Critical`
  (or `Less Severe`); checked on all 1,902 Ground Conflict reports in 2018–2023.
- `Other <free text>` write-ins → `Other / Write-in` (raw write-in text is not copied here).
- `data/asrs/hidden/anomaly_nodes.parquet` is the cleaned report → leaf table. `Primary Problem` (18 values) is a flat
  attribute, not part of this lattice.

## Sources and reuse

- IMDRF N43 annexes, release 2026: `data/maude/docs/imdrf/` with `MANIFEST.json` (URL, sha256). Reuse terms not
  verified yet — confirm before releasing the benchmark.
- FDA code lists (`data/maude/raw/*problemcode*`) and the ASRS taxonomy are US-government public material.
- MedDRA must never be added here (licence).

## Rebuild

`python scripts/build_hierarchies.py` (any working directory). The public files need only the raw code lists, the IMDRF
file and the crosswalk; the hidden-side files need `scripts/build_tables.py` to have run, and are lost when it reruns
(it wipes `hidden/`) — rerun this script after it.
