"""VAERS symptom-term cluster lattice (issue #3, decision V4): the alternative VAERS hierarchy for experiment X5.

Leaves are the distinct MedDRA preferred terms (PTs) that VAERS reports carry (SYMPTOM1-5, public in the VAERS files).
Each term is embedded with a fixed sentence-embedding model; one Ward hierarchical clustering tree is cut at two levels
(N_TOP ~ the 27 MedDRA SOCs, N_MID ~ the 337 HLGTs). Cuts of one tree nest, so the result is a tree:
    PT  <=  mid group  <=  top group  <=  TOP
Group labels name the term nearest to the group centroid (a reading aid, not MedDRA content).

Outputs (local until Chenyang confirms that the PT names may be committed; see STATE.md V4):
  data/vaers/lattice_clusters/{nodes,edges,mapping}.csv, checks.json, MANIFEST.json
  data/vaers/hidden/lattice_vaers_clusters_support.csv   per-node report counts (hidden: they reveal answers)
The term list comes from data/vaers/hidden/symptoms.parquet (run scripts/build_tables.py vaers first).
MedDRA hierarchy files are never used here.

Usage: python scripts/build_vaers_clusters.py
"""

import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = DATA / "vaers/lattice_clusters"
MODEL = "BAAI/bge-small-en-v1.5"
N_TOP, N_MID = 27, 300
TOP = "TOP"

_spec = importlib.util.spec_from_file_location("build_hierarchies", ROOT / "scripts/build_hierarchies.py")
bh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bh)


def embed(terms: list[str]) -> np.ndarray:
    from fastembed import TextEmbedding  # ONNX runtime, CPU; deterministic for a fixed model file
    model = TextEmbedding(MODEL)
    x = np.asarray(list(model.embed(terms, batch_size=256)), dtype=np.float64)
    return x / np.linalg.norm(x, axis=1, keepdims=True)


def nearest_label(x: np.ndarray, terms: np.ndarray, members: np.ndarray) -> str:
    c = x[members].mean(axis=0)
    return str(terms[members][np.argmax(x[members] @ c)])


def main() -> None:
    sym = pd.read_parquet(DATA / "vaers/hidden/symptoms.parquet", columns=["VAERS_ID", "pt"])
    sym["pt"] = sym["pt"].str.strip()
    terms = np.array(sorted(sym["pt"].unique()))
    print(f"{len(terms)} distinct terms; embedding with {MODEL}", flush=True)
    x = embed(list(terms))

    z = linkage(x, method="ward")  # deterministic for fixed input order
    top = fcluster(z, N_TOP, criterion="maxclust")
    mid = fcluster(z, N_MID, criterion="maxclust")
    assert pd.Series(top).groupby(mid).nunique().max() == 1, "mid groups must nest in top groups"

    # stable ids: order groups by their first term alphabetically
    top_ids = {g: f"T{i:02d}" for i, g in enumerate(pd.Series(terms).groupby(top).min().sort_values().index, 1)}
    mid_ids = {}
    for g, first in pd.Series(terms).groupby(mid).min().sort_values().items():
        t = top_ids[top[mid == g][0]]
        mid_ids[g] = f"{t}.M{sum(v.startswith(t) for v in mid_ids.values()) + 1:03d}"

    nodes = [{"node_id": TOP, "label": "All symptom terms", "level": 0}]
    edges = []
    for g, nid in top_ids.items():
        nodes.append({"node_id": nid, "label": nearest_label(x, terms, np.flatnonzero(top == g)), "level": 1})
        edges.append({"child": nid, "parent": TOP})
    for g, nid in mid_ids.items():
        nodes.append({"node_id": nid, "label": nearest_label(x, terms, np.flatnonzero(mid == g)), "level": 2})
        edges.append({"child": nid, "parent": nid.split(".")[0]})
    for t, g in zip(terms, mid):
        nodes.append({"node_id": f"PT:{t}", "label": t, "level": 3})
        edges.append({"child": f"PT:{t}", "parent": mid_ids[g]})
    nodes = pd.DataFrame(nodes).assign(source=f"Ward clusters of {MODEL} embeddings", status="")
    edges = pd.DataFrame(edges).assign(placement="primary")
    mapping = pd.DataFrame({"raw_value": terms, "node_id": [f"PT:{t}" for t in terms], "method": "exact PT name"})

    checks = bh.validate(nodes, edges)
    if not checks["valid"]:
        raise SystemExit(f"structural check failed: {checks}")
    sizes = pd.Series(mid).value_counts()
    checks["mid_group_size"] = {"min": int(sizes.min()), "median": int(sizes.median()), "max": int(sizes.max())}
    checks["top_group_size"] = {k: int(v) for k, v in pd.Series(top).map(top_ids).value_counts().sort_index().items()}

    OUT.mkdir(parents=True, exist_ok=True)
    nodes.to_csv(OUT / "nodes.csv", index=False)
    edges.sort_values(["parent", "child"]).to_csv(OUT / "edges.csv", index=False)
    mapping.to_csv(OUT / "mapping.csv", index=False)
    (OUT / "checks.json").write_text(json.dumps(checks, indent=2))
    import fastembed
    import onnxruntime
    import scipy
    (OUT / "MANIFEST.json").write_text(json.dumps({
        "built_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "script": "scripts/build_vaers_clusters.py",
        "model": MODEL, "embedding_runtime": f"fastembed {fastembed.__version__}, onnxruntime {onnxruntime.__version__}",
        "normalised": True, "clustering": f"scipy {scipy.__version__} linkage(method='ward'), fcluster maxclust",
        "n_top": N_TOP, "n_mid": N_MID, "n_terms": len(terms),
        "terms_sha256": hashlib.sha256("\n".join(terms).encode()).hexdigest(),
        "embeddings_sha256": hashlib.sha256(np.round(x, 6).tobytes()).hexdigest(),
        "seed": "none needed (Ward linkage and fcluster are deterministic)",
    }, indent=2))

    rl = sym.assign(node_id="PT:" + sym["pt"])[["VAERS_ID", "node_id"]]
    bh.support(rl, nodes, edges, "VAERS_ID").to_csv(DATA / "vaers/hidden/lattice_vaers_clusters_support.csv",
                                                     index=False)
    print(f"[vaers_clusters] {checks['n_nodes']} nodes ({N_TOP} top, {N_MID} mid, {len(terms)} terms), valid; "
          f"mid group size {checks['mid_group_size']}")


if __name__ == "__main__":
    main()
