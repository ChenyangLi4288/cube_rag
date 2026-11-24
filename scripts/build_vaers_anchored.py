"""VAERS symptom-cluster lattice anchored on IMDRF Annex E (issue #3, optional item; fallback main VAERS lattice if
MedDRA is not available). The plain cluster lattice (scripts/build_vaers_clusters.py) stays the X5 alternative.

IMDRF Annex E (public, release 2026) gives a MedDRA name for most health-effect terms ("Non-IMDRF Code",
e.g. "MedDRA:10008107:Cerebral edema"). VAERS terms that match such a name (after US/UK spelling normalisation) are
anchors with known IMDRF level-1 groups (E01 Nervous System ... E24). The lattice is
    PT  <=  mid cluster (the 300 mid groups of the plain lattice, unchanged)  <=  IMDRF level-1 group  <=  TOP
Each mid cluster goes under one IMDRF group: the majority primary group of its anchors if at least MIN_VOTES anchors
agree with a share >= MIN_SHARE, otherwise the group whose anchor centroid is nearest to the cluster centroid
(text embeddings). An anchor whose IMDRF groups differ from its cluster's group gets them as extra parents
(placement = secondary), as in maude_patient (decision L7).
Validation: anchors are split into 5 seeded folds; each fold is hidden, mid clusters are re-assigned from the
remaining anchors, and we report how often a hidden anchor ends up under its IMDRF primary group (and under any of
its IMDRF groups).

Outputs (local, like the plain clusters, until committing MedDRA term names is confirmed):
  data/vaers/lattice_clusters_anchored/{nodes,edges,mapping}.csv, checks.json, MANIFEST.json
  data/vaers/hidden/lattice_vaers_clusters_anchored_support.csv
Needs: data/vaers/lattice_clusters/ (run build_vaers_clusters.py first) and the IMDRF workbook.

Usage: python scripts/build_vaers_anchored.py
"""

import hashlib
import importlib.util
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PLAIN = DATA / "vaers/lattice_clusters"
OUT = DATA / "vaers/lattice_clusters_anchored"
MIN_VOTES, MIN_SHARE = 2, 0.5
SEED, FOLDS = 20261123, 5
TOP = "TOP"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bh = _load("build_hierarchies")
vc = _load("build_vaers_clusters")

UK_US = [("oedema", "edema"), ("oesoph", "esoph"), ("haem", "hem"), ("anaem", "anem"), ("aemia", "emia"),
         ("diarrhoea", "diarrhea"), ("oestr", "estr"), ("foetal", "fetal"), ("paed", "ped"), ("tumour", "tumor"),
         ("ischaem", "ischem"), ("leukaem", "leukem"), ("dyspnoea", "dyspnea"), ("apnoea", "apnea"),
         ("coeli", "celi")]


def norm(s: str) -> str:
    s = re.sub(r"\s+", " ", str(s).lower().strip())
    for uk, us in UK_US:
        s = s.replace(uk, us)
    return s


def imdrf_anchors() -> tuple[dict[str, tuple[str, set[str]]], dict[str, str]]:
    """normalised MedDRA name -> (primary IMDRF level-1 group, all level-1 groups); level-1 code -> label."""
    prim, sec = bh.imdrf_annex("E")
    level1 = dict(zip(prim.loc[prim["level"] == 1, "Code"], prim.loc[prim["level"] == 1, "label"]))
    primary_top = dict(zip(prim["Code"], prim["chain"].str[0]))
    a = pd.read_excel(bh.IMDRF_XLSX, "E", dtype=str, header=7)
    a = a[a["Code"].notna() & a["Non-IMDRF Code"].fillna("").str.startswith("MedDRA:")]
    a["Code"] = a["Code"].str.strip()
    a["top"] = a["CodeHierarchy"].str.strip().str.split("|").str[0]
    a["name"] = a["Non-IMDRF Code"].str.split(":", n=2).str[2].map(norm)
    out: dict[str, tuple[str, set[str]]] = {}
    for name, g in a.groupby("name"):
        codes = sorted(set(g["Code"]))
        groups = set(g["top"])
        out[name] = (primary_top[codes[0]], groups)
    return out, level1


