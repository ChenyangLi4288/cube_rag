"""Build concept hierarchies (STUDENT_START task 4) for MAUDE and ASRS.

Public outputs (committed; the method may know the taxonomy) — built only from public sources:
  lattices/<name>/nodes.csv            node_id, label, level (depth along the primary path), source, status
  lattices/<name>/edges.csv            child, parent, placement   <- the (child, parent) pairs of a DAG with top TOP
                                       (decision L7: IMDRF secondary placements are edges too; placement = primary
                                       for the one IMDRF primary parent, secondary otherwise)
  lattices/<name>/mapping.csv          value in the data -> node_id, method
  lattices/<name>/checks.json          structural checks
Inputs: FDA code lists (data/maude/raw), IMDRF 2026 annexes (data/maude/docs/imdrf), the ASRS coding form (hard-coded
below), and lattices/crosswalk_fda_imdrf.csv (manual FDA legacy code -> IMDRF; only status=approved is applied).

Hidden-side outputs (not committed — per-node counts would reveal true answers); need scripts/build_tables.py first:
  data/<ds>/hidden/lattice_<name>_support.csv    every node: n_reports_direct, n_reports_rollup (distinct reports in
                                                 ↓node over all parents; 0 if unused)
  data/<ds>/hidden/lattice_<name>_coverage.json  mapping coverage by year, with and without the manual crosswalk (L8)
  data/maude/hidden/crosswalk_trend_check.csv    reports per year and level-1 group, with and without the crosswalk
  data/asrs/hidden/anomaly_nodes.parquet         ACN -> leaf node

Usage (from anywhere): python scripts/build_hierarchies.py
"""

import json
import re
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "lattices"
IMDRF_XLSX = DATA / "maude/docs/imdrf/imdrf-tech-ae-terminologies-n43-ReleaseNumber2026-Annexes-revisedJune.xlsx"
CROSSWALK = OUT / "crosswalk_fda_imdrf.csv"
TOP = "TOP"


# ====================================================================== shared
def norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip().lower()


def parents_of(edges: pd.DataFrame) -> dict[str, set[str]]:
    par: dict[str, set[str]] = {}
    for c, p in zip(edges["child"], edges["parent"]):
        par.setdefault(c, set()).add(p)
    return par


def ancestors(edges: pd.DataFrame) -> dict[str, frozenset[str]]:
    """Node -> itself and all ancestors over every parent (raises on a cycle)."""
    par, memo, active = parents_of(edges), {}, set()

    def up(n):
        if n in memo:
            return memo[n]
        if n in active:
            raise ValueError(f"cycle through {n}")
        active.add(n)
        memo[n] = frozenset({n}).union(*(up(p) for p in par.get(n, ())))
        active.discard(n)
        return memo[n]

    for n in set(edges["child"]) | set(edges["parent"]):
        up(n)
    return memo


def validate(nodes: pd.DataFrame, edges: pd.DataFrame) -> dict:
    ids = set(nodes["node_id"])
    lvl = dict(zip(nodes["node_id"], nodes["level"]))
    prim = edges[edges["placement"] == "primary"]
    try:
        anc, acyclic = ancestors(edges), True
    except ValueError:
        anc, acyclic = {}, False
    checks = {
        "n_nodes": len(nodes),
        "n_edges": len(edges),
        "n_edges_secondary": int((edges["placement"] == "secondary").sum()),
        "n_nodes_with_several_parents": int(edges["child"].value_counts().gt(1).sum()),
        "roots": sorted(ids - set(edges["child"])),
        "unique_node_ids": bool(nodes["node_id"].is_unique),
        "single_top": ids - set(edges["child"]) == {TOP},
        "no_duplicate_edges": not edges.duplicated(["child", "parent"]).any(),
        "one_primary_parent_each": bool(prim["child"].is_unique and set(prim["child"]) == ids - {TOP}),
        "edges_reference_known_nodes": bool(edges["child"].isin(ids).all() and edges["parent"].isin(ids).all()),
        "acyclic": acyclic,
        "all_nodes_reach_top": acyclic and all(TOP in anc.get(n, {n}) for n in ids),
        "primary_child_level_is_parent_level_plus_1": all(lvl[c] == lvl[p] + 1
                                                          for c, p in zip(prim["child"], prim["parent"])),
        # info only: IMDRF also places terms under a level-2 term of another group (Headache <= Pain), so `level`
        # is the depth along the primary path; the order itself is checked by `acyclic`
        "secondary_edges_by_child_parent_level": {
            f"{a}->{b}": int(n) for (a, b), n in edges.loc[edges["placement"] == "secondary"].assign(
                a=lambda d: d["child"].map(lvl), b=lambda d: d["parent"].map(lvl)).groupby(["a", "b"]).size().items()},
        "max_depth": int(nodes["level"].max()),
        "nodes_per_level": {str(k): int(v) for k, v in nodes["level"].value_counts().sort_index().items()},
    }
    checks["valid"] = all(checks[k] for k in (
        "unique_node_ids", "single_top", "no_duplicate_edges", "one_primary_parent_each", "edges_reference_known_nodes",
        "acyclic", "all_nodes_reach_top", "primary_child_level_is_parent_level_plus_1"))
    return checks


