"""Laws L12–L13 (ALGEBRA.md Section 11): score-stratified and Poisson (IPW) audit designs.

L12  Stratified SRSWOR with any strata and any allocation (unequal sampling fractions):
     (a) the PPI estimator is exactly design-unbiased for every component of a multi-component query;
     (b) its exact covariance equals Σ_h N_h²(1 − f_h)/n_h S_h^pop (stratified_design_cov);
     (c) the joint covariance estimator Σ̂ is exactly unbiased for it.
     All three by enumeration of every stratified sample.
L13  Poisson sampling with unequal p_r: the same three statements, by enumeration of every subset.
Simulation: for a slope over a 400-report synthetic cube, the Monte Carlo variance of the PPI slope
matches wᵀVw for both designs, and the mean of the estimated variances matches it too.
"""
import itertools
import math

import numpy as np
import pytest
from hypothesis import assume, given, settings, strategies as st

from cuberag import (Audit, C, Calendar, Count, Cube, Fact, Lattice, PAnd, PNot, PoissonAudit, Report,
                     Series, Slice, Slope, draw_poisson, draw_stratified, evaluate, neyman_allocation,
                     ols_weights, poisson_design_cov, poisson_probs, proportional_allocation,
                     quantile_strata, stratified_design_cov)
from cuberag.query import compile_query, ppi_moments

from test_laws import CONCEPTS, cubes


def residual_matrix(comps, cube, truth, rids):
    """Rows e_r = y_r − f_r over the whole frame (the population quantity the design estimates)."""
    E = np.zeros((len(rids), len(comps)))
    for j, r in enumerate(rids):
        for i, c in enumerate(comps):
            if c.sl.contains(cube.reports[r]):
                E[j, i] = truth[(i, r)] - c.rv.pi.get(r, 0.0)
    return E


