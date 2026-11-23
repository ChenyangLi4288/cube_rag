"""Query algebra Q and its evaluation (ALGEBRA.md Sections 4 and 10).

Every query compiles to a normal form (N, g): a vector N = (N_1..N_m) of random counts
(one per component cell), and a smooth map g. The answer is g(θ̂) with covariance
J Σ Jᵀ (delta method; exact for linear g). θ̂ and Σ come from one of two estimators:

* "raw": the uncorrected cube moments, θ_i = Σ π, Σ_ij exact from the lineage formulas
  (false-positive variance only; ALGEBRA.md Section 2, item 3).
* "ppi": the audit-corrected estimator of Proposition 2(a) with the joint covariance of
  Proposition 2(c′) (stratified SRSWOR design).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence

import numpy as np
from scipy import stats

from .audit import PoissonAudit
from .cube import Cube, CountRV, Pred, Slice


# ------------------------------------------------------------------ AST
@dataclass(frozen=True)
class Count:
    pred: Pred
    sl: Slice = Slice()


@dataclass(frozen=True)
class Series:
    pred: Pred
    sl: Slice = Slice()
    level: str = "base"
    exposure: tuple[float, ...] | None = None  # ÷E: fixed exposure per output bin


@dataclass(frozen=True)
class GroupBy:
    pred: Pred
    sl: Slice
    dim: str
    values: tuple[str, ...]


@dataclass(frozen=True)
class Diff:
    a: "Query"
    b: "Query"


@dataclass(frozen=True)
class Ratio:
    a: "Query"
    b: "Query"


@dataclass(frozen=True)
class Slope:
    series: Series
    x: tuple[float, ...] | None = None  # default 1..k


Query = Count | Series | GroupBy | Diff | Ratio | Slope


# ------------------------------------------------------------------ normal form
@dataclass
class Component:
    pred: Pred
    sl: Slice
    rv: CountRV


@dataclass
class NormalForm:
    comps: list[Component]
    g: Callable[[np.ndarray], np.ndarray]
    linear: np.ndarray | None = None  # if g is linear: matrix A with g(θ) = A θ


def ols_weights(x: Sequence[float]) -> np.ndarray:
    x = np.asarray(x, float)
    xc = x - x.mean()
    return xc / (xc @ xc)


def compile_query(q: Query, cube: Cube) -> NormalForm:
    if isinstance(q, Count):
        comp = Component(q.pred, q.sl, cube.count(q.pred, q.sl))
        return NormalForm([comp], lambda t: t[:1], np.eye(1))
    if isinstance(q, Series):
        comps = [Component(q.pred, Slice(tb, q.sl.attrs), cube.count(q.pred, Slice(tb, q.sl.attrs)))
                 for tb in cube.time_bins(q.sl, q.level)]
        A = np.eye(len(comps))
        if q.exposure is not None:
            if len(q.exposure) != len(comps):
                raise ValueError("exposure length must equal number of bins")
            A = np.diag(1.0 / np.asarray(q.exposure, float))
        return NormalForm(comps, lambda t, A=A: A @ t, A)
    if isinstance(q, GroupBy):
        comps = []
        for v in q.values:
            s = q.sl.meet(Slice.of(**{q.dim: [v]}))
            comps.append(Component(q.pred, s, cube.count(q.pred, s)))
        A = np.eye(len(comps))
        return NormalForm(comps, lambda t: t, A)
    if isinstance(q, Slope):
        inner = compile_query(q.series, cube)
        k = inner.linear.shape[0]
        w = ols_weights(q.x if q.x is not None else np.arange(1, k + 1))
        A = (w @ inner.linear)[None, :]
        return NormalForm(inner.comps, lambda t, A=A: A @ t, A)
    if isinstance(q, (Diff, Ratio)):
        a, b = compile_query(q.a, cube), compile_query(q.b, cube)
        m = len(a.comps)
        if isinstance(q, Diff):
            lin = None
            if a.linear is not None and b.linear is not None:
                lin = np.hstack([a.linear, -b.linear])
            return NormalForm(a.comps + b.comps, lambda t: a.g(t[:m]) - b.g(t[m:]), lin)
        return NormalForm(a.comps + b.comps, lambda t: a.g(t[:m]) / b.g(t[m:]), None)
    raise TypeError(f"unknown query {q!r}")


# ------------------------------------------------------------------ estimators
@dataclass
class Audit:
    """Audit sample U drawn by stratified SRSWOR. strata: report -> stratum id (all reports)."""
    sample: Sequence[str]
    strata: Mapping[str, str]
    oracle: Callable[[Pred, str], int]  # reference label y_r for a predicate

    def design(self):
        Nh: dict[str, int] = {}
        for h in self.strata.values():
            Nh[h] = Nh.get(h, 0) + 1
        nh: dict[str, int] = {}
        for r in self.sample:
            nh[self.strata[r]] = nh.get(self.strata[r], 0) + 1
        return Nh, nh


def raw_moments(comps: list[Component]) -> tuple[np.ndarray, np.ndarray]:
    m = len(comps)
    theta = np.array([c.rv.mean for c in comps])
    S = np.zeros((m, m))
    for i in range(m):
        S[i, i] = comps[i].rv.var
        for j in range(i + 1, m):
            S[i, j] = S[j, i] = comps[i].rv.cov(comps[j].rv)
    return theta, S


def ppi_moments(comps: list[Component], cube: Cube, audit: "Audit | PoissonAudit") -> tuple[np.ndarray, np.ndarray]:
    """θ̂_i = Σ_r f_ir + Σ_h (N_h/n_h) Σ_{r∈U_h} (y_ir − f_ir), with f_ir = π_ir 1[r ∈ slice_i].

    Joint covariance (Prop 2(c′)): Σ_h N_h² (1 − n_h/N_h) / n_h · S_h, where S_h is the
    sample covariance of the residual vectors e_r = y_r − f_r in stratum h.
    """
    m = len(comps)
    theta = np.array([c.rv.mean for c in comps])

    def resid(r: str) -> np.ndarray:
        rep = cube.reports[r]
        e = np.zeros(m)
        for i, c in enumerate(comps):
            if c.sl.contains(rep):
                e[i] = audit.oracle(c.pred, r) - c.rv.pi.get(r, 0.0)
        return e

    if isinstance(audit, PoissonAudit):
        # ALGEBRA.md 11.3: Horvitz–Thompson residual correction, θ̂ = Σf + Σ_{r∈U} e_r/p_r and the
        # unbiased covariance estimator Σ_{r∈U} (1 − p_r)/p_r² e_r e_rᵀ.
        S = np.zeros((m, m))
        for r in audit.sample:
            p = audit.incl[r]
            e = resid(r)
            theta += e / p
            S += (1 - p) / p ** 2 * np.outer(e, e)
        return theta, S
    Nh, nh = audit.design()
    by_h: dict[str, list[np.ndarray]] = {}
    for r in audit.sample:
        by_h.setdefault(audit.strata[r], []).append(resid(r))
    S = np.zeros((m, m))
    for h, es in by_h.items():
        E = np.vstack(es)
        theta += Nh[h] / nh[h] * E.sum(axis=0)
        if nh[h] > 1:
            S += Nh[h] ** 2 * (1 - nh[h] / Nh[h]) / nh[h] * np.atleast_2d(np.cov(E, rowvar=False))
    return theta, S


@dataclass
class Answer:
    value: np.ndarray
    cov: np.ndarray
    level: float = 0.95

    @property
    def se(self) -> np.ndarray:
        return np.sqrt(np.clip(np.diag(self.cov), 0, None))

    @property
    def ci(self) -> tuple[np.ndarray, np.ndarray]:
        z = stats.norm.ppf(0.5 + self.level / 2)
        return self.value - z * self.se, self.value + z * self.se


def _jacobian(g, theta: np.ndarray) -> np.ndarray:
    y0 = np.atleast_1d(g(theta))
    J = np.zeros((len(y0), len(theta)))
    for i in range(len(theta)):
        h = 1e-6 * max(1.0, abs(theta[i]))
        tp, tm = theta.copy(), theta.copy()
        tp[i] += h
        tm[i] -= h
        J[:, i] = (np.atleast_1d(g(tp)) - np.atleast_1d(g(tm))) / (2 * h)
    return J


def evaluate(q: Query, cube: Cube, mode: str = "raw", audit: Audit | None = None,
             level: float = 0.95) -> Answer:
    nf = compile_query(q, cube)
    if mode == "raw":
        theta, S = raw_moments(nf.comps)
    elif mode == "ppi":
        if audit is None:
            raise ValueError("ppi mode needs an audit (Audit or PoissonAudit)")
        theta, S = ppi_moments(nf.comps, cube, audit)
    else:
        raise ValueError(mode)
    J = nf.linear if nf.linear is not None else _jacobian(nf.g, theta)
    return Answer(np.atleast_1d(nf.g(theta)), J @ S @ J.T, level)
