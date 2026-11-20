"""Audit-design comparison and threshold baselines on the pilot (EXPERIMENTS.md Section 9).

Same data, split, lattice, cube and query set as scripts/run_small_eval.py (Section 8). Adds:
  1. audit designs for PPI (ALGEBRA.md Section 11), each with --reps replicate audits of size --audit-n:
       uniform   SRSWOR, one stratum (the Section 8 pilot)
       cell      strata = year × manufacturer group, proportional allocation
       score     strata = quantiles of a pre-audit score d_r, Neyman allocation (unweighted d_r)
       score_rare  same, d_r weighted by concept rarity (1/N̂_ℓ²: minimizes the summed relative variance)
       poisson   Poisson (IPW) sampling, p_r ∝ sqrt(d_r) (rarity-weighted), 20% uniform floor
     d_r = Σ_ℓ w_ℓ ê²_rℓ is the predicted squared residual of report r. ê² comes from a calibration of
     π on *cross-fitted train predictions* (tfidf extractor), or from π(1 − π) + 0.005 (proxy, for an
     extractor that was run on the eval split only). The design uses no eval labels.
  2. score-threshold retrievers (dense bge-small and BM25): keep every report with score ≥ τ_ℓ, τ_ℓ
     tuned on the train split per concept, with a counting reader (count all kept) and an oracle reader.
     Top-k oracle readers are kept for reference.

Usage:
  python scripts/run_audit_eval.py                          # tfidf stand-in extractor (as Section 8)
  python scripts/run_audit_eval.py --facts data/extract/<run>/facts_eval.jsonl --tag qwen3_4b
      [--train-facts data/extract/<run>/facts_train.jsonl]   # calibrated design instead of the proxy
Writes results/audit_eval_<tag>.json and prints the tables.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from cuberag import (C, Audit, Calendar, Count, Cube, Fact, PAnd, PNot, PoissonAudit, POr, Report,  # noqa: E402
                     Series, Slice, Slope, compile_query, draw_poisson, draw_stratified, evaluate,
                     neyman_allocation, poisson_probs, proportional_allocation, quantile_strata)
from cuberag.extract import load_facts  # noqa: E402
from cuberag.query import ppi_moments  # noqa: E402
from extract_llm import split_rows  # noqa: E402
from run_small_eval import BM25, GROUPS, QTEXT, TOP, build_lattice, mfr_group, tokenize  # noqa: E402

BANDS = [(3, 19), (20, 49), (50, 149), (150, 10 ** 9)]
BAND_NAMES = ["3–19", "20–49", "50–149", "≥150"]


def band_of(t: float) -> int:
    for i, (lo, hi) in enumerate(BANDS):
        if lo <= t <= hi:
            return i
    return -1


def fit_tfidf(train, ev, leaves, seed):
    """The Section 8 stand-in extractor (identical settings), plus 5-fold cross-fitted train scores."""
    vec = TfidfVectorizer(ngram_range=(1, 2), min_df=3, max_features=50000, sublinear_tf=True)
    Xtr = vec.fit_transform([r["text"] for r in train])
    Xev = vec.transform([r["text"] for r in ev])
    Qev, Qtr = {}, {}
    skf = StratifiedKFold(5, shuffle=True, random_state=seed)
    for leaf in leaves:
        ytr = np.array([leaf in r["labels"] for r in train], int)
        if ytr.sum() < 8:
            continue
        Qev[leaf] = LogisticRegression(C=4.0, max_iter=2000).fit(Xtr, ytr).predict_proba(Xev)[:, 1]
        cf = np.zeros(len(train))
        for a, b in skf.split(Xtr, ytr):
            cf[b] = LogisticRegression(C=4.0, max_iter=2000).fit(Xtr[a], ytr[a]).predict_proba(Xtr[b])[:, 1]
        Qtr[leaf] = cf
    return Qev, Qtr


def concept_pi(Q: dict, lat, concepts, n: int, emit: float) -> dict:
    """π_r(ℓ) as the cube computes it: 1 − Π (1 − q) over emitted leaf facts in ↓ℓ (one variable each)."""
    out = {}
    for l in concepts:
        none = np.ones(n)
        for leaf in lat.down(l):
            if leaf in Q:
                q = Q[leaf]
                none *= np.where(q >= emit, 1 - q, 1.0)
        out[l] = 1 - none
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data/raw/maude_frn_2020_2024.jsonl"))
    ap.add_argument("--facts", default=None, help="facts JSONL from scripts/extract_llm.py (eval split)")
    ap.add_argument("--train-facts", default=None,
                    help="optional facts JSONL of the same extractor on the train split (enables the calibrated design)")
    ap.add_argument("--simulate-se", type=float, default=None,
                    help="SENSITIVITY ANALYSIS ONLY: semi-synthetic extractor drawn from the hidden labels with this "
                         "sensitivity and PPV ≈ 0.8 (not a method result)")
    ap.add_argument("--tag", default="tfidf")
    ap.add_argument("--audit-n", type=int, default=150)
    ap.add_argument("--reps", type=int, default=1000)
    ap.add_argument("--emit", type=float, default=0.05)
    ap.add_argument("--strata", type=int, default=6, help="number of score strata")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    t0 = time.time()

    rows = [json.loads(l) for l in open(args.data, encoding="utf-8")]
    lat, leaves = build_lattice()
    for r in rows:
        r["labels"] = sorted(set(r["hidden_product_problems"]) & set(leaves))
        y, mo = int(r["date_received"][:4]), int(r["date_received"][4:6])
        r["bin"] = (y - 2020) * 4 + (mo - 1) // 3
        r["mfr"] = mfr_group(r["manufacturer"])
    train, ev = split_rows(rows, args.seed)
    n_ev = len(ev)
    ids = [r["id"] for r in ev]
    idx_of = {rid: i for i, rid in enumerate(ids)}

    # ---------------- extractor scores on eval (and cross-fitted on train, if available)
    if args.facts:
        Qev = {leaf: np.zeros(n_ev) for leaf in leaves}
        got = set()
        for e in load_facts(Path(args.facts)):
            if e.report_id in idx_of and e.concept in Qev:
                i = idx_of[e.report_id]
                Qev[e.concept][i] = max(Qev[e.concept][i], e.q)
                got.add(e.report_id)
        Qtr = None
        if args.train_facts:
            tr_idx = {r["id"]: i for i, r in enumerate(train)}
            Qtr = {leaf: np.zeros(len(train)) for leaf in leaves}
            for e in load_facts(Path(args.train_facts)):
                if e.report_id in tr_idx and e.concept in Qtr:
                    i = tr_idx[e.report_id]
                    Qtr[e.concept][i] = max(Qtr[e.concept][i], e.q)
        man = Path(args.facts).with_name(Path(args.facts).name.replace("facts_", "manifest_").replace(".jsonl", ".json"))
        manifest = json.loads(man.read_text()) if man.exists() else {}
        if manifest.get("reports_missing"):
            print(f"WARNING: {manifest['reports_missing']} eval reports have no extraction (treated as no facts)")
        extractor_name = f"facts:{args.facts}"
    elif args.simulate_se is not None:
        srng = np.random.default_rng(args.seed + 7)
        Qev, Qtr = {}, {}
        for leaf in leaves:
            for split, store in ((ev, Qev), (train, Qtr)):
                y = np.array([leaf in r["labels"] for r in split])
                prev = max(y.mean(), 1e-6)
                fp = min(args.simulate_se * prev * 0.25 / (1 - prev), 1.0)  # PPV = se·prev/(se·prev + fp·(1−prev)) = 0.8
                hit = np.where(y, srng.random(len(y)) < args.simulate_se, srng.random(len(y)) < fp)
                low = np.where(srng.random(len(y)) < 0.05, srng.uniform(0.05, 0.4, len(y)), 0.0)  # mostly no fact
                store[leaf] = np.where(hit, srng.uniform(0.55, 0.99, len(y)), low)
        manifest = {}
        extractor_name = f"SEMI-SYNTHETIC extractor from hidden labels (Se={args.simulate_se}, PPV≈0.8)"
    else:
        Qev, Qtr = fit_tfidf(train, ev, leaves, args.seed)
        manifest = {}
        extractor_name = "tfidf+LR stand-in (Section 8)"

    # ---------------- cube (as Section 8)
    cal = Calendar(20, [f"{2020 + b // 4}Q{b % 4 + 1}" for b in range(20)],
                   levels={"year": [b // 4 for b in range(20)]})
    reports = [Report(r["id"], r["bin"], (("mfr", r["mfr"]),)) for r in ev]
    facts, fid = [], 0
    for i, r in enumerate(ev):
        for leaf, q in Qev.items():
            if q[i] >= args.emit:
                facts.append(Fact(fid, r["id"], leaf, float(q[i])))
                fid += 1
    cube = Cube(lat, cal, reports, facts)
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

    ext = {}
    for leaf in leaves:
        y = np.array([leaf in labels[rid] for rid in ids])
        p = Qev.get(leaf, np.zeros(n_ev)) >= .5
        tp = (y & p).sum()
        ext[leaf] = {"prev": int(y.sum()), "se": float(tp / max(y.sum(), 1)), "ppv": float(tp / max(p.sum(), 1)),
                     "flagged": int(p.sum())}
    ext_mean = {"se": float(np.mean([v["se"] for v in ext.values()])),
                "ppv": float(np.mean([v["ppv"] for v in ext.values()])),
                "ppv_flagged_only": float(np.mean([v["ppv"] for v in ext.values() if v["flagged"]] or [0])),
                "micro_se": float(sum(v["se"] * v["prev"] for v in ext.values()) / sum(v["prev"] for v in ext.values())),
                "leaves_never_flagged": int(sum(v["flagged"] == 0 for v in ext.values()))}

    # ---------------- queries (identical generator to Section 8)
    concepts = [l for l in lat.nodes if l != TOP]
    eval_prev = {l: sum(truth(C(l), rid) for rid in ids) for l in concepts}
    concepts = sorted([l for l in concepts if eval_prev[l] >= 15 and (l in GROUPS or l in leaves)])
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

    # Linear functionals as columns: F[r, j] = f_rj (π restricted to the slice), Y[r, j] = y_rj.
    cols, F_cols, Y_cols = [], [], []
    for kind, pred, sl, name in queries:
        inside = np.array([sl.contains(cube.reports[rid]) for rid in ids])
        y = np.array([truth(pred, rid) for rid in ids], float) * inside
        if y.sum() < 3:
            continue
        rv = cube.count(pred, sl)
        f = np.array([rv.pi.get(rid, 0.0) for rid in ids]) * inside
        cols.append({"kind": kind, "name": name, "pred": pred, "sl": sl, "truth": float(y.sum()),
                     "slice_size": int(inside.sum())})
        F_cols.append(f)
        Y_cols.append(y)
    n_count = len(cols)
    year = np.array([r["bin"] // 4 for r in ev])
    w = ols_w = (np.arange(1, 6) - 3.0) / 10.0
    for l in concepts:
        rv = cube.count(C(l))
        pi = np.array([rv.pi.get(rid, 0.0) for rid in ids])
        y = np.array([truth(C(l), rid) for rid in ids], float)
        ts = float(sum(ols_w[k] * y[year == k].sum() for k in range(5)))
        cols.append({"kind": "slope", "name": f"{l} | yearly slope", "pred": C(l), "truth": ts,
                     "true_series": [float(y[year == k].sum()) for k in range(5)]})
        F_cols.append(w[year] * pi)
        Y_cols.append(w[year] * y)
    F, Y = np.array(F_cols).T, np.array(Y_cols).T
    E = Y - F
    T = Y.sum(axis=0)
    raw = F.sum(axis=0)
    print(f"[{time.time() - t0:.0f}s] eval={n_ev} facts={len(facts)} count/bool columns={n_count} "
          f"slope columns={len(cols) - n_count}")

    # ---------------- design-time predicted squared residuals d_r (no eval labels)
    design_concepts = concepts
    pi_ev = concept_pi(Qev, lat, design_concepts, n_ev, args.emit)
    if Qtr is not None:
        pi_tr = concept_pi(Qtr, lat, design_concepts, len(train), args.emit)
        lab_tr = {l: np.array([int(any(lat.leq(x, l) for x in r["labels"])) for r in train]) for l in design_concepts}
        g = {}
        for l in design_concepts:
            iso = IsotonicRegression(y_min=0, y_max=1, out_of_bounds="clip").fit(pi_tr[l], lab_tr[l])
            g[l] = iso.predict(pi_ev[l])
        e2 = {l: g[l] * (1 - pi_ev[l]) ** 2 + (1 - g[l]) * pi_ev[l] ** 2 for l in design_concepts}
        Nhat = {l: max(g[l].sum(), 5.0) for l in design_concepts}
        design_basis = ("isotonic calibration of train-split scores" if args.facts else
                        "isotonic calibration of cross-fitted train scores")
    else:
        e2 = {l: pi_ev[l] * (1 - pi_ev[l]) + 0.005 for l in design_concepts}
        Nhat = {l: max(pi_ev[l].sum() + 0.005 * n_ev, 5.0) for l in design_concepts}
        design_basis = "proxy: pi(1-pi) + 0.005 (no train extraction)"
    d_plain = sum(e2[l] for l in design_concepts)
    d_rare = sum(e2[l] / Nhat[l] ** 2 for l in design_concepts)

    # ---------------- designs
    n = args.audit_n
    designs = {}
    designs["uniform"] = {"type": "strat", "strata": np.array(["all"] * n_ev),
                          "alloc": {"all": n}}
    cell = np.array([f"{y}|{r['mfr']}" for y, r in zip(year, ev)])
    Nh = {h: int((cell == h).sum()) for h in np.unique(cell)}
    designs["cell"] = {"type": "strat", "strata": cell, "alloc": proportional_allocation(Nh, n)}
    for name, d in (("score", d_plain), ("score_rare", d_rare)):
        st = quantile_strata({rid: float(v) for rid, v in zip(ids, d)}, args.strata, zero_stratum=False)
        lab = np.array([st[rid] for rid in ids])
        Nh = {h: int((lab == h).sum()) for h in np.unique(lab)}
        Sh = {h: float(np.sqrt(d[lab == h].mean())) for h in Nh}
        designs[name] = {"type": "strat", "strata": lab, "alloc": neyman_allocation(Nh, Sh, n)}
    # DIAGNOSTIC ONLY (uses eval labels, violates the design rule of ALGEBRA 11.1): strata and Neyman
    # allocation from the true squared residuals of the count columns. Upper bound on what a score design can gain.
    d_or = (E[:, :n_count] ** 2 / np.maximum(T[:n_count], 1) ** 2).sum(axis=1)
    st = quantile_strata({rid: float(v) for rid, v in zip(ids, d_or)}, args.strata, zero_stratum=True)
    lab = np.array([st[rid] for rid in ids])
    Nh = {h: int((lab == h).sum()) for h in np.unique(lab)}
    Sh = {h: float(np.sqrt(d_or[lab == h].mean())) for h in Nh}
    designs["oracle_diag"] = {"type": "strat", "strata": lab, "alloc": neyman_allocation(Nh, Sh, n)}
    p = poisson_probs({rid: float(np.sqrt(v)) for rid, v in zip(ids, d_rare)}, n, floor=0.2)
    designs["poisson"] = {"type": "poisson", "p": np.array([p[rid] for rid in ids])}

    # exact design variances (population formulas; no Monte Carlo noise)
    for dn, D in designs.items():
        if D["type"] == "strat":
            V = np.zeros(E.shape[1])
            for h, nh in D["alloc"].items():
                m = D["strata"] == h
                Nh_ = m.sum()
                if Nh_ > 1 and nh < Nh_:
                    V += Nh_ ** 2 * (1 - nh / Nh_) / nh * E[m].var(axis=0, ddof=1)
        else:
            pp = D["p"]
            V = ((1 - pp) / pp) @ (E ** 2)
        D["true_var"] = V

    # ---------------- replicate audits (vectorized; cross-checked against cuberag.ppi_moments below)
    rng = np.random.default_rng(args.seed + 1)
    rep = {}
    strata_maps = {}
    for dn, D in designs.items():
        est = np.zeros((args.reps, E.shape[1]))
        var = np.zeros_like(est)
        sizes = []
        if D["type"] == "strat":
            members = {h: np.flatnonzero(D["strata"] == h) for h in D["alloc"]}
        for b in range(args.reps):
            th = raw.copy()
            v = np.zeros(E.shape[1])
            if D["type"] == "strat":
                tot = 0
                for h, nh in D["alloc"].items():
                    mem = members[h]
                    U = mem[rng.choice(len(mem), nh, replace=False)]
                    Nh_ = len(mem)
                    th += Nh_ / nh * E[U].sum(axis=0)
                    if nh > 1:
                        v += Nh_ ** 2 * (1 - nh / Nh_) / nh * E[U].var(axis=0, ddof=1)
                    tot += nh
                sizes.append(tot)
            else:
                pp = D["p"]
                U = np.flatnonzero(rng.random(n_ev) < pp)
                th += (E[U] / pp[U, None]).sum(axis=0)
                v += (((1 - pp[U]) / pp[U] ** 2)[:, None] * E[U] ** 2).sum(axis=0)
                sizes.append(len(U))
            est[b], var[b] = th, v
        rep[dn] = (est, var, np.array(sizes))

    # cross-check: library estimator on a few draws equals the vectorized one
    chk_rng = np.random.default_rng(99)
    oracle = lambda pred, rid: truth(pred, rid)  # noqa: E731
    max_diff = 0.0
    for dn, D in designs.items():
        for _ in range(2):
            if D["type"] == "strat":
                smap = dict(zip(ids, D["strata"]))
                U = draw_stratified(smap, D["alloc"], chk_rng)
                audit = Audit(U, smap, oracle)
                Ui = [idx_of[u] for u in U]
                th = raw.copy()
                for h, nh in D["alloc"].items():
                    sel = [i for i in Ui if D["strata"][i] == h]
                    th += (D["strata"] == h).sum() / nh * E[sel].sum(axis=0)
            else:
                pmap = dict(zip(ids, D["p"]))
                U = draw_poisson(pmap, chk_rng)
                audit = PoissonAudit(U, pmap, oracle)
                Ui = [idx_of[u] for u in U]
                th = raw + (E[Ui] / D["p"][Ui, None]).sum(axis=0)
            for j in list(range(0, n_count, max(n_count // 6, 1))) + [n_count]:
                c = cols[j]
                if c["kind"] == "slope":
                    a = evaluate(Slope(Series(c["pred"], level="year")), cube, "ppi", audit)
                    lib = a.value[0]
                else:
                    lib = ppi_moments(compile_query(Count(c["pred"], c["sl"]), cube).comps, cube, audit)[0][0]
                max_diff = max(max_diff, abs(lib - th[j]))
    print(f"[{time.time() - t0:.0f}s] library vs vectorized PPI: max |diff| = {max_diff:.2e}")
    assert max_diff < 1e-6

    # ---------------- per-design summaries
    is_cnt = np.array([c["kind"] != "slope" for c in cols])
    bands = np.array([band_of(c["truth"]) if c["kind"] != "slope" else -1 for c in cols])
    summ = {}
    for dn, (est, var, sizes) in rep.items():
        se = np.sqrt(np.clip(var, 0, None))
        cover = np.abs(est - T) <= 1.96 * se
        relerr = np.abs(est - T) / np.where(np.abs(T) > 0, np.abs(T), 1)
        s = {"audit_size_mean": float(sizes.mean()), "audit_size_sd": float(sizes.std()),
             "median_relerr_single_audit": float(np.median(relerr[:, is_cnt].mean(axis=0))),
             "median_relerr_mean_over_audits": float(np.median(np.abs(est[:, is_cnt].mean(axis=0) - T[is_cnt]) / T[is_cnt])),
             "coverage": float(cover[:, is_cnt].mean()),
             "zero_width_rate": float((var[:, is_cnt] <= 1e-12).mean()),
             "median_true_relse": float(np.median(np.sqrt(designs[dn]["true_var"][is_cnt]) / T[is_cnt])),
             "bands": {}}
        for bi, bn in enumerate(BAND_NAMES):
            m = bands == bi
            s["bands"][bn] = {"queries": int(m.sum()),
                              "relerr": float(np.median(relerr[:, m].mean(axis=0))),
                              "coverage": float(cover[:, m].mean()),
                              "zero_width_rate": float((var[:, m] <= 1e-12).mean()),
                              "true_relse": float(np.median(np.sqrt(designs[dn]["true_var"][m]) / T[m])),
                              "median_rel_width": float(np.median((2 * 1.96 * se[:, m]).mean(axis=0) / T[m]))}
        sl = ~is_cnt
        big = sl & (np.abs(T) >= 1)
        s["slope"] = {"coverage": float(cover[:, sl].mean()),
                      "sign_acc_single_audit": float((np.sign(est[:, big]) == np.sign(T[big])).mean()),
                      "sign_acc_mean_over_audits": float((np.sign(est[:, big].mean(axis=0)) == np.sign(T[big])).mean()),
                      "median_abs_err": float(np.median(np.abs(est[:, sl] - T[sl]).mean(axis=0))),
                      "n_concepts": int(sl.sum()), "n_big": int(big.sum())}
        summ[dn] = s
    raw_relerr = np.abs(raw - T) / np.where(np.abs(T) > 0, np.abs(T), 1)
    raw_summary = {"median_relerr": float(np.median(raw_relerr[is_cnt])),
                   "median_ratio": float(np.median(raw[is_cnt] / T[is_cnt])),
                   "bands": {bn: float(np.median(raw_relerr[bands == bi])) for bi, bn in enumerate(BAND_NAMES)}}

    # ---------------- retrieval baselines: score threshold (τ tuned on train) and top-k
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from sentence_transformers import SentenceTransformer
    st_model = SentenceTransformer("BAAI/bge-small-en-v1.5", device="cpu")
    st_model.max_seq_length = 256

    def embed(rs, tag):
        cache = ROOT / "data" / f"emb_bge_small_{tag}_{len(rs)}_{args.seed}.npy"
        legacy = ROOT / "data" / f"emb_bge_small_{len(rs)}_{args.seed}.npy"  # Section 8 eval cache
        if tag == "eval" and legacy.exists():
            return np.load(legacy)
        if cache.exists():
            return np.load(cache)
        Em = st_model.encode([r["text"] for r in rs], batch_size=32, normalize_embeddings=True, show_progress_bar=False)
        np.save(cache, Em)
        return Em

    Eev, Etr = embed(ev, "eval"), embed(train, "train")
    bm_ev, bm_tr = BM25([tokenize(r["text"]) for r in ev]), BM25([tokenize(r["text"]) for r in train])

    def qtext(l):
        return QTEXT.get(l, l)

    qv = {l: st_model.encode(["Represent this sentence for searching relevant passages: " + qtext(l)],
                             normalize_embeddings=True)[0] for l in concepts}
    S = {"dense": ({l: Etr @ qv[l] for l in concepts}, {l: Eev @ qv[l] for l in concepts}),
         "bm25": ({l: bm_tr.scores(tokenize(qtext(l))) for l in concepts},
                  {l: bm_ev.scores(tokenize(qtext(l))) for l in concepts})}
    ytr = {l: np.array([int(any(lat.leq(x, l) for x in r["labels"])) for r in train]) for l in concepts}
    yev = {l: np.array([truth(C(l), rid) for rid in ids]) for l in concepts}

    def tune(s, y):
        """τ_F1 maximizes the F1 of {s ≥ τ}; τ_count makes #{s ≥ τ} equal the true train count."""
        order = np.argsort(-s)
        tp = np.cumsum(y[order])
        k = np.arange(1, len(s) + 1)
        f1 = 2 * tp / (k + y.sum())
        kb = int(np.argmax(f1))
        cnt = int(y.sum())
        return float(s[order][kb]), float(s[order][max(cnt - 1, 0)])

    tau = {m: {l: tune(S[m][0][l], ytr[l]) for l in concepts} for m in S}

    def retrieved(m, pred, which):
        if isinstance(pred, C):
            return S[m][1][pred.concept] >= tau[m][pred.concept][which]
        if isinstance(pred, PAnd):
            return retrieved(m, pred.a, which) & retrieved(m, pred.b, which)
        if isinstance(pred, POr):
            return retrieved(m, pred.a, which) | retrieved(m, pred.b, which)
        return ~retrieved(m, pred.a, which)  # set complement: a threshold retriever can express ¬

    def bow(pred):  # concepts named in a predicate (top-k query text drops negation, as in Section 8)
        if isinstance(pred, C):
            return [pred.concept]
        if isinstance(pred, (PAnd, POr)):
            return bow(pred.a) + bow(pred.b)
        return []

    base = {}
    for j in range(len(cols)):
        c = cols[j]
        out = {}
        if c["kind"] == "slope":
            l = c["pred"].concept
            for m in S:
                for which, wn in ((0, "f1"), (1, "count")):
                    kept = S[m][1][l] >= tau[m][l][which]
                    out[f"thr_{m}_{wn}_countall"] = float(sum(ols_w[k] * kept[year == k].sum() for k in range(5)))
                    out[f"thr_{m}_{wn}_oracle"] = float(sum(ols_w[k] * (kept & (yev[l] == 1))[year == k].sum()
                                                            for k in range(5)))
                for k_ in (10, 50):
                    ser = []
                    for k in range(5):
                        ix = np.flatnonzero(year == k)
                        top = ix[np.argsort(-S[m][1][l][ix], kind="stable")[:k_]]
                        ser.append(yev[l][top].sum())
                    out[f"topk_{m}@{k_}_oracle"] = float(ols_w @ np.array(ser, float))
        else:
            inside = np.array([c["sl"].contains(cube.reports[rid]) for rid in ids])
            yq = Y[:, j] > 0
            for m in S:
                for which, wn in ((0, "f1"), (1, "count")):
                    kept = retrieved(m, c["pred"], which) & inside
                    out[f"thr_{m}_{wn}_countall"] = float(kept.sum())
                    out[f"thr_{m}_{wn}_oracle"] = float((kept & yq).sum())
                sc = sum(S[m][1][l] for l in bow(c["pred"])) if m == "dense" else \
                    bm_ev.scores(tokenize(" ".join(qtext(l) for l in bow(c["pred"]))))
                ix = np.flatnonzero(inside)
                order = ix[np.argsort(-sc[ix], kind="stable")]
                for k_ in (10, 50):
                    out[f"topk_{m}@{k_}_oracle"] = float(yq[order[:k_]].sum())
        base_j = {k: v for k, v in out.items()}
        c["baselines"] = base_j
        base[j] = base_j
    bkeys = list(base[0].keys())
    bsum = {}
    for k in bkeys:
        vals = np.array([base[j][k] for j in range(n_count)])
        re_ = np.abs(vals - T[:n_count]) / T[:n_count]
        sl_vals = np.array([base[j][k] for j in range(n_count, len(cols))])
        bigs = np.abs(T[n_count:]) >= 1
        bsum[k] = {"median_relerr": float(np.median(re_)),
                   "bands": {bn: float(np.median(re_[bands[:n_count] == bi])) for bi, bn in enumerate(BAND_NAMES)},
                   "slope_sign_acc": float((np.sign(sl_vals[bigs]) == np.sign(T[n_count:][bigs])).mean())}
    tau_quality = {m: {"train_f1_mean": float(np.mean([
        (lambda s, y, t: 2 * ((s >= t) & (y == 1)).sum() / max((s >= t).sum() + y.sum(), 1))(S[m][0][l], ytr[l], tau[m][l][0])
        for l in concepts])), "eval_f1_mean": float(np.mean([
        (lambda s, y, t: 2 * ((s >= t) & (y == 1)).sum() / max((s >= t).sum() + y.sum(), 1))(S[m][1][l], yev[l], tau[m][l][0])
        for l in concepts]))} for m in S}

    out = {"tag": args.tag, "extractor": extractor_name, "extractor_manifest": manifest, "emit": args.emit,
           "n_eval": n_ev, "n_facts": len(facts), "audit_n": n, "reps": args.reps, "design_basis": design_basis,
           "extractor_quality_mean": ext_mean, "extractor_quality": ext,
           "designs": {dn: {"type": D["type"], "alloc": {str(k): int(v) for k, v in D.get("alloc", {}).items()},
                            "p_min": float(D["p"].min()) if "p" in D else None,
                            "p_max": float(D["p"].max()) if "p" in D else None} for dn, D in designs.items()},
           "raw": raw_summary, "ppi": summ, "baselines": bsum, "threshold_f1": tau_quality,
           "library_crosscheck_max_diff": max_diff, "n_count_queries": n_count,
           "n_slope_queries": len(cols) - n_count, "seconds": time.time() - t0,
           "queries": [{k: v for k, v in c.items() if k not in ("pred", "sl")} |
                       {"raw": float(raw[j]),
                        **{f"ppi_{dn}_true_se": float(math.sqrt(designs[dn]["true_var"][j])) for dn in designs}}
                       for j, c in enumerate(cols)]}
    (ROOT / "results").mkdir(exist_ok=True)
    path = ROOT / "results" / f"audit_eval_{args.tag}.json"
    path.write_text(json.dumps(out, indent=1))
    report(out)
    print(f"wrote {path} in {time.time() - t0:.0f}s")