def query_and_truth(cube, a, b, data):
    """A 3-component query: Count(a), Count(a ∧ ¬b) on the first half, Count(b) on attr m=x.
    Oracle labels are arbitrary 0/1 per (component, report): PPI assumes nothing about the extractor."""
    q1 = compile_query(Count(C(a)), cube).comps
    q2 = compile_query(Count(PAnd(C(a), PNot(C(b))), Slice((0, cube.T.n // 2))), cube).comps
    q3 = compile_query(Count(C(b), Slice.of(None, m="x")), cube).comps
    comps = q1 + q2 + q3
    rids = sorted(cube.reports)
    lab = {(i, r): data.draw(st.integers(0, 1)) for i in range(3) for r in rids}
    preds = [c.pred for c in comps]

    def oracle(pred, r):
        return lab[(preds.index(pred), r)]

    truth_vec = np.array([sum(lab[(i, r)] for r in rids if comps[i].sl.contains(cube.reports[r]))
                          for i in range(3)], float)
    return comps, rids, lab, oracle, truth_vec


# ---------------------------------------------------------------- L12 stratified SRSWOR
@settings(max_examples=40, deadline=None)
@given(cubes(), st.sampled_from(CONCEPTS), st.sampled_from(CONCEPTS), st.data())
def test_L12_stratified_unbiased_and_exact_covariance(cube, a, b, data):
    rids = sorted(cube.reports)
    assume(4 <= len(rids) <= 10)
    assume(a != b)
    comps, rids, lab, oracle, truth_vec = query_and_truth(cube, a, b, data)
    # two strata, e.g. "score ≥ cut" vs the rest, with unequal sampling fractions
    k = data.draw(st.integers(2, len(rids) - 2))
    strata = {r: ("hi" if i < k else "lo") for i, r in enumerate(rids)}
    n_hi = data.draw(st.integers(1, k))
    n_lo = data.draw(st.integers(2, len(rids) - k))  # ≥ 2 so S_lo is estimable
    assume(n_hi >= 2 or n_hi == k)  # a stratum with n_h = 1 needs census (no variance term)
    hi = [r for r in rids if strata[r] == "hi"]
    lo = [r for r in rids if strata[r] == "lo"]
    thetas, Sigmas = [], []
    for U1 in itertools.combinations(hi, n_hi):
        for U2 in itertools.combinations(lo, n_lo):
            th, S = ppi_moments(comps, cube, Audit(list(U1) + list(U2), strata, oracle))
            thetas.append(th)
            Sigmas.append(S)
    thetas, Sigmas = np.array(thetas), np.array(Sigmas)
    assert thetas.mean(axis=0) == pytest.approx(truth_vec, abs=1e-9)  # (a)
    E = residual_matrix(comps, cube, {(i, r): lab[(i, r)] for i in range(3) for r in rids}, rids)
    V = stratified_design_cov(E, [strata[r] for r in rids], {"hi": n_hi, "lo": n_lo})
    D = thetas - truth_vec
    assert (D.T @ D) / len(D) == pytest.approx(V, abs=1e-8)  # (b)
    assert Sigmas.mean(axis=0) == pytest.approx(V, abs=1e-8)  # (c)


# ---------------------------------------------------------------- L13 Poisson / IPW
@settings(max_examples=30, deadline=None)
@given(cubes(), st.sampled_from(CONCEPTS), st.sampled_from(CONCEPTS), st.data())
def test_L13_poisson_ipw_unbiased_and_exact_covariance(cube, a, b, data):
    rids = sorted(cube.reports)
    assume(2 <= len(rids) <= 9)
    assume(a != b)
    comps, rids, lab, oracle, truth_vec = query_and_truth(cube, a, b, data)
    p = {r: data.draw(st.sampled_from([0.1, 0.25, 0.5, 0.8, 1.0])) for r in rids}
    m, mean, second, sig = len(comps), np.zeros(len(comps)), np.zeros((len(comps),) * 2), np.zeros((len(comps),) * 2)
    for bits in itertools.product([0, 1], repeat=len(rids)):
        w = math.prod(p[r] if b_ else 1 - p[r] for r, b_ in zip(rids, bits))
        if w == 0:
            continue
        U = [r for r, b_ in zip(rids, bits) if b_]
        th, S = ppi_moments(comps, cube, PoissonAudit(U, p, oracle))
        mean += w * th
        second += w * np.outer(th - truth_vec, th - truth_vec)
        sig += w * S
    assert mean == pytest.approx(truth_vec, abs=1e-9)
    E = residual_matrix(comps, cube, {(i, r): lab[(i, r)] for i in range(3) for r in rids}, rids)
    V = poisson_design_cov(E, np.array([p[r] for r in rids]))
    assert second == pytest.approx(V, abs=1e-8)
    assert sig == pytest.approx(V, abs=1e-8)


# ---------------------------------------------------------------- simulation: slope covariance
def synthetic(seed=1, n=400, nb=8):
    rng = np.random.default_rng(seed)
    lat = Lattice([("x", "g"), ("y", "g")], top="T")
    cal = Calendar(nb, levels={"half": [i // 2 for i in range(nb)]})
    reports, facts, truth, fid = [], [], {}, 0
    for i in range(n):
        rid = f"r{i}"
        reports.append(Report(rid, int(rng.integers(nb))))
        y = rng.random() < 0.15 + 0.02 * reports[-1].t  # rising prevalence
        q = float(np.clip(rng.beta(4, 2) if y else rng.beta(1, 6), 0, 1))
        if rng.random() < (0.8 if y else 0.5):  # some positives are missed entirely
            facts.append(Fact(fid, rid, "x", round(q, 3)))
            fid += 1
        truth[rid] = int(y)
    return Cube(lat, cal, reports, facts), truth


def test_L12_L13_slope_covariance_by_simulation():
    cube, truth = synthetic()
    oracle = lambda pred, r: truth[r] if pred == C("x") else 0
    q = Slope(Series(C("x"), level="half"))
    nf = compile_query(q, cube)
    rids = sorted(cube.reports)
    w = nf.linear[0]
    E = np.zeros((len(rids), len(nf.comps)))
    for j, r in enumerate(rids):
        for i, c in enumerate(nf.comps):
            if c.sl.contains(cube.reports[r]):
                E[j, i] = truth[r] - c.rv.pi.get(r, 0.0)
    true_slope = w @ (E.sum(axis=0) + np.array([c.rv.mean for c in nf.comps]))
    pi_x = {r: cube.pi["x"].get(r, 0.0) for r in rids}
    score = {r: pi_x[r] for r in rids}
    strata = quantile_strata(score, 3)
    Nh = {h: sum(1 for v in strata.values() if v == h) for h in set(strata.values())}
    alloc = neyman_allocation(Nh, {h: 0.4 if h == "s0" else 0.3 for h in Nh}, 60)
    p = poisson_probs({r: math.sqrt(pi_x[r] * (1 - pi_x[r]) + 0.05) for r in rids}, 60, floor=0.2)
    pa = np.array([p[r] for r in rids])
    V_strat = w @ stratified_design_cov(E, [strata[r] for r in rids], alloc) @ w
    V_pois = w @ poisson_design_cov(E, pa) @ w
    rng = np.random.default_rng(7)
    for name, V, draw in [
        ("stratified", V_strat, lambda: Audit(draw_stratified(strata, alloc, rng), strata, oracle)),
        ("poisson", V_pois, lambda: PoissonAudit(draw_poisson(p, rng), p, oracle)),
    ]:
        est, var = [], []
        for _ in range(3000):
            a = evaluate(q, cube, "ppi", draw())
            est.append(a.value[0])
            var.append(a.cov[0, 0])
        est, var = np.array(est), np.array(var)
        se_mean = est.std() / math.sqrt(len(est))
        assert abs(est.mean() - true_slope) < 4 * se_mean, name  # unbiased
        assert est.var() == pytest.approx(V, rel=0.08), name  # Monte Carlo variance = wᵀVw
        assert var.mean() == pytest.approx(V, rel=0.06), name  # E Σ̂ = V


# ---------------------------------------------------------------- design helpers
@given(st.lists(st.integers(1, 60), min_size=1, max_size=6), st.lists(st.floats(0, 3), min_size=6, max_size=6),
       st.data())
def test_neyman_allocation_bounds(sizes, sds, data):
    Nh = {f"h{i}": s for i, s in enumerate(sizes)}
    lo = sum(min(2, s) for s in sizes)
    n = data.draw(st.integers(max(lo, 2 * len(sizes)) if all(s >= 2 for s in sizes) else lo, sum(sizes)))
    assume(n >= 2 * len(sizes))
    al = neyman_allocation(Nh, {f"h{i}": sds[i] for i in range(len(sizes))}, n)
    assert sum(al.values()) == n
    assert all(min(2, Nh[h]) <= al[h] <= Nh[h] for h in Nh)


def test_allocation_strata_and_probs():
    Nh = {"a": 1000, "b": 100, "c": 10}
    al = neyman_allocation(Nh, {"a": 0.1, "b": 1.0, "c": 5.0}, 60)
    assert al["c"] == 10 and sum(al.values()) == 60 and al["b"] > al["a"] * 100 / 1000
    assert proportional_allocation({"a": 300, "b": 100}, 40) == {"a": 30, "b": 10}
    s = quantile_strata({f"r{i}": (0 if i < 10 else i) for i in range(50)}, 4)
    assert sum(v == "s0" for v in s.values()) == 10 and len(set(s.values())) == 5
    p = poisson_probs({f"r{i}": float(i) for i in range(100)}, 30, floor=0.1)
    assert sum(p.values()) == pytest.approx(30) and max(p.values()) <= 1 and min(p.values()) > 0
    p = poisson_probs({"a": 100.0, "b": 1.0, "c": 1.0, "d": 1.0}, 2)
    assert p["a"] == 1.0 and sum(p.values()) == pytest.approx(2)
