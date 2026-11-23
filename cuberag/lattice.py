"""Concept poset (L, ≤) with a top element, and the time calendar (T, ≤) with levels."""
from __future__ import annotations

from collections import defaultdict
from functools import cached_property
from typing import Iterable, Sequence

import numpy as np


class Lattice:
    """Finite poset given by (child, parent) pairs. A concept may have several parents (DAG).

    `ℓ ≤ ℓ'` means ℓ is more specific. `down(ℓ)` is ↓ℓ (ℓ and all descendants).
    A top element is added if `top` is not already the unique maximal element.
    """

    def __init__(self, edges: Iterable[tuple[str, str]], top: str = "⊤", concepts: Iterable[str] = ()):
        self.parents: dict[str, set[str]] = defaultdict(set)
        self.children: dict[str, set[str]] = defaultdict(set)
        nodes = set(concepts)
        for c, p in edges:
            if c == p:
                raise ValueError(f"self loop on {c}")
            self.parents[c].add(p)
            self.children[p].add(c)
            nodes |= {c, p}
        maximal = {n for n in nodes if not self.parents[n]} - {top}
        for m in maximal:
            self.parents[m].add(top)
            self.children[top].add(m)
        nodes.add(top)
        self.top = top
        self.nodes = frozenset(nodes)
        self._check_acyclic()

    def _check_acyclic(self) -> None:
        state: dict[str, int] = {}

        def visit(n: str) -> None:
            if state.get(n) == 1:
                raise ValueError(f"cycle through {n}")
            if state.get(n) == 2:
                return
            state[n] = 1
            for p in self.parents[n]:
                visit(p)
            state[n] = 2

        for n in self.nodes:
            visit(n)

    @cached_property
    def _down(self) -> dict[str, frozenset[str]]:
        memo: dict[str, frozenset[str]] = {}

        def down(n: str) -> frozenset[str]:
            if n not in memo:
                memo[n] = frozenset({n}).union(*(down(c) for c in self.children[n]))
            return memo[n]

        for n in self.nodes:
            down(n)
        return memo

    def down(self, l: str) -> frozenset[str]:
        return self._down[l]

    def up(self, l: str) -> frozenset[str]:
        return frozenset(n for n in self.nodes if l in self._down[n])

    def leq(self, a: str, b: str) -> bool:
        return a in self._down[b]

    def topological(self) -> list[str]:
        """Children before parents (order for the recursive roll-up)."""
        return sorted(self.nodes, key=lambda n: len(self._down[n]))


class Calendar:
    """Base time bins 0..T-1 (total order) and coarser levels.

    `levels[name]` maps each base bin to a coarse bin id. A level must be monotone
    (contiguous coarse bins), so every coarse bin is an interval of base bins.
    """

    def __init__(self, n_bins: int, labels: Sequence[str] | None = None,
                 levels: dict[str, Sequence[int]] | None = None):
        self.n = n_bins
        self.labels = list(labels) if labels is not None else [str(i) for i in range(n_bins)]
        self.levels: dict[str, np.ndarray] = {"base": np.arange(n_bins)}
        for name, m in (levels or {}).items():
            m = np.asarray(m)
            if len(m) != n_bins or np.any(np.diff(m) < 0):
                raise ValueError(f"level {name} must be a monotone map of length {n_bins}")
            self.levels[name] = m

    def coarse_bins(self, level: str) -> list[tuple[int, int]]:
        """Base-bin intervals [lo, hi] of each coarse bin, in order."""
        m = self.levels[level]
        out = []
        for b in np.unique(m):
            idx = np.nonzero(m == b)[0]
            out.append((int(idx[0]), int(idx[-1])))
        return out
