"""Property-based tests of the laws L1–L11 in ALGEBRA.md Section 10."""
import itertools
import math
from collections import defaultdict

import numpy as np
import pytest
from hypothesis import assume, given, settings, strategies as st

from cuberag import (PB, And, Atom, Audit, C, Calendar, Constraints, Count, Cube, Diff, Fact, Lattice,
                     Not, Or, PAnd, PNot, POr, Report, Series, Slice, Slope, evaluate, eval_expr,
                     ols_weights, prob, prob_expr, project)
from cuberag.query import compile_query, ppi_moments, raw_moments

settings.register_profile("ci", max_examples=150, deadline=None)
settings.load_profile("ci")

VARS = list(range(6))
monomial = st.frozensets(st.sampled_from(VARS), max_size=3)
pb = st.builds(PB, st.lists(monomial, max_size=4))
qmap = st.fixed_dictionaries({v: st.floats(0, 1) for v in VARS})
WORLDS = [frozenset(w) for k in range(len(VARS) + 1) for w in itertools.combinations(VARS, k)]


def brute_prob(f, q):
    return sum(math.prod(q[v] if v in w else 1 - q[v] for v in VARS) for w in WORLDS if f(w))


# ---------------------------------------------------------------- L1 semiring laws
@given(pb, pb, pb)
def test_L1_commutative_semiring_and_distributive_lattice(a, b, c):
    z, o = PB.zero(), PB.one()
    assert (a | b) | c == a | (b | c) and (a & b) & c == a & (b & c)
    assert a | b == b | a and a & b == b & a
    assert a | z == a and a & o == a and a & z == z
    assert a | a == a and a & a == a                      # idempotence
    assert a & (b | c) == (a & b) | (a & c)               # distributivity
    assert a | (b & c) == (a | b) & (a | c)               # dual distributivity (lattice)
    assert a | (a & b) == a and a & (a | b) == a          # absorption
    assert a | o == o                                     # 1 is top


# ---------------------------------------------------------------- L2 valuations are homomorphisms
@given(pb, pb, st.sampled_from(WORLDS))
def test_L2_world_evaluation_is_homomorphism(a, b, w):
    assert (a | b).ev(w) == (a.ev(w) or b.ev(w))
    assert (a & b).ev(w) == (a.ev(w) and b.ev(w))
    assert (a | b).ev1() == (a.ev1() or b.ev1()) and (a & b).ev1() == (a.ev1() and b.ev1())


@given(pb, pb)
def test_L2_canonical_form(a, b):
    same_function = all(a.ev(w) == b.ev(w) for w in WORLDS)
    assert (a == b) == same_function
    assert a.implies(b) == all(b.ev(w) for w in WORLDS if a.ev(w))


# ---------------------------------------------------------------- L3 probability is a valuation
@given(pb, pb, qmap)
def test_L3_probability_valuation(a, b, q):
    assert prob(a, q) == pytest.approx(brute_prob(a.ev, q), abs=1e-9)
    assert prob(a | b, q) + prob(a & b, q) == pytest.approx(prob(a, q) + prob(b, q), abs=1e-9)
    assert prob(PB.zero(), q) == 0 and prob(PB.one(), q) == 1
    if a.implies(b):
        assert prob(a, q) <= prob(b, q) + 1e-12


@given(pb, pb, qmap)
def test_L3_negation_and_section2_formula(a, b, q):
    e = And(Atom(a), Not(Atom(b)))
    assert prob_expr(e, q) == pytest.approx(brute_prob(lambda w: a.ev(w) and not b.ev(w), q), abs=1e-9)
    assert prob_expr(e, q) == pytest.approx(prob(a, q) - prob(a & b, q), abs=1e-9)
    # Section 2 closed form for disjunctions of single facts
    SA, SB = a.variables(), b.variables()
    N = lambda S: math.prod(1 - q[v] for v in S)
    A, B = PB.any_of(SA), PB.any_of(SB)
    assert prob(A, q) == pytest.approx(1 - N(SA), abs=1e-9)
    assert prob(A & B, q) == pytest.approx(1 - N(SA) - N(SB) + N(SA | SB), abs=1e-9)


# ---------------------------------------------------------------- random cubes
CONCEPTS = ["a", "b", "c", "d", "e", "f"]