def report(out: dict) -> None:
    q = out["extractor_quality_mean"]
    print(f"\nextractor {out['extractor']}: mean Se {q['se']:.2f}, mean PPV {q['ppv']:.2f} "
          f"(flagged leaves only {q['ppv_flagged_only']:.2f}), micro Se {q['micro_se']:.2f}, "
          f"never flagged {q['leaves_never_flagged']}; facts {out['n_facts']}")
    r = out["raw"]
    print(f"raw Σπ: median rel err {r['median_relerr']:.3f}, median Σπ/truth {r['median_ratio']:.2f}; bands "
          + ", ".join(f"{k} {v:.2f}" for k, v in r["bands"].items()))
    print(f"\nPPI designs (n={out['audit_n']}, {out['reps']} replicate audits each; design basis: {out['design_basis']})")
    print(f"{'design':11s} {'size':>6s} {'relerr':>7s} {'meanAud':>7s} {'cover':>6s} {'trueSE':>7s} "
          + " ".join(f"{b:>15s}" for b in BAND_NAMES) + "  slope cov/sign1")
    for dn, s in out["ppi"].items():
        bs = " ".join(f"{s['bands'][b]['relerr']:5.2f}/{s['bands'][b]['coverage']:4.2f}/{s['bands'][b]['true_relse']:4.2f}"
                      for b in BAND_NAMES)
        print(f"{dn:11s} {s['audit_size_mean']:6.1f} {s['median_relerr_single_audit']:7.3f} "
              f"{s['median_relerr_mean_over_audits']:7.3f} {s['coverage']:6.3f} {s['median_true_relse']:7.3f} {bs}"
              f"  {s['slope']['coverage']:.2f}/{s['slope']['sign_acc_single_audit']:.2f}")
    print("  (band cells: relerr / coverage / exact design rel. SE)")
    print("\nretrieval baselines (median rel err; bands; slope sign acc)")
    for k, v in out["baselines"].items():
        print(f"  {k:28s} {v['median_relerr']:6.3f}  " + " ".join(f"{x:5.2f}" for x in v["bands"].values())
              + f"  sign {v['slope_sign_acc']:.2f}")
    print("threshold τ_F1 quality:", out["threshold_f1"])


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--report":  # reprint tables from a results file
        sys.stdout.reconfigure(encoding="utf-8")
        report(json.loads(Path(sys.argv[2]).read_text()))
    else:
        main()
