"""ALGEBRA.md Section 9: the hand-calculated toy cube, as exact unit tests."""
import numpy as np
import pytest

from cuberag import (C, Calendar, Constraints, Count, Cube, Fact, Lattice, PAnd, PNot, Report,
                     Series, Slice, Slope, evaluate, project)

LAT = Lattice([("Occlusion", "Mechanical"), ("Leak", "Mechanical"),
               ("Mechanical", "Problem"), ("Electrical", "Problem")], top="Problem")
CAL = Calendar(4, ["Q1", "Q2", "Q3", "Q4"], levels={"year": [0, 0, 0, 0]})

SPEC = {  # report: (bin, [(concept, q)])
    "r1": (0, [("Occlusion", 1)]), "r2": (0, [("Occlusion", 1), ("Leak", .5)]), "r3": (0, [("Electrical", 1)]),
    "r4": (0, [("Leak", 1)]), "r5": (0, [("Electrical", 1)]),
    "r6": (1, [("Occlusion", 1)]), "r7": (1, [("Occlusion", 1)]), "r8": (1, [("Occlusion", 1), ("Electrical", .5)]),
    "r9": (1, [("Leak", 1)]), "r10": (1, [("Electrical", 1)]),
    "r11": (2, [("Occlusion", 1)]), "r12": (2, [("Occlusion", 1)]), "r13": (2, [("Occlusion", 1)]),
    "r14": (2, [("Occlusion", 1), ("Leak", .5)]), "r15": (2, [("Electrical", 1)]),
    "r16": (3, [("Occlusion", 1)]), "r17": (3, [("Occlusion", 1)]), "r18": (3, [("Occlusion", 1)]),
    "r19": (3, [("Occlusion", 1)]), "r20": (3, [("Electrical", .8)]),
}


def toy_cube() -> Cube:
    reports = [Report(r, t) for r, (t, _) in SPEC.items()]
    facts, i = [], 0
    for r, (_, fs) in SPEC.items():
        for c, q in fs:
            facts.append(Fact(i, r, c, q))
            i += 1
    return Cube(LAT, CAL, reports, facts)


CUBE = toy_cube()

TABLE = {  # concept: (n, S1, S2) per quarter
    "Occlusion": ([2, 3, 4, 4], [2, 3, 4, 4], [2, 3, 4, 4]),
    "Leak": ([2, 1, 1, 0], [1.5, 1, .5, 0], [1.25, 1, .25, 0]),
    "Mechanical": ([3, 4, 4, 4], [3, 4, 4, 4], [3, 4, 4, 4]),
    "Electrical": ([2, 2, 1, 1], [2, 1.5, 1, .8], [2, 1.25, 1, .64]),
    "Problem": ([5, 5, 5, 5], [5, 5, 5, 4.8], [5, 5, 5, 4.64]),
}


@pytest.mark.parametrize("concept", TABLE)
def test_cell_table(concept):
    n, s1, s2 = TABLE[concept]
    for t in range(4):
        m = CUBE.atom_moments(concept, Slice((t, t)))
        assert m == pytest.approx([n[t], s1[t], s2[t]])
        rv = CUBE.count(C(concept), Slice((t, t)))
        assert len(rv.bitmap) == n[t]
        assert rv.mean == pytest.approx(s1[t])
        assert rv.var == pytest.approx(s1[t] - s2[t])


def test_rollup_distinct_vs_child_sum():
    q1 = Slice((0, 0))
    mech = CUBE.count(C("Mechanical"), q1).bitmap
    assert mech == {"r1", "r2", "r4"}
    kids = [CUBE.count(C(c), q1).bitmap for c in ("Occlusion", "Leak")]
    assert sum(map(len, kids)) == 4 and max(map(len, kids)) == 2 <= len(mech) == 3
    q3 = Slice((2, 2))
    assert len(CUBE.count(C("Mechanical"), q3).bitmap) == 4
    assert CUBE.pi["Mechanical"]["r2"] == pytest.approx(1.0)


def test_boolean_predicates():
    q1 = Slice((0, 0))
    lm = CUBE.count(PAnd(C("Leak"), C("Mechanical")), q1)
    assert lm.pi["r2"] == pytest.approx(.5)
    ol = CUBE.count(PAnd(C("Occlusion"), C("Leak")), q1)
    assert ol.pi["r2"] == pytest.approx(.5) and ol.bitmap == {"r2"}
    # Mechanical ∧ ¬Leak in Q1: r1 sure, r2 only if Leak is false (prob 1/2)
    mn = CUBE.count(PAnd(C("Mechanical"), PNot(C("Leak"))), q1)
    assert mn.bitmap == {"r1"}  # ev1 = B_Mech \ B_Leak
    assert mn.pi["r1"] == 1 and mn.pi["r2"] == pytest.approx(.5) and mn.pi["r4"] == 0


def test_time_rollup_prefix():
    assert CUBE.atom_moments("Occlusion", Slice((1, 3)))[0] == 11
    assert CUBE.prefix["Occlusion"][()][:, 0].tolist() == [0, 2, 5, 9, 13]
    y = evaluate(Series(C("Occlusion"), level="year"), CUBE).value
    assert y == pytest.approx([13])


@pytest.mark.parametrize("concept,slope,var", [
    ("Occlusion", .7, 0), ("Mechanical", .3, 0), ("Electrical", -.41, .0169),
    ("Leak", -.5, .025), ("Problem", -.06, 9 / 625)])
def test_slopes(concept, slope, var):
    a = evaluate(Slope(Series(C(concept))), CUBE)
    assert a.value[0] == pytest.approx(slope)
    assert a.cov[0, 0] == pytest.approx(var)


def test_reconciliation_example():
    K = Constraints(3).concept_family(2, [0, 1])
    y = np.array([2, 2, 1.5])
    assert project(y, K) == pytest.approx([11 / 6] * 3, abs=1e-6)
    assert project(y, K, np.diag([1, 1, .25])) == pytest.approx([5 / 3] * 3, abs=1e-6)


def test_reconciliation_regression_slsqp_failure():
    # hypothesis found SLSQP failing here; the exact active-set solver must handle it
    K = Constraints(3).concept_family(2, [0, 1])
    p = project(np.array([0., 8., 0.]), K, np.diag([1.0, 0.21875, 0.2]))
    assert K.feasible(p, tol=1e-9)
    assert p[1] == pytest.approx(p[2])
