"""Small-scale end-to-end test of the reference cube on public MAUDE FRN reports.

Pipeline (all local, no LLM, no external API calls after the data fetch):
  1. split reports 40% train / 60% eval (seed 0)
  2. extractor: TF-IDF + logistic regression per leaf concept, trained on the train split with the
     hidden product-problem codes. This is a stand-in for the LLM extractor (none is configured);
     its score is the fact probability q.
  3. build the cube on the eval split (concept lattice below, quarter bins, manufacturer attribute)
  4. generate count / Boolean / trend queries; ground truth from the hidden codes on the eval split
  5. compare with BM25 and dense (bge-small-en-v1.5, local) top-k retrieval baselines

Usage: python scripts/run_small_eval.py [--data data/raw/maude_frn_2020_2024.jsonl]
Writes results/small_eval.json and prints tables.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cuberag import (C, Audit, Calendar, Count, Cube, Fact, Lattice, PAnd, PNot, POr, Report,  # noqa: E402
                     Series, Slice, Slope, evaluate)
from cuberag.query import compile_query, ppi_moments, raw_moments  # noqa: E402

# ------------------------------------------------------------------ provisional lattice
# Hand-made grouping of the most frequent FDA device-problem terms in this sample. It is NOT the
# official FDA/IMDRF hierarchy (task 4 of STUDENT_START.md replaces it). Two leaves have two parents.
GROUPS = {
    "Flow or Infusion Problem": ["Excess Flow or Over-Infusion", "Improper Flow or Infusion",
                                 "Insufficient Flow or Under Infusion", "Obstruction of Flow", "Failure to Infuse",
                                 "Infusion or Flow Problem", "Inaccurate Delivery", "Volume Accuracy Problem",
                                 "Pressure Problem", "Filling Problem", "Fluid/Blood Leak"],
    "Alarm Problem": ["Device Alarm System", "False Alarm", "Defective Alarm"],
    "Material Integrity Problem": ["Crack", "Break", "Corroded", "Deformation Due to Compressive Stress",
                                   "Peeled/Delaminated", "Naturally Worn", "Fluid/Blood Leak"],
    "Mechanical Problem (group)": ["Physical Resistance/Sticking", "Mechanical Problem", "Mechanics Altered",
                                   "Misassembled", "Failure to Align"],
    "Electrical or Power Problem": ["Circuit Failure", "Battery Problem", "Complete Loss of Power",
                                    "Electrical /Electronic Property Problem"],
    "Sensing or Signal Problem": ["Device Sensing Problem", "Failure to Read Input Signal", "Failure to Sense",
                                  "Calibration Problem", "Failure to Calibrate", "False Alarm"],
    "Display Problem": ["Display Difficult to Read", "Display or Visual Feedback Problem", "No Display/Image"],
    "Contamination Problem": ["Contamination"],
}
TOP = "Device Problem"
# natural-language query text for the retrieval baselines (what a user would type)
QTEXT = {
    "Flow or Infusion Problem": "flow or infusion problem over-infusion under-infusion occlusion",
    "Alarm Problem": "alarm problem",
    "Material Integrity Problem": "crack break corrosion broken damaged material",
    "Mechanical Problem (group)": "mechanical problem sticking misassembled",
    "Electrical or Power Problem": "electrical or power problem battery circuit loss of power",
    "Sensing or Signal Problem": "sensing or signal problem sensor calibration",
    "Display Problem": "display problem screen",
    "Contamination Problem": "contamination fluid ingress",
    TOP: "device problem",
}


def build_lattice() -> tuple[Lattice, list[str]]:
    edges = [(leaf, g) for g, leaves in GROUPS.items() for leaf in leaves]
    edges += [(g, TOP) for g in GROUPS]
    leaves = sorted({l for ls in GROUPS.values() for l in ls})
    return Lattice(edges, top=TOP), leaves


def mfr_group(m: str) -> str:
    for key in ("CAREFUSION", "BAXTER", "SMITHS", "MEDTRONIC"):
        if key in m:
            return key
    return "OTHER"


def tokenize(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


class BM25:
    def __init__(self, docs: list[list[str]], k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.tf = [Counter(d) for d in docs]
        self.dl = np.array([len(d) for d in docs], float)
        self.avg = self.dl.mean()
        df = Counter(w for d in self.tf for w in d)
        n = len(docs)
        self.idf = {w: math.log(1 + (n - c + .5) / (c + .5)) for w, c in df.items()}

    def scores(self, q: list[str]) -> np.ndarray:
        s = np.zeros(len(self.tf))
        for w in set(q):
            if w not in self.idf:
                continue
            f = np.array([t.get(w, 0) for t in self.tf], float)
            s += self.idf[w] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.dl / self.avg))
        return s


def ranking_metrics(ranked: list[int], rel: set[int], ks=(10, 100)) -> dict:
    out = {f"recall@{k}": len(set(ranked[:k]) & rel) / len(rel) for k in ks}
    R = len(rel)
    out["r_precision"] = len(set(ranked[:R]) & rel) / R
    rr = 0.0
    for i, d in enumerate(ranked):
        if d in rel:
            rr = 1 / (i + 1)
            break
    out["mrr"] = rr
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data/raw/maude_frn_2020_2024.jsonl"))
    ap.add_argument("--audit-n", type=int, default=150)
    ap.add_argument("--audit-reps", type=int, default=200)
    ap.add_argument("--emit", type=float, default=0.05, help="emit a fact if q >= this")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)
    t0 = time.time()

    rows = [json.loads(l) for l in open(args.data, encoding="utf-8")]
    lat, leaves = build_lattice()
    for r in rows:
        r["labels"] = sorted(set(r["hidden_product_problems"]) & set(leaves))
        y, mo = int(r["date_received"][:4]), int(r["date_received"][4:6])
        r["bin"] = (y - 2020) * 4 + (mo - 1) // 3
        r["mfr"] = mfr_group(r["manufacturer"])
    perm = rng.permutation(len(rows))
    ntr = int(0.4 * len(rows))
    train = [rows[i] for i in perm[:ntr]]
    ev = [rows[i] for i in perm[ntr:]]

    # ---------------- extractor (stand-in for the LLM)
    vec = TfidfVectorizer(ngram_range=(1, 2), min_df=3, max_features=50000, sublinear_tf=True)
    Xtr = vec.fit_transform([r["text"] for r in train])
    Xev = vec.transform([r["text"] for r in ev])
    models, skipped = {}, []
    for leaf in leaves:
        ytr = np.array([leaf in r["labels"] for r in train], int)
        if ytr.sum() < 8:
            skipped.append(leaf)
            continue
        models[leaf] = LogisticRegression(C=4.0, max_iter=2000).fit(Xtr, ytr)
    Q = {leaf: m.predict_proba(Xev)[:, 1] for leaf, m in models.items()}

    # ---------------- cube on the eval split
    cal = Calendar(20, [f"{2020 + b // 4}Q{b % 4 + 1}" for b in range(20)],
                   levels={"year": [b // 4 for b in range(20)]})
    reports = [Report(r["id"], r["bin"], (("mfr", r["mfr"]),)) for r in ev]
    facts, fid = [], 0
    for i, r in enumerate(ev):
        for leaf, q in Q.items():
            if q[i] >= args.emit:
                facts.append(Fact(fid, r["id"], leaf, float(q[i])))
                fid += 1
    cube = Cube(lat, cal, reports, facts)
    t_build = time.time() - t0
    labels = {r["id"]: set(r["labels"]) for r in ev}

    def truth(pred, rid) -> int:
        ls = labels[rid]
        if isinstance(pred, C):
            return int(any(lat.leq(l, pred.concept) for l in ls))
        if isinstance(pred, PAnd):
            return truth(pred.a, rid) & truth(pred.b, rid)
        if isinstance(pred, POr):
            return truth(pred.a, rid) | truth(pred.b, rid)
        return 1 - truth(pred.a, rid)

    # extractor quality on eval (per leaf, threshold 0.5)
    ext = {}
    for leaf in models:
        y = np.array([leaf in r["labels"] for r in ev])
        p = Q[leaf] >= .5
        tp = (y & p).sum()
        ext[leaf] = {"prev": int(y.sum()), "se": float(tp / max(y.sum(), 1)),
                     "ppv": float(tp / max(p.sum(), 1)), "brier": float(np.mean((Q[leaf] - y) ** 2))}

    # ---------------- baselines: BM25 and dense
    idx_of = {r["id"]: i for i, r in enumerate(ev)}
    bm25 = BM25([tokenize(r["text"]) for r in ev])
    dense = None
    try:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        from sentence_transformers import SentenceTransformer
        st_model = SentenceTransformer("BAAI/bge-small-en-v1.5", device="cpu")
        st_model.max_seq_length = 256
        cache = ROOT / "data" / f"emb_bge_small_{len(ev)}_{args.seed}.npy"
        if cache.exists():
            E = np.load(cache)
        else:
            E = st_model.encode([r["text"] for r in ev], batch_size=32, normalize_embeddings=True,
                                show_progress_bar=False)
            np.save(cache, E)
        dense = (st_model, E)
        dense_name = "dense (bge-small-en-v1.5, local)"
    except Exception as e:  # local fallback
        print("dense model unavailable, falling back to TF-IDF+SVD:", e)
        from sklearn.decomposition import TruncatedSVD
        svd = TruncatedSVD(256, random_state=0).fit(Xev)
        E = svd.transform(Xev)
        E /= np.linalg.norm(E, axis=1, keepdims=True) + 1e-12
        dense = (("svd", vec, svd), E)
        dense_name = "dense fallback (TF-IDF+SVD)"

    def dense_scores(text: str) -> np.ndarray:
        model, E = dense
        if isinstance(model, tuple):
            _, v, s = model
            qv = s.transform(v.transform([text]))[0]
            qv /= np.linalg.norm(qv) + 1e-12
        else:
            qv = model.encode(["Represent this sentence for searching relevant passages: " + text],
                              normalize_embeddings=True)[0]
        return E @ qv

    def qtext(pred) -> str:
        if isinstance(pred, C):
            return QTEXT.get(pred.concept, pred.concept)
        if isinstance(pred, (PAnd, POr)):
            return qtext(pred.a) + " " + qtext(pred.b)
        return ""  # negation cannot be expressed in a bag-of-words query

    # ---------------- queries
    concepts = [l for l in lat.nodes if l != TOP]
    eval_prev = {l: sum(truth(C(l), r["id"]) for r in ev) for l in concepts}
    concepts = sorted([l for l in concepts if eval_prev[l] >= 15 and (l in GROUPS or l in models)])
    queries = []
    for l in concepts:
        queries.append(("count", C(l), Slice(), f"{l} | all"))
        for y in range(5):
            queries.append(("count", C(l), Slice((4 * y, 4 * y + 3)), f"{l} | {2020 + y}"))
        for m in ("CAREFUSION", "BAXTER", "SMITHS"):
            queries.append(("count", C(l), Slice.of(None, mfr=m), f"{l} | mfr={m}"))
    groups = [g for g in GROUPS if g in concepts]
    for i, a in enumerate(groups):
        for b in groups[i + 1:]:
            queries.append(("bool", PAnd(C(a), C(b)), Slice(), f"{a} AND {b}"))
            queries.append(("bool", PAnd(C(a), PNot(C(b))), Slice(), f"{a} AND NOT {b}"))
            queries.append(("bool", PAnd(C(b), PNot(C(a))), Slice(), f"{b} AND NOT {a}"))

    # audit draws (SRSWOR from the eval split, single stratum)
    all_ids = [r["id"] for r in ev]
    strata = {r: "all" for r in all_ids}
    audits = [list(rng.choice(all_ids, args.audit_n, replace=False)) for _ in range(args.audit_reps)]

    results = []
    bm25_cache: dict[str, np.ndarray] = {}
    dense_cache: dict[str, np.ndarray] = {}
    for kind, pred, sl, name in queries:
        in_slice = [r["id"] for r in ev if sl.contains(cube.reports[r["id"]])]
        rel = {idx_of[r] for r in in_slice if truth(pred, r)}
        if len(rel) < 3:
            continue
        sl_idx = np.array([idx_of[r] for r in in_slice])
        txt = qtext(pred)
        if txt not in bm25_cache:
            bm25_cache[txt] = bm25.scores(tokenize(txt))
            dense_cache[txt] = dense_scores(txt)
        rank_b = list(sl_idx[np.argsort(-bm25_cache[txt][sl_idx], kind="stable")])
        rank_d = list(sl_idx[np.argsort(-dense_cache[txt][sl_idx], kind="stable")])
        nf = compile_query(Count(pred, sl), cube)
        rv = nf.comps[0].rv
        pis = np.array([rv.pi.get(all_ids[i], 0.0) for i in sl_idx])
        # cube ranking: by π, ties (incl. π = 0) broken by BM25
        order = np.lexsort((-bm25_cache[txt][sl_idx], -pis))
        rank_c = list(sl_idx[order])
        T = len(rel)
        res = {"kind": kind, "name": name, "truth": T, "slice_size": len(in_slice),
               "bm25": ranking_metrics(rank_b, rel), "dense": ranking_metrics(rank_d, rel),
               "cube": ranking_metrics(rank_c, rel)}
        hard = {sl_idx[i] for i in range(len(sl_idx)) if pis[i] >= .5}
        tp = len(hard & rel)
        res["cube_set"] = {"precision": tp / max(len(hard), 1), "recall": tp / T}
        counts = {f"topk_oracle_bm25@{k}": len(set(rank_b[:k]) & rel) for k in (10, 50)}
        counts |= {f"topk_oracle_dense@{k}": len(set(rank_d[:k]) & rel) for k in (10, 50)}
        theta, S = raw_moments(nf.comps)
        counts["cube_threshold"] = len(hard)
        counts["cube_raw"] = float(theta[0])
        raw_cover = abs(theta[0] - T) <= 1.96 * math.sqrt(S[0, 0])
        ests, covered, widths = [], 0, []
        for U in audits:
            th, Sp = ppi_moments(nf.comps, cube, Audit(U, strata, truth))
            se = math.sqrt(max(Sp[0, 0], 0))
            ests.append(th[0])
            covered += abs(th[0] - T) <= 1.96 * se
            widths.append(2 * 1.96 * se)
        counts["cube_ppi_mean_over_audits"] = float(np.mean(ests))
        res["counts"] = counts
        res["relerr"] = {k: abs(v - T) / T for k, v in counts.items()}
        res["relerr"]["cube_ppi"] = float(np.mean(np.abs(np.array(ests) - T) / T))
        res["coverage"] = {"raw": bool(raw_cover), "ppi": covered / len(audits),
                           "ppi_width_rel": float(np.mean(widths) / T)}
        if kind == "count" and isinstance(pred, C) and pred.concept in GROUPS and sl == Slice():
            kids = [k for k in lat.children[pred.concept]]
            res["no_bitmap_sum_children"] = float(sum(cube.count(C(k), sl).mean for k in kids))
            res["children_sum_truth"] = int(sum(sum(truth(C(k), r) for r in in_slice) for k in kids))
        results.append(res)

    # trends: yearly slope per concept
    trends = []
    for l in concepts:
        tser = np.array([sum(truth(C(l), r["id"]) for r in ev if r["bin"] // 4 == y) for y in range(5)], float)
        w = np.arange(1, 6) - 3.0
        w /= w @ w
        true_slope = float(w @ tser)
        q = Slope(Series(C(l), level="year"))
        raw = evaluate(q, cube)
        ppi_s = []
        cov = 0
        for U in audits[:50]:
            a = evaluate(q, cube, "ppi", Audit(U, strata, truth))
            ppi_s.append(a.value[0])
            cov += abs(a.value[0] - true_slope) <= 1.96 * a.se[0]
        topk = {}
        for k in (10, 50):
            for name_b, sc in (("bm25", bm25_cache), ("dense", dense_cache)):
                txt = qtext(C(l))
                if txt not in sc:
                    bm25_cache[txt] = bm25.scores(tokenize(txt))
                    dense_cache[txt] = dense_scores(txt)
                ser = []
                for y in range(5):
                    idx = np.array([idx_of[r["id"]] for r in ev if r["bin"] // 4 == y])
                    top = idx[np.argsort(-sc[txt][idx])[:k]]
                    ser.append(sum(truth(C(l), all_ids[i]) for i in top))
                topk[f"{name_b}@{k}"] = float(w @ np.array(ser, float))
        trends.append({"concept": l, "true_series": tser.tolist(), "true_slope": true_slope,
                       "cube_raw": float(raw.value[0]), "cube_ppi_mean": float(np.mean(ppi_s)),
                       "ppi_coverage": cov / 50, **{f"topk_{k}": v for k, v in topk.items()}})

    out = {"n_reports": len(rows), "n_train": len(train), "n_eval": len(ev), "n_facts": len(facts),
           "n_concepts": len(lat.nodes), "leaves_with_extractor": len(models), "skipped_leaves": skipped,
           "build_seconds": t_build, "total_seconds": time.time() - t0, "dense": dense_name,
           "audit_n": args.audit_n, "audit_reps": args.audit_reps, "emit": args.emit,
           "extractor": ext, "queries": results, "trends": trends}
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "small_eval.json").write_text(json.dumps(out, indent=1))
    summarize(out)


def summarize(out: dict) -> None:
    Rs = out["queries"]
    print(f"reports={out['n_reports']} eval={out['n_eval']} facts={out['n_facts']} queries={len(Rs)} "
          f"dense={out['dense']} build={out['build_seconds']:.1f}s total={out['total_seconds']:.1f}s")
    for kind in ("count", "bool", "all"):
        sub = [r for r in Rs if kind == "all" or r["kind"] == kind]
        if not sub:
            continue
        print(f"\n== {kind} queries (n={len(sub)}), median truth={np.median([r['truth'] for r in sub]):.0f}")
        print(f"{'ranking':10s} {'R@10':>6s} {'R@100':>6s} {'R-prec':>6s} {'MRR':>6s}")
        for m in ("bm25", "dense", "cube"):
            v = [np.mean([r[m][k] for r in sub]) for k in ("recall@10", "recall@100", "r_precision", "mrr")]
            print(f"{m:10s} " + " ".join(f"{x:6.3f}" for x in v))
        cs = [r["cube_set"] for r in sub]
        print(f"cube set (pi>=0.5): precision={np.mean([c['precision'] for c in cs]):.3f} "
              f"recall={np.mean([c['recall'] for c in cs]):.3f}")
        print("count median relative error:")
        for k in sub[0]["relerr"]:
            print(f"  {k:28s} {np.median([r['relerr'][k] for r in sub]):.3f}")
        print(f"95% CI coverage: raw={np.mean([r['coverage']['raw'] for r in sub]):.3f} "
              f"ppi={np.mean([r['coverage']['ppi'] for r in sub]):.3f} "
              f"(median rel. width {np.median([r['coverage']['ppi_width_rel'] for r in sub]):.2f})")
    nb = [r for r in Rs if "no_bitmap_sum_children" in r]
    if nb:
        print("\nno-bitmap ablation (parent = sum of children), median rel. error: "
              f"{np.median([abs(r['no_bitmap_sum_children'] - r['truth']) / r['truth'] for r in nb]):.3f} "
              f"vs bitmap {np.median([r['relerr']['cube_raw'] for r in nb]):.3f}")
    T = out["trends"]
    print(f"\n== trends (yearly OLS slope, {len(T)} concepts; slopes of the sample composition)")
    ts = np.array([t["true_slope"] for t in T])
    for k in ["cube_raw", "cube_ppi_mean"] + [k for k in T[0] if k.startswith("topk_")]:
        v = np.array([t[k] for t in T])
        nz = np.abs(ts) >= 1
        print(f"  {k:22s} sign acc (|true|>=1, n={nz.sum()}) {np.mean(np.sign(v[nz]) == np.sign(ts[nz])):.3f}  "
              f"median abs err {np.median(np.abs(v - ts)):.2f}")
    print(f"  ppi slope CI coverage {np.mean([t['ppi_coverage'] for t in T]):.3f}")


if __name__ == "__main__":
    main()
