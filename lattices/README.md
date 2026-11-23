# Concept lattices

Concept hierarchies for STUDENT_START task 4, built by `scripts/build_hierarchies.py` (last built 2026-11-19).
VAERS is not here yet (decision V4 in STATE.md).

Each hierarchy is a tree with one top node `TOP`. A tree with a top is a join-semilattice: the join of two concepts is
their lowest common ancestor, which is what roll-up and the child ≤ parent reconciliation constraints in ALGEBRA.md
need. (Meets of siblings would need an added bottom ⊥; nothing uses them yet.)

These files are public: the method may know the taxonomy. They are built only from public sources (FDA code lists,
IMDRF annexes, the ASRS coding form). Which report has which concept is ground truth and lives in `data/<ds>/hidden/`,
together with per-node report counts (`lattice_<name>_support.csv`), which would reveal true answers.

## Files

| File | Columns | Meaning |
|---|---|---|
| `<name>/edges.csv` | `child, parent` | the (child, parent) pairs; one parent per node |
| `<name>/nodes.csv` | `node_id, label, level, source, status` | level 0 = `TOP`; `status` from IMDRF (e.g. `Retired (2025)`, `Not selectable`) |
| `<name>/mapping.csv` | MAUDE: `fda_code, fda_term, node_id, method, proposed_node`; ASRS: `raw_value, node_id, method` | how values in the data map to nodes |
| `<name>/checks.json` | | unique ids, single top, one parent each, no cycles, child level = parent level + 1 |
| `maude_patient/edges_secondary.csv` | `child, parent` | IMDRF secondary placements (202 edges); **not** part of the tree (see below) |
| `crosswalk_fda_imdrf.csv` | `lattice, fda_code, fda_term, target_node, target_label, status, confidence, rationale` | manual map of FDA legacy codes to IMDRF; only `status = approved` is applied |

## Lattices

| Name | Source | Nodes | Structure | Data rows in IMDRF tree |
|---|---|---|---|---|
| `maude_device` | IMDRF Annex A *Medical Device Problem*, release 2026 | 882 = 491 IMDRF + 389 FDA legacy leaves + `UNMAPPED` + `TOP` | 27 level-1 groups, 3 levels | 99.71% (99.84% with proposed crosswalk) |
| `maude_patient` | IMDRF Annex E *Health Effects – Clinical Signs, Symptoms and Conditions*, release 2026 | 1,181 = 812 IMDRF + 366 FDA legacy leaves + `UNMAPPED` + `NO_EFFECT` + `TOP` | 24 level-1 groups (E01–E18 body systems; E19–E24 infections, injury, procedural, investigations, generalized, other), 3 levels | 99.75% (99.89%) |
| `asrs_anomaly` | ASRS Coding Form, April 2024 (`data/asrs/docs/ASRS_CodingTaxonomy.pdf` p.13) | 83 | 15 categories → 65 subcategories; Ground Conflict → Critical / Less Severe; 66 leaves | all 31,673 reports with an anomaly (7 reports have none) |

`maude_device` is the main MAUDE lattice. Example chains: `Failure to Infuse (A140802) ≤ No Flow (A1408) ≤ Infusion or
Flow Problem (A14) ≤ TOP`; `Gas/Air Leak (A050402) ≤ Leak/Splash (A0504) ≤ Mechanical Problem (A05) ≤ TOP`;
`Runway ≤ Ground Incursion ≤ TOP`. Note: in IMDRF, occlusion/obstruction sits under A14 *Infusion or Flow Problem*,
not under *Mechanical* as in ALGEBRA.md's toy lattice.

## Rules

**MAUDE — structure**

- Parents come from IMDRF's `CodeHierarchy` column (primary placement), not from the code prefix. They agree for all
  codes except `E1707` *Impaired Healing*, which IMDRF places under `E23` *Generalized Disorders*.
- **Poly-hierarchy.** Annex E puts 200 terms under a second level-1 group too (e.g. *Concussion* is under Nervous
  System and also under *Injury*). The tree keeps only the primary placement (the group named in *Primary Category*;
  level-3 terms follow their parent). Secondary placements are in `edges_secondary.csv`. Consequence: `↓E20 Injury` in the
  tree misses terms whose primary group is a body system. Whether to use the DAG is open (STATE.md L7).
- **Internal nodes have their own reports.** Many FDA codes map to a level-1 or level-2 IMDRF code (e.g. `A0401`
  *Break*). 91 device and 65 patient internal nodes have reports coded directly to them, so a parent's count is not the
  sum of its children: reconciliation must include the parent's own term (ALGEBRA.md §5, `x[ℓ-own]`).
- **Multi-valued reports.** A report can have several codes (16% of device reports, 3% patient, 83% of ASRS reports),
  so sibling counts overlap; roll-ups count distinct reports.
- All taxonomy nodes are kept, including codes no report uses and IMDRF codes marked retired or *Not selectable*
  (historical reports still use them).

**MAUDE — mapping FDA codes to nodes** (`method` in `mapping.csv`, in this order)

1. `fda_imdrf_code`: FDA gives the IMDRF code (1:1; all exist in release 2026).
2. `manual_crosswalk`: approved row in `crosswalk_fda_imdrf.csv` (so far only generic "Other / Unknown / No information"
   codes → `A26`, `A27`, `E2401`, `E2402`, `NO_EFFECT`).
3. `name_match`: exact case-insensitive name match to an IMDRF term (3 device, 11 patient codes).
4. `no_effect_rule` (patient): "No Consequences Or Impact To Patient", "No Known Impact…", "No Patient Involvement" →
   `NO_EFFECT` under IMDRF `E24`, which also holds `E2403` *No Clinical Signs* and `E2401` *Insufficient Information*.
   **Real health effects are `E01`–`E23`.**
5. `unmapped_fda_leaf`: own leaf (`FDA-DEV:<code>` / `FDA-PAT:<code>`) under `UNMAPPED`, so no report is lost.

The legacy codes are almost all in early years, so IMDRF-node trends have a jump if they are not mapped: unmapped share of
device rows is 4.98% in 2018 and 0% from 2019; of patient rows 1.49% / 1.29% / 0.84% in 2018–2020 and ~0% after.
The crosswalk's **proposed** rows (35, awaiting sign-off) would cut 2018 device to 2.74% and patient 2018 to 0.67%;
the rest are vague codes with no IMDRF target (e.g. *Device Operates Differently Than Expected*, *Device Inoperable*,
*Death*). `mapping.csv` column `proposed_node` shows where each would go.

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
