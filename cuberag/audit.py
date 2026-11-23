"""Audit designs for the PPI estimator (ALGEBRA.md Section 11).

Two designs, both with known inclusion probabilities, so the PPI estimator is exactly
design-unbiased and its joint covariance estimator is unbiased for linear queries:

* Stratified SRSWOR (`Audit` in query.py): strata may be any function of data known before
  the audit (time/attribute cell, extractor score, concept rarity). Inclusion probability n_h/N_h.
  This module adds score strata and Neyman allocation.
* Poisson sampling (`PoissonAudit`): report r is audited independently with probability p_r
  (e.g. proportional to a predicted residual size). Horvitz–Thompson weights 1/p_r.

Population-level (true) design covariances are given for tests and for design selection.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

import numpy as np

from .cube import Pred


@dataclass
class PoissonAudit:
    """Poisson design: r ∈ U independently with probability incl[r] > 0 (all reports in the frame)."""
    sample: Sequence[str]
    incl: Mapping[str, float]
    oracle: Callable[[Pred, str], int]


# ------------------------------------------------------------------ strata
def quantile_strata(score: Mapping[str, float], n_strata: int, zero_stratum: bool = True) -> dict[str, str]:
    """Strata from a report-level score (known before the audit). Reports with score 0 get their
    own stratum if zero_stratum; the rest are cut at quantiles into n_strata groups."""
    ids = list(score)
    s = np.array([score[r] for r in ids], float)
    out: dict[str, str] = {}
    pos = s > 0 if zero_stratum else np.ones(len(s), bool)
    if zero_stratum:
        for r, z in zip(ids, ~pos):
            if z:
                out[r] = "s0"
    sp = s[pos]
    if len(sp):
        cuts = np.unique(np.quantile(sp, np.linspace(0, 1, n_strata + 1)[1:-1]))
        lab = np.searchsorted(cuts, sp, side="right")
        for r, k in zip([r for r, p in zip(ids, pos) if p], lab):
            out[r] = f"s{k + 1}"
    return out


def neyman_allocation(N_h: Mapping[str, int], S_h: Mapping[str, float], n: int, min_n: int = 2) -> dict[str, int]:
    """n_h ∝ N_h S_h, with min_n ≤ n_h ≤ N_h and Σ n_h = n (largest-remainder rounding).

    S_h is a design-time guess of the residual standard deviation in stratum h (from training data
    or a model); a wrong guess loses efficiency, never unbiasedness."""
    hs = sorted(N_h)
    lo = {h: min(min_n, N_h[h]) for h in hs}
    if n < sum(lo.values()) or n > sum(N_h.values()):
        raise ValueError("audit size incompatible with strata")
    w = {h: N_h[h] * max(float(S_h.get(h, 0.0)), 1e-12) for h in hs}

    def total(lam: float) -> float:  # n_h(λ) = clip(λ w_h, lo_h, N_h) is monotone in λ
        return sum(min(max(lam * w[h], lo[h]), N_h[h]) for h in hs)

    a_, b_ = 0.0, 1.0
    while total(b_) < n:
        b_ *= 2
    for _ in range(200):
        mid = (a_ + b_) / 2
        a_, b_ = (mid, b_) if total(mid) < n else (a_, mid)
    real = {h: min(max(b_ * w[h], lo[h]), N_h[h]) for h in hs}
    alloc = {h: int(np.floor(real[h])) for h in hs}
    rem = n - sum(alloc.values())
    order = sorted((h for h in hs if alloc[h] < N_h[h]), key=lambda h: -(real[h] - alloc[h]))
    for h in order[:rem]:
        alloc[h] += 1
    return alloc


def proportional_allocation(N_h: Mapping[str, int], n: int, min_n: int = 2) -> dict[str, int]:
    return neyman_allocation(N_h, {h: 1.0 for h in N_h}, n, min_n)


def draw_stratified(strata: Mapping[str, str], alloc: Mapping[str, int], rng: np.random.Generator) -> list[str]:
    by: dict[str, list[str]] = {}
    for r, h in strata.items():
        by.setdefault(h, []).append(r)
    out: list[str] = []
    for h, n_h in alloc.items():
        members = sorted(by[h])
        out += [members[i] for i in rng.choice(len(members), n_h, replace=False)]
    return out


def poisson_probs(size: Mapping[str, float], n: float, floor: float = 0.0) -> dict[str, float]:
    """p_r ∝ size_r with expected sample size n, mixed with a uniform floor (share `floor` of n),
    capped at 1 (iterated so that the expected size stays n)."""
    ids = list(size)
    N = len(ids)
    s = np.array([max(size[r], 0.0) for r in ids], float)
    if s.sum() == 0:
        s = np.ones(N)
    s = (1 - floor) * s / s.sum() + floor / N
    p = np.zeros(N)
    fixed = np.zeros(N, bool)
    for _ in range(N):
        rest = n - fixed.sum()
        p[~fixed] = rest * s[~fixed] / s[~fixed].sum()
        over = (p > 1) & ~fixed
        if not over.any():
            break
        fixed |= over
        p[fixed] = 1.0
    return {r: float(v) for r, v in zip(ids, p)}


def draw_poisson(incl: Mapping[str, float], rng: np.random.Generator) -> list[str]:
    ids = sorted(incl)
    u = rng.random(len(ids))
    return [r for r, x in zip(ids, u) if x < incl[r]]


# ------------------------------------------------------------------ true design covariances
def stratified_design_cov(E: np.ndarray, strata: Sequence[str], alloc: Mapping[str, int]) -> np.ndarray:
    """Exact Cov of the stratified PPI estimator: Σ_h N_h²(1 − n_h/N_h)/n_h · S_h^pop, where S_h^pop is
    the population covariance (divisor N_h − 1) of the residual vectors e_r = y_r − f_r (rows of E)."""
    E = np.atleast_2d(E.T).T if E.ndim == 1 else E
    strata = np.asarray(strata)
    m = E.shape[1]
    V = np.zeros((m, m))
    for h, n_h in alloc.items():
        Eh = E[strata == h]
        N_h = len(Eh)
        if N_h > 1 and n_h < N_h:
            V += N_h ** 2 * (1 - n_h / N_h) / n_h * np.atleast_2d(np.cov(Eh, rowvar=False))
    return V


def poisson_design_cov(E: np.ndarray, p: np.ndarray) -> np.ndarray:
    """Exact Cov of the Poisson PPI estimator: Σ_r (1 − p_r)/p_r · e_r e_rᵀ."""
    E = E[:, None] if E.ndim == 1 else E
    w = (1 - p) / p
    return (E * w[:, None]).T @ E
