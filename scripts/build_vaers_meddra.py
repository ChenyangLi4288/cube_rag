"""VAERS symptom lattice from the MedDRA hierarchy (issue #3, decision V4): the main VAERS concept lattice.

    PT  <=  HLT  <=  HLGT  <=  SOC  <=  TOP

MedDRA is multiaxial: a PT can sit under several HLTs (and so several SOCs), an HLT under several HLGTs, an HLGT under
several SOCs. As in maude_patient (decision L7) every link is kept and one parent per node is primary:
  PT   -> HLT   primary = the HLT on the PT's primary-SOC path (mdhier.asc primary_soc_fg = Y)
  HLT  -> HLGT  primary = the HLGT used by most primary PT paths through the HLT (ties: lowest code)
  HLGT -> SOC   primary = the SOC used by most primary PT paths through the HLGT (ties: lowest code)
All other links are secondary. `level` is the depth along the primary path (SOC 1 ... PT 4).
All SOCs, HLGTs and HLTs are nodes; only PTs that VAERS uses are leaves (same leaves as the cluster lattices, X5).

VAERS SYMPTOMn values are MedDRA terms from the version current when each report was coded. They map to 29.1 PTs by
exact PT name, then PT name ignoring case, then LLT name (old and renamed PTs stay as LLTs) to its PT. The rest are
listed as unmapped with their report counts.

Licence (MSSO): MedDRA files and anything that carries MedDRA names stay local and are never committed (CLAUDE.md).
This script prints counts only. Using MedDRA names in an LLM prompt waits on the AI-use confirmation (issue #3).

Inputs: data/vaers/MedDRA_29_1_English_v2/MedAscii/*.asc (column layout: MSSO distribution file format, release 29.1)
        data/vaers/hidden/symptoms.parquet; data/vaers/lattice_clusters{,_anchored}/ for the comparison (optional)
Outputs (local): data/vaers/lattice_meddra/{nodes,edges,mapping,unmapped}.csv, checks.json, compare_clusters.json,
                 MANIFEST.json; data/vaers/hidden/lattice_vaers_meddra_support.csv

Usage: python scripts/build_vaers_meddra.py
"""

import hashlib
import importlib.util
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MEDDRA = DATA / "vaers/MedDRA_29_1_English_v2/MedAscii"
OUT = DATA / "vaers/lattice_meddra"
TOP = "TOP"

_spec = importlib.util.spec_from_file_location("build_hierarchies", ROOT / "scripts/build_hierarchies.py")
bh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bh)

_LEGACY = ["whoart_code", "harts_code", "costart_sym", "icd9_code", "icd9cm_code", "icd10_code", "jart_code"]
COLS = {
    "mdhier": ["pt_code", "hlt_code", "hlgt_code", "soc_code", "pt_name", "hlt_name", "hlgt_name", "soc_name",
               "soc_abbrev", "null_field", "pt_soc_code", "primary_soc_fg"],
    "pt": ["pt_code", "pt_name", "null_field", "pt_soc_code"] + [f"pt_{c}" for c in _LEGACY],
    "llt": ["llt_code", "llt_name", "pt_code"] + [f"llt_{c}" for c in _LEGACY[:6]] + ["llt_currency", "llt_jart_code"],
    "hlt": ["hlt_code", "hlt_name"] + [f"hlt_{c}" for c in _LEGACY],
    "hlgt": ["hlgt_code", "hlgt_name"] + [f"hlgt_{c}" for c in _LEGACY],
    "soc": ["soc_code", "soc_name", "soc_abbrev"] + [f"soc_{c}" for c in _LEGACY],
    "hlt_pt": ["hlt_code", "pt_code"],
    "hlgt_hlt": ["hlgt_code", "hlt_code"],
    "soc_hlgt": ["soc_code", "hlgt_code"],
}


