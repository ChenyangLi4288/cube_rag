"""Reconciliation: weighted projection onto the consistent set 𝒦 (ALGEBRA.md Section 5, Prop 3).

𝒦 = {x : x ≥ 0, A_eq x = 0, A_le x ≤ 0}. Concept-axis constraints are inequalities
(child ≤ parent ≤ Σ children [+ own]); time/attribute partitions are equalities.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import itertools

import numpy as np
from scipy.optimize import minimize


@dataclass
class Constraints:
    d: int
    le: list[np.ndarray] = field(default_factory=list)  # rows a with a·x ≤ 0
    eq: list[np.ndarray] = field(default_factory=list)  # rows a with a·x = 0
    nonneg: bool = True

    def _row(self, coefs: dict[int, float]) -> np.ndarray:
        a = np.zeros(self.d)
        for i, c in coefs.items():
            a[i] += c
        return a

    def child_le_parent(self, child: int, parent: int) -> "Constraints":
        self.le.append(self._row({child: 1.0, parent: -1.0}))
        return self

    def parent_le_sum(self, parent: int, parts: list[int]) -> "Constraints":
        self.le.append(self._row({parent: 1.0, **{p: -1.0 for p in parts}}))
        return self

    def total_eq_sum(self, total: int, parts: list[int]) -> "Constraints":
        self.eq.append(self._row({total: 1.0, **{p: -1.0 for p in parts}}))
        return self

    def concept_family(self, parent: int, children: list[int], own: int | None = None) -> "Constraints":
        for c in children:
            self.child_le_parent(c, parent)
        return self.parent_le_sum(parent, children + ([own] if own is not None else []))

    def feasible(self, x: np.ndarray, tol: float = 1e-7) -> bool:
        ok = all(a @ x <= tol for a in self.le) and all(abs(a @ x) <= tol for a in self.eq)
        return ok and (not self.nonneg or bool(np.all(x >= -tol)))


def _project_active_set(y: np.ndarray, K: Constraints, M: np.ndarray) -> np.ndarray | None:
    """Exact projection by enumerating active sets (KKT). Used when the constraint count is small."""
    d = len(y)
    G = list(K.le) + ([-np.eye(d)[i] for i in range(d)] if K.nonneg else [])
    E = list(K.eq)
    best, best_val = None, np.inf
    for k in range(len(G) + 1):
        for A in itertools.combinations(range(len(G)), k):
            rows = [G[i] for i in A] + E
            m = len(rows)
            R = np.array(rows).reshape(m, d)
            KKT = np.block([[2 * M, R.T], [R, np.zeros((m, m))]])
            rhs = np.concatenate([2 * M @ y, np.zeros(m)])
            sol = np.linalg.lstsq(KKT, rhs, rcond=None)[0]
            x, lam = sol[:d], sol[d:d + k]
            if not np.allclose(KKT @ sol, rhs, atol=1e-8):
                continue
            if np.any(lam < -1e-9) or not K.feasible(x, tol=1e-9):
                continue
            val = (x - y) @ M @ (x - y)
            if val < best_val - 1e-12:
                best, best_val = x, val
        if best is not None:
            return best  # strictly convex: the first valid KKT point found is the optimum
    return best


def project(y: np.ndarray, K: Constraints, W: np.ndarray | None = None) -> np.ndarray:
    """argmin_{x ∈ 𝒦} (x − y)ᵀ W⁻¹ (x − y). W is SPD and fixed (not a function of y).

    Exact active-set enumeration for small problems (≤ 14 inequality rows), SLSQP otherwise.
    """
    y = np.asarray(y, float)
    W = np.eye(len(y)) if W is None else np.asarray(W, float)
    Winv = np.linalg.inv(W)
    if K.feasible(y):
        return y.copy()
    n_ineq = len(K.le) + (len(y) if K.nonneg else 0)
    if n_ineq <= 14:
        x = _project_active_set(y, K, Winv)
        if x is not None:
            return x
    cons = [{"type": "ineq", "fun": (lambda x, a=a: -(a @ x)), "jac": (lambda x, a=a: -a)} for a in K.le]
    cons += [{"type": "eq", "fun": (lambda x, a=a: a @ x), "jac": (lambda x, a=a: a)} for a in K.eq]
    bounds = [(0, None)] * len(y) if K.nonneg else None
    x0 = np.clip(y, 0, None) if K.nonneg else y
    res = minimize(lambda x: (x - y) @ Winv @ (x - y), x0, jac=lambda x: 2 * Winv @ (x - y),
                   constraints=cons, bounds=bounds, method="SLSQP",
                   options={"ftol": 1e-13, "maxiter": 500})
    if not res.success:
        raise RuntimeError(f"projection failed: {res.message}")
    return res.x