def assign(mid: np.ndarray, x: np.ndarray, anchor_primary: dict[int, str], groups: list[str]) -> dict:
    """mid cluster -> IMDRF group, from the anchors given (term index -> primary group)."""
    idx = np.array(sorted(anchor_primary))
    g_of = np.array([anchor_primary[i] for i in idx])
    cent = {g: x[idx[g_of == g]].mean(axis=0) for g in groups if (g_of == g).any()}
    cg = list(cent)
    cm = np.stack([cent[g] / np.linalg.norm(cent[g]) for g in cg])
    out, how = {}, {}
    for m in np.unique(mid):
        members = np.flatnonzero(mid == m)
        votes = pd.Series([anchor_primary[i] for i in members if i in anchor_primary], dtype=object).value_counts()
        if len(votes) and votes.iloc[0] >= MIN_VOTES and votes.iloc[0] / votes.sum() >= MIN_SHARE:
            out[m], how[m] = votes.index[0], "anchor_majority"
        else:
            c = x[members].mean(axis=0)
            out[m], how[m] = cg[int(np.argmax(cm @ (c / np.linalg.norm(c))))], "nearest_anchor_centroid"
    return {"group": out, "how": how}


def main() -> None:
    pn = pd.read_csv(PLAIN / "nodes.csv")
    pe = pd.read_csv(PLAIN / "edges.csv")
    leaf_mid = pe[pe["child"].str.startswith("PT:")].set_index("child")["parent"]
    terms = np.array(sorted(t[3:] for t in leaf_mid.index))
    mid_ids = leaf_mid.reindex([f"PT:{t}" for t in terms]).to_numpy()
    plain_manifest = json.loads((PLAIN / "MANIFEST.json").read_text())
    assert hashlib.sha256("\n".join(terms).encode()).hexdigest() == plain_manifest["terms_sha256"], \
        "term list differs from the plain cluster lattice; rebuild it first"

    anchors, level1 = imdrf_anchors()
    groups = sorted(level1)
    anchor_primary = {i: anchors[norm(t)][0] for i, t in enumerate(terms) if norm(t) in anchors}
    anchor_all = {i: anchors[norm(t)][1] for i, t in enumerate(terms) if norm(t) in anchors}
    print(f"{len(terms)} terms, {len(anchor_primary)} IMDRF anchors; embedding with {vc.MODEL}", flush=True)
    x = vc.embed(list(terms))
    assert hashlib.sha256(np.round(x, 6).tobytes()).hexdigest() == plain_manifest["embeddings_sha256"], \
        "embeddings differ from the plain build (model or runtime changed)"

    # validation: hide one fold of anchors, re-assign, check hidden anchors
    rng = np.random.default_rng(SEED)
    a_idx = np.array(sorted(anchor_primary))
    fold = rng.permutation(len(a_idx)) % FOLDS
    hit_p = hit_any = 0
    for f in range(FOLDS):
        train = {i: anchor_primary[i] for i, k in zip(a_idx, fold) if k != f}
        res = assign(mid_ids, x, train, groups)["group"]
        for i in a_idx[fold == f]:
            hit_p += res[mid_ids[i]] == anchor_primary[i]
            hit_any += res[mid_ids[i]] in anchor_all[i]
    validation = {"anchors": int(len(a_idx)), "folds": FOLDS, "seed": SEED,
                  "hidden_anchor_under_primary_group": round(hit_p / len(a_idx), 3),
                  "hidden_anchor_under_any_of_its_groups": round(hit_any / len(a_idx), 3)}
    print(f"validation: {validation}", flush=True)

    res = assign(mid_ids, x, anchor_primary, groups)
    mid_group, how = res["group"], res["how"]
    mid_label = dict(zip(pn["node_id"], pn["label"]))

    nodes = [{"node_id": TOP, "label": "All symptom terms", "level": 0}]
    nodes += [{"node_id": g, "label": level1[g], "level": 1} for g in groups]
    nodes += [{"node_id": m, "label": mid_label[m], "level": 2} for m in sorted(mid_group)]
    nodes += [{"node_id": f"PT:{t}", "label": t, "level": 3} for t in terms]
    edges = [{"child": g, "parent": TOP, "placement": "primary"} for g in groups]
    edges += [{"child": m, "parent": g, "placement": "primary"} for m, g in sorted(mid_group.items())]
    edges += [{"child": f"PT:{t}", "parent": m, "placement": "primary"} for t, m in zip(terms, mid_ids)]
    n_extra = 0
    for i, gs in anchor_all.items():  # anchors keep their IMDRF groups as extra parents (DAG, decision L7)
        for g in sorted(gs - {mid_group[mid_ids[i]]}):
            edges.append({"child": f"PT:{terms[i]}", "parent": g, "placement": "secondary"})
            n_extra += 1
    nodes = pd.DataFrame(nodes).assign(source="IMDRF Annex E 2026 level-1 groups over Ward clusters of "
                                              f"{vc.MODEL} embeddings", status="")
    edges = pd.DataFrame(edges)
    mapping = pd.DataFrame({"raw_value": terms, "node_id": [f"PT:{t}" for t in terms],
                            "method": ["exact PT name; IMDRF anchor" if i in anchor_primary else "exact PT name"
                                       for i in range(len(terms))]})

    checks = bh.validate(nodes, edges)
    if not checks["valid"]:
        raise SystemExit(f"structural check failed: {checks}")
    checks["mid_clusters_by_rule"] = pd.Series(how).value_counts().to_dict()
    checks["mid_clusters_per_imdrf_group"] = {g: int(n) for g, n in
                                              pd.Series(mid_group).value_counts().reindex(groups, fill_value=0).items()}
    checks["anchor_secondary_edges"] = n_extra
    checks["validation"] = validation

    OUT.mkdir(parents=True, exist_ok=True)
    nodes.to_csv(OUT / "nodes.csv", index=False)
    edges.sort_values(["parent", "child"]).to_csv(OUT / "edges.csv", index=False)
    mapping.to_csv(OUT / "mapping.csv", index=False)
    (OUT / "checks.json").write_text(json.dumps(checks, indent=2))
    (OUT / "MANIFEST.json").write_text(json.dumps({
        "built_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "script": "scripts/build_vaers_anchored.py",
        "mid_clusters_from": "data/vaers/lattice_clusters (plain lattice, unchanged)",
        "plain_terms_sha256": plain_manifest["terms_sha256"],
        "plain_embeddings_sha256": plain_manifest["embeddings_sha256"],
        "anchor_source": "IMDRF Annex E release 2026, column 'Non-IMDRF Code' (MedDRA names), US/UK spelling normalised",
        "imdrf_workbook": str(bh.IMDRF_XLSX.relative_to(ROOT)),
        "rule": {"min_votes": MIN_VOTES, "min_share": MIN_SHARE, "else": "nearest anchor centroid (cosine)"},
        "validation": validation,
    }, indent=2))

    sym = pd.read_parquet(DATA / "vaers/hidden/symptoms.parquet", columns=["VAERS_ID", "pt"])
    rl = sym.assign(node_id="PT:" + sym["pt"].str.strip())[["VAERS_ID", "node_id"]]
    bh.support(rl, nodes, edges, "VAERS_ID").to_csv(
        DATA / "vaers/hidden/lattice_vaers_clusters_anchored_support.csv", index=False)
    print(f"[vaers_clusters_anchored] {checks['n_nodes']} nodes, {checks['n_edges']} edges "
          f"({n_extra} secondary), valid; rules {checks['mid_clusters_by_rule']}")


if __name__ == "__main__":
    main()