def read(name: str) -> pd.DataFrame:
    """One $-delimited MedAscii file (every line ends with '$', so the last split field is empty)."""
    d = pd.read_csv(MEDDRA / f"{name}.asc", sep="$", header=None, dtype=str, keep_default_na=False, quoting=3,
                    encoding="ascii")
    assert d.shape[1] == len(COLS[name]) + 1 and (d.iloc[:, -1] == "").all(), f"{name}.asc: unexpected columns"
    d = d.iloc[:, :-1]
    d.columns = COLS[name]
    for c in [c for c in d.columns if c in {"pt_code", "hlt_code", "hlgt_code", "soc_code", "llt_code", "pt_soc_code"}]:
        assert d[c].str.fullmatch(r"\d{8}").all(), f"{name}.asc: {c} is not an 8-digit code everywhere"
    return d


def primary_parent(links: pd.DataFrame, child: str, parent: str, prim_paths: pd.DataFrame, all_paths: pd.DataFrame):
    """child -> primary parent: the parent used by most primary PT paths (then by most paths, then lowest code)."""
    def votes(paths):
        return paths.groupby([child, parent]).size().rename("n").reset_index()
    v = links[[child, parent]].drop_duplicates()
    v = v.merge(votes(prim_paths).rename(columns={"n": "n_prim"}), how="left") \
         .merge(votes(all_paths).rename(columns={"n": "n_all"}), how="left").fillna({"n_prim": 0, "n_all": 0})
    v = v.sort_values([child, "n_prim", "n_all", parent], ascending=[True, False, False, True])
    return v.drop_duplicates(child).set_index(child)[parent]


def purity(labels: pd.Series, truth: pd.Series, weight: pd.Series | None = None) -> float:
    """Share (of terms, or of weight) whose truth label is the majority truth label of their group."""
    w = pd.Series(1.0, index=labels.index) if weight is None else weight.astype(float)
    d = pd.DataFrame({"g": labels, "t": truth, "w": w})
    best = d.groupby(["g", "t"])["w"].sum().groupby("g").max().sum()
    return round(float(best / d["w"].sum()), 3)


def compare_cluster_lattices(term_soc: pd.Series, term_hlgt: pd.Series, term_reports: pd.Series) -> dict:
    """How well the stand-in lattices (plain clusters, IMDRF-anchored) recover the MedDRA primary SOC / HLGT."""
    from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score
    out = {}

    def score(name, groups, truth, n_truth_groups):
        common = groups.index.intersection(truth.index)
        g, t = groups[common], truth[common]
        out[name] = {"terms": int(len(common)), "groups": int(g.nunique()), "meddra_groups": int(n_truth_groups),
                     "nmi": round(float(normalized_mutual_info_score(t, g)), 3),
                     "ari": round(float(adjusted_rand_score(t, g)), 3),
                     "purity_terms": purity(g, t), "purity_reports": purity(g, t, term_reports[common])}

    plain = DATA / "vaers/lattice_clusters/edges.csv"
    if plain.exists():
        e = pd.read_csv(plain)
        leaf = e[e["child"].str.startswith("PT:")].set_index("child")["parent"]
        leaf.index = leaf.index.str[3:]
        score("plain_top27_vs_soc", leaf.str.split(".").str[0], term_soc, term_soc.nunique())
        score("plain_mid300_vs_hlgt", leaf, term_hlgt, term_hlgt.nunique())
    anch = DATA / "vaers/lattice_clusters_anchored/edges.csv"
    if anch.exists():
        e = pd.read_csv(anch)
        p = e[e["placement"] == "primary"]
        leaf = p[p["child"].str.startswith("PT:")].set_index("child")["parent"]
        leaf.index = leaf.index.str[3:]
        grp = leaf.map(p[~p["child"].str.startswith("PT:")].set_index("child")["parent"])
        score("anchored_imdrf_groups_vs_soc", grp, term_soc, term_soc.nunique())
    return out