def support(report_leaf: pd.DataFrame, nodes: pd.DataFrame, edges: pd.DataFrame, key: str) -> pd.DataFrame:
    """Distinct reports per node: mapped directly to it, and anywhere in ↓node (over all parents, each report once).
    Every node listed (0 if unused)."""
    anc = ancestors(edges)
    rl = report_leaf[[key, "node_id"]].drop_duplicates()
    direct = rl.groupby("node_id")[key].nunique()
    up = rl.assign(node_id=rl["node_id"].map(lambda n: sorted(anc.get(n, {n})))).explode("node_id")
    rollup = up.drop_duplicates().groupby("node_id")[key].nunique()
    out = nodes[["node_id"]].copy()
    out["n_reports_direct"] = out["node_id"].map(direct).fillna(0).astype(int)
    out["n_reports_rollup"] = out["node_id"].map(rollup).fillna(0).astype(int)
    return out


# ====================================================================== MAUDE (IMDRF)
def imdrf_annex(sheet: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Primary placement of every code (parent, level, label, status) + secondary placements.

    IMDRF Annex E lists some terms under a second level-1 group (CodeHierarchy, Primary/Secondary Category).
    Primary placement = the only row of a code, or the row whose CodeHierarchy starts at the level-1 group named in
    'Primary Category'. Parents come from CodeHierarchy, not from the code prefix (E1707 sits under E23)."""
    a = pd.read_excel(IMDRF_XLSX, sheet, dtype=str, header=7)
    a = a[a["Code"].notna()].copy()
    a["Code"] = a["Code"].str.strip()
    a["chain"] = a["CodeHierarchy"].str.strip().str.split("|")
    a["label"] = a[["Level 1 Term", "Level 2 Term", "Level 3 Term"]].bfill(axis=1).iloc[:, 0].str.strip()
    a["status"] = a["Status"].fillna("").str.strip()
    assert (a["chain"].str[-1] == a["Code"]).all(), "CodeHierarchy does not end with Code"
    level1 = {norm(lbl): code for code, lbl in zip(a["Code"], a["label"]) if len(code) == 3}
    pc = a["Primary Category"] if "Primary Category" in a else pd.Series(index=a.index, dtype=str)
    a["pc_code"] = pc.map(lambda s: level1.get(norm(s)) if isinstance(s, str) else None)
    a["n_rows"] = a.groupby("Code")["Code"].transform("size")
    a["is_primary"] = (a["n_rows"] == 1) | (a["chain"].str[0] == a["pc_code"])
    # Level-3 rows under a multi-placed level-2 term carry no Primary Category: they follow their parent's primary
    # level-1 group (e.g. E081901 under E0819 Eye Injury: primary E08, secondary E20).
    primary_top = a[a["is_primary"]].groupby("Code")["chain"].first().str[0]
    undecided = a.groupby("Code")["is_primary"].transform("sum") == 0
    parent_top = a["chain"].str[-2].map(primary_top)
    a.loc[undecided, "is_primary"] = a.loc[undecided, "chain"].str[0] == parent_top[undecided]
    n_primary = a.groupby("Code")["is_primary"].sum()
    bad = n_primary[n_primary != 1]
    assert bad.empty, f"codes without exactly one primary placement: {list(bad.index)[:10]}"
    prim = a[a["is_primary"]].copy()
    prim["parent"] = prim["chain"].map(lambda c: c[-2] if len(c) > 1 else TOP)
    prim["level"] = prim["chain"].str.len()
    sec = a[~a["is_primary"]].assign(parent=lambda d: d["chain"].str[-2])[["Code", "parent"]]
    return prim, sec.rename(columns={"Code": "child"})


def fda_codes(zip_name: str) -> pd.DataFrame:
    with zipfile.ZipFile(DATA / "maude/raw" / zip_name) as z:
        return pd.read_csv(z.open(z.namelist()[0]), dtype=str, encoding="utf-8-sig", keep_default_na=False)


NO_EFFECT_RE = re.compile(r"^no (consequences or impact|known impact|patient involvement)", re.I)


def maude_public(name: str, sheet: str, codes_zip: str, legacy_prefix: str, no_effect: bool, xw: pd.DataFrame):
    prim, sec = imdrf_annex(sheet)
    root = "All device problems" if sheet == "A" else "All health effects"
    nodes = [{"node_id": TOP, "label": root, "level": 0, "source": "root", "status": ""}]
    nodes += [{"node_id": r.Code, "label": r.label, "level": int(r.level), "source": f"IMDRF Annex {sheet} 2026",
               "status": r.status} for r in prim.itertuples()]
    edges = [{"child": r.Code, "parent": r.parent, "placement": "primary"} for r in prim.itertuples()]
    # L7 (DAG): IMDRF secondary placements are edges too; a level-3 term under a multi-placed level-2 term repeats its
    # primary edge in the secondary chain, so drop pairs that are already primary
    have = {(e["child"], e["parent"]) for e in edges}
    edges += [{"child": c, "parent": p, "placement": "secondary"}
              for c, p in sec[["child", "parent"]].drop_duplicates().itertuples(index=False) if (c, p) not in have]
    nodes.append({"node_id": "UNMAPPED", "label": "FDA legacy code without IMDRF equivalent", "level": 1,
                  "source": "added", "status": ""})
    edges.append({"child": "UNMAPPED", "parent": TOP, "placement": "primary"})
    if no_effect:  # FDA legacy "no impact / no patient" codes sit with IMDRF's own E24 group
        nodes.append({"node_id": "NO_EFFECT", "label": "No health effect or no patient involved (FDA legacy codes)",
                      "level": 2, "source": "added", "status": ""})
        edges.append({"child": "NO_EFFECT", "parent": "E24", "placement": "primary"})

    known = {n["node_id"] for n in nodes}
    by_name = {norm(lbl): code for code, lbl in zip(prim["Code"], prim["label"])}
    xw = xw[xw["lattice"] == name]
    approved = dict(zip(xw.loc[xw.status == "approved", "fda_code"], xw.loc[xw.status == "approved", "target_node"]))
    proposed = dict(zip(xw.loc[xw.status == "proposed", "fda_code"], xw.loc[xw.status == "proposed", "target_node"]))
    for t in list(approved.values()) + list(proposed.values()):
        assert t in known, f"crosswalk target {t} not in {name}"

    mapping = []
    for r in fda_codes(codes_zip).itertuples():
        code, term, imdrf = r.FDA_CODE, r.TERM, r.IMDRF_CODE.strip()
        if imdrf:
            mapping.append((code, term, imdrf, "fda_imdrf_code"))
        elif code in approved:
            mapping.append((code, term, approved[code], "manual_crosswalk"))
        elif norm(term) in by_name:
            mapping.append((code, term, by_name[norm(term)], "name_match"))
        elif no_effect and NO_EFFECT_RE.search(term):
            mapping.append((code, term, "NO_EFFECT", "no_effect_rule"))
        else:  # keep the legacy FDA term as its own leaf under UNMAPPED
            nid = f"{legacy_prefix}:{code}"
            nodes.append({"node_id": nid, "label": term, "level": 2, "source": "FDA legacy code", "status": ""})
            edges.append({"child": nid, "parent": "UNMAPPED", "placement": "primary"})
            mapping.append((code, term, nid, "unmapped_fda_leaf"))
    mapping = pd.DataFrame(mapping, columns=["fda_code", "fda_term", "node_id", "method"])
    mapping["proposed_node"] = mapping["fda_code"].map(proposed)  # preview only; applied once approved
    return pd.DataFrame(nodes), pd.DataFrame(edges), mapping


def maude_hidden(name: str, hidden_file: str, nodes, edges, mapping) -> pd.DataFrame:
    h = pd.read_parquet(DATA / "maude/hidden" / hidden_file, columns=["MDR_REPORT_KEY", "code"])
    h = h.merge(mapping[["fda_code", "node_id", "method", "proposed_node"]], left_on="code", right_on="fda_code",
                how="left")
    rec = pd.read_parquet(DATA / "maude/processed/reports", columns=["MDR_REPORT_KEY", "date_received"])
    h["year"] = h["MDR_REPORT_KEY"].map(rec.set_index("MDR_REPORT_KEY")["date_received"]).map(
        lambda d: d.year if pd.notna(d) else None)
    in_tree = ~h["method"].isin(["unmapped_fda_leaf"]) & h["method"].notna()
    in_tree_wo = in_tree & (h["method"] != "manual_crosswalk")      # L8: without the manual crosswalk
    in_tree_prop = in_tree | h["proposed_node"].notna()             # remaining (medium-confidence) proposals applied

    def by_year(mask):
        return {str(int(y)): round(float(1 - g.mean()), 4) for y, g in mask.groupby(h["year"]) if pd.notna(y)}

    cov = {
        "rows": len(h),
        "rows_unknown_code": int(h["node_id"].isna().sum()),
        "rows_by_method": {str(k): int(v) for k, v in h["method"].value_counts(dropna=False).items()},
        "share_rows_in_imdrf_tree": round(float(in_tree.mean()), 4),
        "share_rows_in_imdrf_tree_without_crosswalk": round(float(in_tree_wo.mean()), 4),
        "share_rows_in_imdrf_tree_if_remaining_proposed_applied": round(float(in_tree_prop.mean()), 4),
        "unmapped_share_by_year": by_year(in_tree),
        "unmapped_share_by_year_without_crosswalk": by_year(in_tree_wo),
        "unmapped_share_by_year_if_remaining_proposed_applied": by_year(in_tree_prop),
    }
    (DATA / "maude/hidden" / f"lattice_{name}_coverage.json").write_text(json.dumps(cov, indent=2))
    h = h.dropna(subset=["node_id"])
    support(h, nodes, edges, "MDR_REPORT_KEY").to_csv(DATA / "maude/hidden" / f"lattice_{name}_support.csv",
                                                      index=False)
    # L8 trend check: distinct reports per year and level-1 group (over all parents), with and without the crosswalk
    anc = ancestors(edges)
    level1 = set(nodes.loc[nodes["level"] == 1, "node_id"])
    groups = {n: sorted(a & level1) for n, a in anc.items()}
    h["node_without"] = h["node_id"].where(h["method"] != "manual_crosswalk", "UNMAPPED")
    counts = {}
    for col, tag in (("node_id", "n_with_crosswalk"), ("node_without", "n_without_crosswalk")):
        g = h[["MDR_REPORT_KEY", "year", col]].assign(group=h[col].map(groups)).explode("group")
        counts[tag] = g.drop_duplicates(["MDR_REPORT_KEY", "group"]).groupby(["year", "group"])["MDR_REPORT_KEY"].size()
    trend = pd.DataFrame(counts).fillna(0).astype(int).reset_index()
    trend.insert(0, "lattice", name)
    trend["diff"] = trend["n_with_crosswalk"] - trend["n_without_crosswalk"]
    print(f"  [{name}] in IMDRF tree {cov['share_rows_in_imdrf_tree']:.2%} "
          f"(without crosswalk {cov['share_rows_in_imdrf_tree_without_crosswalk']:.2%})")
    return trend


# ====================================================================== ASRS
# ASRS Coding Form, April 2024 (data/asrs/docs/ASRS_CodingTaxonomy.pdf p.13), spelled as in the CSV export.
ASRS_TAXONOMY = {
    "Aircraft Equipment Problem": ["Critical", "Less Severe"],
    "Airspace Violation": ["All Types"],
    "ATC Issue": ["All Types"],
    "Flight Deck / Cabin / Aircraft Event": ["Illness / Injury", "Passenger Electronic Device", "Passenger Misconduct",
                                             "Smoke / Fire / Fumes / Odor", "Other / Unknown"],
    "Conflict": ["NMAC", "Airborne Conflict", "Ground Conflict"],
    "Deviation - Altitude": ["Crossing Restriction Not Met", "Excursion From Assigned Altitude", "Overshoot",
                             "Undershoot"],
    "Deviation - Speed": ["All Types"],
    "Deviation - Track / Heading": ["All Types"],
    "Deviation / Discrepancy - Procedural": ["Clearance", "FAR", "Hazardous Material Violation",
                                             "Landing Without Clearance", "Maintenance", "MEL / CDL",
                                             "Published Material / Policy", "Security",
                                             "Unauthorized Flight Operations (UAS)", "Weight And Balance",
                                             "Other / Unknown"],
    "Ground Excursion": ["Ramp", "Runway", "Taxiway"],
    "Ground Incursion": ["Ramp", "Runway", "Taxiway"],
    "Ground Event / Encounter": ["Aircraft", "FOD", "Fuel Issue", "Gear Up Landing", "Ground Equipment Issue",
                                 "Ground Strike - Aircraft", "Jet Blast", "Loss Of Aircraft Control",
                                 "Loss Of VLOS (UAS)", "Object", "Person / Animal / Bird", "Vehicle",
                                 "Weather / Turbulence", "Other / Unknown"],
    "Inflight Event / Encounter": ["Aircraft", "CFTT / CFIT", "Fly Away (UAS)", "Fuel Issue", "Laser",
                                   "Loss Of Aircraft Control", "Object", "Bird / Animal", "Unstabilized Approach",
                                   "VFR In IMC", "Wake Vortex Encounter", "Weather / Turbulence", "Other / Unknown"],
    "No Specific Anomaly Occurred": ["All Types", "Unwanted Situation"],
    "Other": ["Write-in"],
}
GROUND_CONFLICT_SEVERITIES = ["Critical", "Less Severe"]


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def asrs_leaf(cat: str, sub: str, sev: str | None = None) -> str:
    return f"{slug(cat)}/{slug(sub)}" + (f"/{slug(sev)}" if sev else "")


def asrs_public():
    nodes = [{"node_id": TOP, "label": "All anomalies", "level": 0}]
    edges = []
    for cat, subs in ASRS_TAXONOMY.items():
        nodes.append({"node_id": slug(cat), "label": cat, "level": 1})
        edges.append({"child": slug(cat), "parent": TOP})
        for sub in subs:
            nodes.append({"node_id": asrs_leaf(cat, sub), "label": sub, "level": 2})
            edges.append({"child": asrs_leaf(cat, sub), "parent": slug(cat)})
    for sev in GROUND_CONFLICT_SEVERITIES:
        nodes.append({"node_id": asrs_leaf("Conflict", "Ground Conflict", sev), "label": sev, "level": 3})
        edges.append({"child": asrs_leaf("Conflict", "Ground Conflict", sev),
                      "parent": asrs_leaf("Conflict", "Ground Conflict")})
    nodes = pd.DataFrame(nodes).assign(source="ASRS Coding Form (April 2024)", status="")
    mapping = [{"raw_value": f"{cat} {sub}", "node_id": asrs_leaf(cat, sub), "method": "category + subcategory"}
               for cat, subs in ASRS_TAXONOMY.items() for sub in subs if cat != "Other"]
    mapping += [{"raw_value": sev, "node_id": asrs_leaf("Conflict", "Ground Conflict", sev),
                 "method": "severity token; refines the preceding 'Conflict Ground Conflict'"}
                for sev in GROUND_CONFLICT_SEVERITIES]
    mapping.append({"raw_value": "Other <free-text write-in>", "node_id": asrs_leaf("Other", "Write-in"),
                    "method": "any value starting with 'Other '"})
    return nodes, pd.DataFrame(edges).assign(placement="primary"), pd.DataFrame(mapping)


def asrs_parse(values: list[str]) -> list[str]:
    """A report's anomaly values -> leaf node ids. Fails loudly on anything outside the coding form."""
    out = []
    for v in values:
        if v in GROUND_CONFLICT_SEVERITIES:
            if not out or out[-1] != asrs_leaf("Conflict", "Ground Conflict"):
                raise ValueError(f"severity without preceding Ground Conflict: {values}")
            out[-1] = asrs_leaf("Conflict", "Ground Conflict", v)
            continue
        if v.startswith("Other "):
            out.append(asrs_leaf("Other", "Write-in"))
            continue
        cat = max((c for c in ASRS_TAXONOMY if v.startswith(c + " ")), key=len, default=None)
        sub = v[len(cat):].strip() if cat else None
        if cat is None or sub not in ASRS_TAXONOMY[cat]:
            raise ValueError(f"anomaly value not in the coding form: {v!r}")
        out.append(asrs_leaf(cat, sub))
    return out


def asrs_hidden(nodes, edges) -> None:
    lab = pd.read_parquet(DATA / "asrs/hidden/labels.parquet", columns=["ACN", "anomaly"])
    with_a = lab[lab["anomaly"].notna()]
    rl = pd.DataFrame([(acn, leaf) for acn, vals in zip(with_a["ACN"], with_a["anomaly"])
                       for leaf in asrs_parse(list(vals))], columns=["ACN", "node_id"]).drop_duplicates()
    rl.to_parquet(DATA / "asrs/hidden/anomaly_nodes.parquet", index=False)
    support(rl, nodes, edges, "ACN").to_csv(DATA / "asrs/hidden/lattice_asrs_anomaly_support.csv", index=False)
    cov = {"reports": len(lab), "reports_without_anomaly": int(lab["anomaly"].isna().sum()),
           "reports_with_anomaly": len(with_a), "report_leaf_pairs": len(rl),
           "distinct_leaves_used": int(rl["node_id"].nunique()),
           "leaves_in_taxonomy": int((~nodes["node_id"].isin(edges["parent"])).sum())}
    (DATA / "asrs/hidden/lattice_asrs_anomaly_coverage.json").write_text(json.dumps(cov, indent=2))
    print(f"  [asrs_anomaly] {cov}")


# ====================================================================== main
def main() -> None:
    xw = pd.read_csv(CROSSWALK, dtype=str, keep_default_na=False)
    built = {
        "maude_device": maude_public("maude_device", "A", "deviceproblemcodes2025.zip", "FDA-DEV", False, xw),
        "maude_patient": maude_public("maude_patient", "E", "patientproblemdata.zip", "FDA-PAT", True, xw),
        "asrs_anomaly": asrs_public(),
    }
    # validate everything before writing anything
    checks = {}
    for name, (nodes, edges, mapping) in built.items():
        checks[name] = validate(nodes, edges)
        if not checks[name]["valid"]:
            raise SystemExit(f"{name}: structural check failed: {checks[name]}")
    for name, (nodes, edges, mapping) in built.items():
        d = OUT / name
        d.mkdir(parents=True, exist_ok=True)
        nodes.sort_values(["level", "node_id"]).to_csv(d / "nodes.csv", index=False)
        edges.sort_values(["parent", "child"]).to_csv(d / "edges.csv", index=False)
        mapping.to_csv(d / "mapping.csv", index=False)
        (d / "edges_secondary.csv").unlink(missing_ok=True)  # merged into edges.csv (L7)
        (d / "checks.json").write_text(json.dumps(checks[name], indent=2))
        print(f"[{name}] {checks[name]['n_nodes']} nodes, {checks[name]['n_edges']} edges "
              f"({checks[name]['n_edges_secondary']} secondary), depth {checks[name]['max_depth']}, valid")

    # hidden side (needs scripts/build_tables.py outputs)
    trend = pd.concat([maude_hidden("maude_device", "device_problems.parquet", *built["maude_device"]),
                       maude_hidden("maude_patient", "patient_problems.parquet", *built["maude_patient"])])
    trend.to_csv(DATA / "maude/hidden/crosswalk_trend_check.csv", index=False)
    asrs_hidden(*built["asrs_anomaly"][:2])


if __name__ == "__main__":
    main()