@st.composite
def cubes(draw):
    # random DAG: each concept may get parents among later concepts
    edges = []
    for i, c in enumerate(CONCEPTS):
        for p in CONCEPTS[i + 1:]:
            if draw(st.booleans()) and draw(st.booleans()):
                edges.append((c, p))
    lat = Lattice(edges, top="T", concepts=CONCEPTS)
    nb = draw(st.integers(2, 6))
    cal = Calendar(nb, levels={"half": [0 if i < nb // 2 else 1 for i in range(nb)], "all": [0] * nb})
    nr = draw(st.integers(1, 14))
    reports = [Report(f"r{i}", draw(st.integers(0, nb - 1)),
                      (("m", draw(st.sampled_from("xyz"))),)) for i in range(nr)]
    facts, fid = [], 0
    for r in reports:
        for c in draw(st.lists(st.sampled_from(CONCEPTS + ["T"]), max_size=3)):
            facts.append(Fact(fid, r.rid, c, draw(st.sampled_from([0.0, 0.3, 0.5, 0.9, 1.0]))))
            fid += 1
    return Cube(lat, cal, reports, facts)


def facts_by(cube):
    d = defaultdict(list)  # report -> [(fid, concept)]
    for fid, c in cube.fact_concept.items():
        r = next(r for r, phi in cube.base[c].items() if fid in phi.variables())
        d[r].append((fid, c))
    return d


# ---------------------------------------------------------------- L4 zeta roll-up
@given(cubes())
def test_L4_zeta_equals_recursive_and_is_monotone(cube):
    L = cube.L
    for l in L.topological():
        rec = dict(cube.base.get(l, {}))
        for ch in L.children[l]:
            for r, phi in cube.cell[ch].items():
                rec[r] = rec[r] | phi if r in rec else phi
        assert rec == cube.cell[l]  # recursive = direct; needs ⊕ idempotent on DAGs
        for p in L.parents[l]:
            for r, phi in cube.cell[l].items():
                assert phi.implies(cube.cell[p][r])
                assert cube.pi[l][r] <= cube.pi[p][r] + 1e-12


# ---------------------------------------------------------------- L5 Prop 1 distinct counts and bounds
@given(cubes(), st.integers(0, 5), st.integers(0, 5))
def test_L5_distinct_counts_and_bounds(cube, lo, hi):
    sl = Slice((min(lo, hi), max(lo, hi)))
    fb = facts_by(cube)
    for l in cube.L.nodes:
        brute = {r for r, rep in cube.reports.items() if sl.contains(rep)
                 and any(cube.L.leq(c, l) for _, c in fb.get(r, []))}
        assert cube.count(C(l), sl).bitmap == brute
        assert cube.atom_moments(l, sl)[0] == len([r for r in brute if cube.pi[l][r] > 0])
        kids = list(cube.L.children[l])
        if kids:
            n = len(brute)
            own = {r for r in brute if any(c == l for _, c in fb.get(r, []))}
            ks = [len(cube.count(C(k), sl).bitmap) for k in kids]
            assert max(ks) <= n <= sum(ks) + len(own)


# ---------------------------------------------------------------- L6 predicates
@given(cubes(), st.sampled_from(CONCEPTS), st.sampled_from(CONCEPTS))
def test_L6_predicate_homomorphism_and_modularity(cube, x, y):
    p, q = C(x), C(y)
    for r in cube.reports:
        fp, fq = cube.cell[x].get(r, PB.zero()), cube.cell[y].get(r, PB.zero())
        assert prob_expr(cube.formula(PAnd(p, q), r), cube.q) == pytest.approx(prob(fp & fq, cube.q))
        assert prob_expr(cube.formula(POr(p, q), r), cube.q) == pytest.approx(prob(fp | fq, cube.q))
    A, B = cube.count(p), cube.count(q)
    assert cube.count(PAnd(p, q)).bitmap == A.bitmap & B.bitmap
    assert cube.count(POr(p, q)).bitmap == A.bitmap | B.bitmap
    assert cube.count(PAnd(p, PNot(q))).bitmap == A.bitmap - B.bitmap
    # modular law on expected counts: E N(p∨q) + E N(p∧q) = E N(p) + E N(q)
    assert (cube.count(POr(p, q)).mean + cube.count(PAnd(p, q)).mean
            == pytest.approx(A.mean + B.mean))
    # complement: E N(p) + E N(¬p) = |slice|
    assert A.mean + cube.count(PNot(p)).mean == pytest.approx(len(cube.reports))


# ---------------------------------------------------------------- L7 slices
slices = st.builds(lambda t, ms: Slice.of(t, **({"m": ms} if ms else {})),
                   st.one_of(st.none(), st.tuples(st.integers(0, 5), st.integers(0, 5)).map(lambda t: (min(t), max(t)))),
                   st.frozensets(st.sampled_from("xyz")))


@given(cubes(), slices, slices, st.sampled_from(CONCEPTS))
def test_L7_slice_meet_commutes_and_measures_add(cube, s1, s2, l):
    assert s1.meet(s2) == s2.meet(s1) and s1.meet(s1) == s1
    both = cube.slice_reports(s1.meet(s2))
    assert both == cube.slice_reports(s1) & cube.slice_reports(s2)
    # σ commutes with predicate formation: count over a slice = restriction of the full count
    full = cube.count(C(l))
    sub = cube.count(C(l), s1)
    assert sub.bitmap == full.bitmap & cube.slice_reports(s1)
    # additivity over a partition of the time axis, and prefix arrays = direct sums
    tot = sum(cube.count(C(l), Slice((t, t))).mean for t in range(cube.T.n))
    assert tot == pytest.approx(full.mean)
    assert cube.atom_moments(l, s1)[1] == pytest.approx(sub.mean)
    assert cube.atom_moments(l, s1)[1] - cube.atom_moments(l, s1)[2] == pytest.approx(sub.var)


# ---------------------------------------------------------------- L8 time roll-up composition
@given(cubes(), st.sampled_from(CONCEPTS))
def test_L8_time_rollup_composes(cube, l):
    base = evaluate(Series(C(l), level="base"), cube).value
    half = evaluate(Series(C(l), level="half"), cube).value
    allv = evaluate(Series(C(l), level="all"), cube).value
    m = cube.T.levels["half"]
    assert half == pytest.approx([base[m == b].sum() for b in np.unique(m)])
    assert allv == pytest.approx([half.sum()]) and allv == pytest.approx([base.sum()])


# ---------------------------------------------------------------- L9 linear operators and covariance
@given(st.lists(st.floats(-50, 50), min_size=2, max_size=8), st.floats(-5, 5), st.floats(-5, 5))
def test_L9_slope_weights(ys, a, b):
    w = ols_weights(range(1, len(ys) + 1))
    assert w.sum() == pytest.approx(0, abs=1e-9)
    assert w @ np.arange(1, len(ys) + 1) == pytest.approx(1)
    assert w @ (a * np.array(ys) + b) == pytest.approx(a * (w @ np.array(ys)), abs=1e-6)


@settings(max_examples=40)
@given(cubes(), st.sampled_from(CONCEPTS), st.sampled_from(CONCEPTS))
def test_L9_exact_covariance_by_enumeration(cube, x, y):
    """Var of Δ(N_x, N_y) with the exact covariance equals the variance over all worlds."""
    vs = sorted(cube.q)
    assume(len(vs) <= 10)
    ans = evaluate(Diff(Count(C(x)), Count(C(y))), cube)
    vals, ws = [], []
    for bits in itertools.product([0, 1], repeat=len(vs)):
        w = frozenset(v for v, b in zip(vs, bits) if b)
        pw = math.prod(cube.q[v] if b else 1 - cube.q[v] for v, b in zip(vs, bits))
        nx = sum(phi.ev(w) for phi in cube.cell[x].values())
        ny = sum(phi.ev(w) for phi in cube.cell[y].values())
        vals.append(nx - ny)
        ws.append(pw)
    vals, ws = np.array(vals), np.array(ws)
    mu = ws @ vals
    assert ans.value[0] == pytest.approx(mu, abs=1e-9)
    assert ans.cov[0, 0] == pytest.approx(ws @ (vals - mu) ** 2, abs=1e-9)


# ---------------------------------------------------------------- L10 PPI is exactly design-unbiased
@settings(max_examples=40)
@given(cubes(), st.sampled_from(CONCEPTS), st.integers(1, 3), st.data())
def test_L10_ppi_design_unbiased(cube, l, n, data):
    rids = sorted(cube.reports)
    assume(len(rids) <= 9 and n <= len(rids))
    truth = {r: data.draw(st.integers(0, 1)) for r in rids}
    strata = {r: "s" for r in rids}
    oracle = lambda pred, r: truth[r]
    comps = compile_query(Count(C(l)), cube).comps
    ests = [ppi_moments(comps, cube, Audit(U, strata, oracle))[0][0]
            for U in itertools.combinations(rids, n)]
    assert np.mean(ests) == pytest.approx(sum(truth.values()), abs=1e-9)


# ---------------------------------------------------------------- L11 reconciliation
vec3 = st.lists(st.floats(0, 10), min_size=3, max_size=3).map(np.array)


@settings(max_examples=60)
@given(vec3, vec3, st.lists(st.floats(0.2, 5), min_size=3, max_size=3))
def test_L11_projection_feasible_idempotent_nonexpansive(y, xstar_raw, wdiag):
    K = Constraints(3).concept_family(2, [0, 1])
    # make a feasible truth: parent between max and sum of children
    c0, c1 = xstar_raw[0], xstar_raw[1]
    xstar = np.array([c0, c1, max(c0, c1) + (min(c0, c1)) * (xstar_raw[2] / 10)])
    assert K.feasible(xstar)
    W = np.diag(wdiag)
    Winv = np.linalg.inv(W)
    p = project(y, K, W)
    assert K.feasible(p, tol=1e-6)
    assert project(p, K, W) == pytest.approx(p, abs=1e-5)
    nrm = lambda v: float(v @ Winv @ v)
    assert nrm(p - xstar) <= nrm(y - xstar) + 1e-6