def main() -> None:
    f = {n: read(n) for n in COLS}
    md, pt, llt = f["mdhier"], f["pt"], f["llt"]

    # ---- structure checks on the MedDRA files (counts only)
    prim = md[md["primary_soc_fg"] == "Y"]
    assert set(md["primary_soc_fg"]) <= {"Y", "N"}
    assert prim["pt_code"].is_unique and set(prim["pt_code"]) == set(md["pt_code"]) == set(pt["pt_code"]), \
        "every PT needs exactly one primary path"
    assert (pt.set_index("pt_code")["pt_soc_code"] == prim.set_index("pt_code")["soc_code"]).all(), \
        "pt.asc primary SOC disagrees with mdhier.asc"
    pairs = lambda d, a, b: set(zip(d[a], d[b]))
    assert pairs(md, "hlt_code", "pt_code") == pairs(f["hlt_pt"], "hlt_code", "pt_code")
    assert pairs(md, "hlgt_code", "hlt_code") <= pairs(f["hlgt_hlt"], "hlgt_code", "hlt_code")
    assert pairs(md, "soc_code", "hlgt_code") <= pairs(f["soc_hlgt"], "soc_code", "hlgt_code")
    assert llt["pt_code"].isin(pt["pt_code"]).all() and set(pt["pt_code"]) <= set(llt["llt_code"])
    assert set(llt["llt_currency"]) <= {"Y", "N"}
    for n, c in [("soc", "soc_code"), ("hlgt", "hlgt_code"), ("hlt", "hlt_code"), ("pt", "pt_code"), ("llt", "llt_code")]:
        assert f[n][c].is_unique, f"{n}.asc codes not unique"
    file_checks = {
        "counts": {n: int(len(f[n])) for n in ["soc", "hlgt", "hlt", "pt", "llt", "mdhier", "hlt_pt", "hlgt_hlt",
                                               "soc_hlgt"]},
        "pts_with_several_hlts": int(f["hlt_pt"]["pt_code"].value_counts().gt(1).sum()),
        "hlts_with_several_hlgts": int(f["hlgt_hlt"]["hlt_code"].value_counts().gt(1).sum()),
        "hlgts_with_several_socs": int(f["soc_hlgt"]["hlgt_code"].value_counts().gt(1).sum()),
        "llts_non_current": int((llt["llt_currency"] == "N").sum()),
        "pt_names_unique": bool(pt["pt_name"].is_unique),
        "pt_names_unique_ignoring_case": bool(pt["pt_name"].str.lower().is_unique),
        "llt_names_unique": bool(llt["llt_name"].is_unique),
    }

    # ---- VAERS terms -> 29.1 PTs
    sym = pd.read_parquet(DATA / "vaers/hidden/symptoms.parquet", columns=["VAERS_ID", "pt"])
    sym["pt"] = sym["pt"].str.strip()
    term_reports = sym.drop_duplicates().groupby("pt")["VAERS_ID"].nunique()
    terms = sorted(term_reports.index)

    def unique_map(keys: pd.Series, vals: pd.Series) -> dict:
        d = pd.DataFrame({"k": keys.to_numpy(), "v": vals.to_numpy()}).drop_duplicates()
        d = d[~d["k"].duplicated(keep=False)]           # drop keys that point to more than one PT
        return dict(zip(d["k"], d["v"]))

    by_pt = unique_map(pt["pt_name"], pt["pt_code"])
    by_pt_ci = unique_map(pt["pt_name"].str.lower(), pt["pt_code"])
    by_llt = unique_map(llt["llt_name"], llt["pt_code"])
    by_llt_ci = unique_map(llt["llt_name"].str.lower(), llt["pt_code"])
    llt_current = dict(zip(llt["llt_name"], llt["llt_currency"]))
    rows = []
    for t in terms:
        if t in by_pt:
            code, how = by_pt[t], "exact PT name"
        elif t.lower() in by_pt_ci:
            code, how = by_pt_ci[t.lower()], "PT name, ignoring case"
        elif t in by_llt:
            code = by_llt[t]
            how = "LLT name -> PT" + ("" if llt_current.get(t) == "Y" else " (non-current LLT)")
        elif t.lower() in by_llt_ci:
            code, how = by_llt_ci[t.lower()], "LLT name, ignoring case -> PT"
        else:
            code, how = None, "unmapped"
        rows.append({"raw_value": t, "pt_code": code, "method": how, "n_reports": int(term_reports[t])})
    m = pd.DataFrame(rows)
    mapped, unmapped = m[m["pt_code"].notna()].copy(), m[m["pt_code"].isna()]
    mapped["node_id"] = "PT:" + mapped["pt_code"]

    # ---- lattice
    used_pt = sorted(set(mapped["pt_code"]))
    hlgt_hlt, soc_hlgt = f["hlgt_hlt"], f["soc_hlgt"]
    hlt_pt = f["hlt_pt"][f["hlt_pt"]["pt_code"].isin(used_pt)]
    pt_prim = prim.set_index("pt_code")["hlt_code"]
    hlt_prim = primary_parent(hlgt_hlt, "hlt_code", "hlgt_code", prim, md)
    hlgt_prim = primary_parent(soc_hlgt, "hlgt_code", "soc_code", prim, md)

    name = {**dict(zip("SOC:" + f["soc"]["soc_code"], f["soc"]["soc_name"])),
            **dict(zip("HLGT:" + f["hlgt"]["hlgt_code"], f["hlgt"]["hlgt_name"])),
            **dict(zip("HLT:" + f["hlt"]["hlt_code"], f["hlt"]["hlt_name"])),
            **dict(zip("PT:" + pt["pt_code"], pt["pt_name"]))}
    nodes = [(TOP, "All symptom terms", 0)]
    nodes += [(f"SOC:{c}", None, 1) for c in sorted(f["soc"]["soc_code"])]
    nodes += [(f"HLGT:{c}", None, 2) for c in sorted(f["hlgt"]["hlgt_code"])]
    nodes += [(f"HLT:{c}", None, 3) for c in sorted(f["hlt"]["hlt_code"])]
    nodes += [(f"PT:{c}", None, 4) for c in used_pt]
    nodes = pd.DataFrame(nodes, columns=["node_id", "label", "level"])
    nodes["label"] = nodes["label"].fillna(nodes["node_id"].map(name))
    nodes = nodes.assign(source="MedDRA 29.1 English (MSSO); local only", status="")

    def link(d, c, p, cpre, ppre, primary):
        e = pd.DataFrame({"child": cpre + d[c], "parent": ppre + d[p]})
        e["placement"] = np.where(d[p].to_numpy() == d[c].map(primary).to_numpy(), "primary", "secondary")
        return e
    edges = pd.concat([
        pd.DataFrame({"child": "SOC:" + f["soc"]["soc_code"], "parent": TOP, "placement": "primary"}),
        link(soc_hlgt, "hlgt_code", "soc_code", "HLGT:", "SOC:", hlgt_prim),
        link(hlgt_hlt, "hlt_code", "hlgt_code", "HLT:", "HLGT:", hlt_prim),
        link(hlt_pt, "pt_code", "hlt_code", "PT:", "HLT:", pt_prim),
    ], ignore_index=True)

    checks = bh.validate(nodes, edges)
    if not checks["valid"]:
        raise SystemExit(f"structural check failed: { {k: v for k, v in checks.items() if v is False} }")
    rl = sym.merge(mapped[["raw_value", "node_id"]], left_on="pt", right_on="raw_value")[["VAERS_ID", "node_id"]]
    sup = bh.support(rl, nodes, edges, "VAERS_ID").merge(
        bh.support(rl, nodes, edges[edges["placement"] == "primary"], "VAERS_ID")[["node_id", "n_reports_rollup"]]
        .rename(columns={"n_reports_rollup": "n_reports_rollup_primary_path"}), on="node_id")
    n_reports = sym["VAERS_ID"].nunique()
    reports_mapped = rl["VAERS_ID"].nunique()
    checks["meddra_files"] = file_checks
    checks["vaers_mapping"] = {
        "distinct_terms": len(terms),
        "terms_by_method": m["method"].value_counts().to_dict(),
        "distinct_pts_used": len(used_pt),
        "symptom_rows_mapped_share": round(float(sym["pt"].isin(mapped["raw_value"]).mean()), 5),
        "reports_with_symptoms": int(n_reports),
        "reports_with_at_least_one_mapped_term": int(reports_mapped),
        "reports_with_an_unmapped_term": int(sym.loc[sym["pt"].isin(unmapped["raw_value"]), "VAERS_ID"].nunique()),
        "unmapped_terms": int(len(unmapped)),
        "unmapped_report_mentions": int(unmapped["n_reports"].sum()),
    }
    checks["support"] = {
        "nodes_with_no_reports_by_level": {str(k): int(v) for k, v in sup.merge(nodes[["node_id", "level"]])
                                           .query("n_reports_rollup == 0").groupby("level").size().items()},
        "top_rollup_equals_reports_mapped": bool(sup.set_index("node_id").at[TOP, "n_reports_rollup"] == reports_mapped),
    }

    # ---- stand-in lattices vs MedDRA (term -> primary SOC / HLGT)
    pp = prim.set_index("pt_code")
    tm = mapped.set_index("raw_value")["pt_code"]
    compare = compare_cluster_lattices(tm.map(pp["soc_code"]), tm.map(pp["hlgt_code"]), term_reports)

    OUT.mkdir(parents=True, exist_ok=True)
    nodes.to_csv(OUT / "nodes.csv", index=False)
    edges.sort_values(["parent", "child"]).to_csv(OUT / "edges.csv", index=False)
    mapped[["raw_value", "node_id", "method", "n_reports"]].to_csv(OUT / "mapping.csv", index=False)
    unmapped[["raw_value", "n_reports"]].sort_values("n_reports", ascending=False).to_csv(OUT / "unmapped.csv",
                                                                                          index=False)
    (OUT / "checks.json").write_text(json.dumps(checks, indent=2))
    (OUT / "compare_clusters.json").write_text(json.dumps(compare, indent=2))
    sup.to_csv(DATA / "vaers/hidden/lattice_vaers_meddra_support.csv", index=False)
    used = ["mdhier", "pt", "llt", "hlt", "hlgt", "soc", "hlt_pt", "hlgt_hlt", "soc_hlgt"]
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout
    dirty = subprocess.run(["git", "status", "--porcelain", "scripts/build_vaers_meddra.py"], cwd=ROOT,
                           capture_output=True, text=True).stdout
    (OUT / "MANIFEST.json").write_text(json.dumps({
        "built_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "script": "scripts/build_vaers_meddra.py",
        "git": commit.strip() + ("+uncommitted-script" if dirty.strip() else ""),
        "meddra_dir": str(MEDDRA.relative_to(ROOT)),
        "meddra_release_file": (MEDDRA / "meddra_release.asc").read_text(encoding="ascii").strip(),
        "files_sha256": {f"{n}.asc": hashlib.sha256((MEDDRA / f"{n}.asc").read_bytes()).hexdigest() for n in used},
        "symptoms_sha256": hashlib.sha256("\n".join(terms).encode()).hexdigest(),
        "primary_rule": {"PT->HLT": "mdhier primary_soc_fg = Y",
                         "HLT->HLGT, HLGT->SOC": "most primary PT paths, then most paths, then lowest code"},
    }, indent=2))

    print(f"[vaers_meddra] {checks['n_nodes']} nodes, {checks['n_edges']} edges ({checks['n_edges_secondary']} "
          f"secondary), valid; levels {checks['nodes_per_level']}")
    print(f"  mapping: {json.dumps(checks['vaers_mapping'])}")
    print(f"  support: {json.dumps(checks['support'])}")
    print(f"  compare: {json.dumps(compare)}")


if __name__ == "__main__":
    main()
