"""The Annotated Fact Cube (ALGEBRA.md Sections 3 and 10).

Storage: for each concept ℓ, a sparse map report -> PosBool formula φ_r(ℓ) (the zeta
roll-up of the base cells), plus per-report probabilities π_r(ℓ) and prefix arrays of
the moments (n, Σπ, Σπ²) over base time bins for each attribute combination.

Each report has exactly one base time bin and one value per attribute dimension, so a
cell (ℓ, τ, a) is the restriction of the concept map to the reports in (τ, a).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Mapping

import numpy as np

from .lattice import Calendar, Lattice
from .posbool import PB, And, Atom, BoolExpr, Not, Or, all_vars, eval_expr, prob_expr


# ------------------------------------------------------------------ objects
@dataclass(frozen=True)
class Fact:
    fid: int
    report: str
    concept: str
    q: float = 1.0
    span: str | None = None


@dataclass(frozen=True)
class Report:
    rid: str
    t: int  # base time bin
    attrs: tuple[tuple[str, str], ...] = ()  # sorted (dimension, value); missing value = "NA"

    def attr(self, name: str) -> str:
        return dict(self.attrs).get(name, "NA")


# predicates over concepts (the Pred grammar)
@dataclass(frozen=True)
class C:
    concept: str


@dataclass(frozen=True)
class PAnd:
    a: "Pred"
    b: "Pred"


@dataclass(frozen=True)
class POr:
    a: "Pred"
    b: "Pred"


@dataclass(frozen=True)
class PNot:
    a: "Pred"


Pred = C | PAnd | POr | PNot


@dataclass(frozen=True)
class Slice:
    """σ_θ: a time interval of base bins (inclusive) and a value set per attribute dimension.

    Absent dimension = no restriction. `dice` is a Slice with several dimensions.
    """
    time: tuple[int, int] | None = None
    attrs: tuple[tuple[str, frozenset], ...] = ()

    @staticmethod
    def of(time: tuple[int, int] | None = None, **attrs: Iterable[str]) -> "Slice":
        return Slice(time, tuple(sorted((k, frozenset([v]) if isinstance(v, str) else frozenset(v))
                                        for k, v in attrs.items())))

    def meet(self, other: "Slice") -> "Slice":
        """σ_θ ∘ σ_θ' = σ_{θ ∧ θ'}."""
        if self.time is None:
            t = other.time
        elif other.time is None:
            t = self.time
        else:
            t = (max(self.time[0], other.time[0]), min(self.time[1], other.time[1]))
        d: dict[str, frozenset] = dict(self.attrs)
        for k, v in other.attrs:
            d[k] = d[k] & v if k in d else v
        return Slice(t, tuple(sorted(d.items())))

    def contains(self, r: Report) -> bool:
        if self.time is not None and not (self.time[0] <= r.t <= self.time[1]):
            return False
        return all(r.attr(k) in v for k, v in self.attrs)


# ------------------------------------------------------------------ random counts
class CountRV:
    """N = Σ_r 1[e_r], a count over reports with per-report Bool[X] events e_r."""

    def __init__(self, events: Mapping[str, BoolExpr], q: Mapping[int, float]):
        self.events = dict(events)
        self.q = q
        self.pi = {r: prob_expr(e, q) for r, e in self.events.items()}

    @property
    def bitmap(self) -> frozenset[str]:
        """ev₁ image: reports whose event is true when every extracted fact is correct."""
        return frozenset(r for r, e in self.events.items() if eval_expr(e, all_vars(e)))

    @property
    def mean(self) -> float:
        return float(sum(self.pi.values()))

    @property
    def var(self) -> float:
        return float(sum(p * (1 - p) for p in self.pi.values()))

    def cov(self, other: "CountRV") -> float:
        """Exact Cov(N, N') = Σ_r [P(e_r ∧ e'_r) − π_r π'_r] (different reports independent)."""
        s = 0.0
        for r in self.events.keys() & other.events.keys():
            s += prob_expr(And(self.events[r], other.events[r]), self.q) - self.pi[r] * other.pi[r]
        return s




# ------------------------------------------------------------------ the cube
class Cube:
    def __init__(self, lattice: Lattice, calendar: Calendar, reports: Iterable[Report],
                 facts: Iterable[Fact], merge_duplicates: bool = True):
        self.L = lattice
        self.T = calendar
        self.reports: dict[str, Report] = {r.rid: r for r in reports}
        self.q: dict[int, float] = {}
        self.provenance: dict[int, list[str | None]] = defaultdict(list)
        self.fact_concept: dict[int, str] = {}
        base: dict[str, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
        seen: dict[tuple[str, str], int] = {}
        for f in facts:
            if f.concept not in self.L.nodes:
                raise KeyError(f"concept {f.concept!r} not in lattice")
            if f.report not in self.reports:
                raise KeyError(f"report {f.report!r} unknown")
            if not 0.0 <= f.q <= 1.0:
                raise ValueError("q must be in [0, 1]")
            key = (f.report, f.concept)
            if merge_duplicates and key in seen:  # decision D3: one variable per (report, concept)
                fid = seen[key]
                self.q[fid] = max(self.q[fid], f.q)
            else:
                fid = f.fid
                if fid in self.q:
                    raise ValueError(f"duplicate fact id {fid}")
                seen[key] = fid
                self.q[fid] = f.q
                self.fact_concept[fid] = f.concept
                base[f.concept][f.report].add(fid)
            self.provenance[fid].append(f.span)
        self.base: dict[str, dict[str, PB]] = {
            l: {r: PB.any_of(fs) for r, fs in m.items()} for l, m in base.items()}
        # zeta roll-up: C[ℓ] = ⊕_{ℓ' ≤ ℓ} C0[ℓ']
        self.cell: dict[str, dict[str, PB]] = {}
        for l in self.L.nodes:
            acc: dict[str, PB] = {}
            for lp in self.L.down(l):
                for r, phi in self.base.get(lp, {}).items():
                    acc[r] = acc[r] | phi if r in acc else phi
            self.cell[l] = acc
        self.pi: dict[str, dict[str, float]] = {
            l: {r: prob_expr(Atom(phi), self.q) for r, phi in m.items()} for l, m in self.cell.items()}
        self._build_prefix()

    # ---- prefix arrays of evaluated moments (time roll-up, Prop 4)
    def _build_prefix(self) -> None:
        self.prefix: dict[str, dict[tuple, np.ndarray]] = {}
        for l, m in self.pi.items():
            per: dict[tuple, np.ndarray] = {}
            for r, p in m.items():
                rep = self.reports[r]
                arr = per.setdefault(rep.attrs, np.zeros((self.T.n, 3)))
                arr[rep.t] += (1.0 if p > 0 else 0.0, p, p * p)
            self.prefix[l] = {k: np.vstack([np.zeros(3), np.cumsum(a, axis=0)]) for k, a in per.items()}

    def atom_moments(self, concept: str, sl: Slice = Slice()) -> np.ndarray:
        """(n, Σπ, Σπ²) of a concept cell over a slice, from prefix arrays."""
        lo, hi = sl.time if sl.time is not None else (0, self.T.n - 1)
        lo, hi = max(lo, 0), min(hi, self.T.n - 1)  # clamp to the calendar
        out = np.zeros(3)
        if hi < lo:
            return out
        for attrs, P in self.prefix.get(concept, {}).items():
            d = dict(attrs)
            if all(d.get(k, "NA") in v for k, v in sl.attrs):
                out += P[hi + 1] - P[lo]
        return out

    # ---- predicates (homomorphic extension: ∧ → ⊗, ∨ → ⊕, ¬ in Bool[X])
    def _support(self, p: Pred, universe: frozenset[str]) -> frozenset[str]:
        if isinstance(p, C):
            return universe & self.cell[p.concept].keys()
        if isinstance(p, PAnd):
            return self._support(p.a, universe) & self._support(p.b, universe)
        if isinstance(p, POr):
            return self._support(p.a, universe) | self._support(p.b, universe)
        return universe  # ¬: may hold for reports without facts

    def formula(self, p: Pred, rid: str) -> BoolExpr:
        if isinstance(p, C):
            return Atom(self.cell[p.concept].get(rid, PB.zero()))
        if isinstance(p, PAnd):
            return And(self.formula(p.a, rid), self.formula(p.b, rid))
        if isinstance(p, POr):
            return Or(self.formula(p.a, rid), self.formula(p.b, rid))
        return Not(self.formula(p.a, rid))

    def slice_reports(self, sl: Slice) -> frozenset[str]:
        return frozenset(r for r, rep in self.reports.items() if sl.contains(rep))

    def count(self, p: Pred, sl: Slice = Slice()) -> CountRV:
        """γ_count(σ_θ(p)) as a random count with exact per-report events."""
        sup = self._support(p, self.slice_reports(sl))
        return CountRV({r: self.formula(p, r) for r in sup}, self.q)

    def series(self, p: Pred, sl: Slice = Slice(), level: str = "base") -> list[CountRV]:
        """Agg(p, σ) BY level: one count per coarse time bin that meets the slice."""
        out = []
        for lo, hi in self.T.coarse_bins(level):
            sub = sl.meet(Slice((lo, hi)))
            if sub.time[0] <= sub.time[1]:
                out.append(self.count(p, sub))
        return out

    def time_bins(self, sl: Slice, level: str) -> list[tuple[int, int]]:
        out = []
        for lo, hi in self.T.coarse_bins(level):
            sub = sl.meet(Slice((lo, hi)))
            if sub.time[0] <= sub.time[1]:
                out.append(sub.time)
        return out
