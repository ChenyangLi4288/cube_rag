"""PosBool[X] lineage formulas and their evaluations (ALGEBRA.md Sections 2 and 10).

A formula is kept in canonical form: an antichain of monomials (minimal monotone DNF).
For monotone Boolean functions this form is unique, so `==` on formulas is equality of
functions (law L2c), and ⊕/⊗ are the lattice join/meet.

Predicates with negation live in Bool[X]. We do not build a canonical form for them;
`BoolExpr` is a tree whose leaves are PosBool formulas, evaluated by Shannon expansion.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Mapping

Monomial = frozenset  # frozenset[int] of fact-variable ids


def _minimize(terms: Iterable[Monomial]) -> frozenset:
    """Absorption: drop every monomial that is a strict superset of another."""
    ts = sorted(set(terms), key=len)
    keep: list[Monomial] = []
    for t in ts:
        if not any(k <= t for k in keep):
            keep.append(t)
    return frozenset(keep)


class PB:
    """Monotone Boolean formula over fact variables. ⊕ is `|`, ⊗ is `&`."""

    __slots__ = ("terms", "_hash")

    def __init__(self, terms: Iterable[Iterable[int]] = ()):
        self.terms = _minimize(frozenset(t) for t in terms)
        self._hash = hash(self.terms)

    # constructors
    @staticmethod
    def zero() -> "PB":
        return PB(())

    @staticmethod
    def one() -> "PB":
        return PB([()])

    @staticmethod
    def var(x: int) -> "PB":
        return PB([(x,)])

    @staticmethod
    def any_of(xs: Iterable[int]) -> "PB":
        return PB([(x,) for x in xs])

    # semiring operations
    def __or__(self, other: "PB") -> "PB":  # ⊕
        return PB(self.terms | other.terms)

    def __and__(self, other: "PB") -> "PB":  # ⊗
        return PB(a | b for a in self.terms for b in other.terms)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, PB) and self.terms == other.terms

    def __hash__(self) -> int:
        return self._hash

    def __repr__(self) -> str:
        if not self.terms:
            return "0"
        if self.terms == frozenset([frozenset()]):
            return "1"
        return " ∨ ".join("∧".join(f"x{v}" for v in sorted(t)) or "1" for t in sorted(self.terms, key=sorted))

    def is_zero(self) -> bool:
        return not self.terms

    def variables(self) -> frozenset:
        return frozenset().union(*self.terms) if self.terms else frozenset()

    def implies(self, other: "PB") -> bool:
        """φ ⇒ ψ (pointwise order of the lattice): every monomial of φ contains one of ψ."""
        return all(any(b <= a for b in other.terms) for a in self.terms)

    # evaluations
    def ev(self, world: frozenset | set) -> bool:
        """Valuation at a world (set of true variables). A semiring homomorphism to 𝔹."""
        return any(t <= world for t in self.terms)

    def ev1(self) -> bool:
        """All variables true: the distinct-bitmap homomorphism of Proposition 1."""
        return bool(self.terms)

    def condition(self, x: int, value: bool) -> "PB":
        if value:
            return PB(t - {x} for t in self.terms)
        return PB(t for t in self.terms if x not in t)


def prob(phi: PB, q: Mapping[int, float]) -> float:
    """P(φ = 1) with independent x_f ~ Bernoulli(q_f). Exact (Shannon expansion)."""
    return prob_expr(Atom(phi), q)


# ---------------------------------------------------------------- Bool[X] expressions
@dataclass(frozen=True)
class Atom:
    phi: PB


@dataclass(frozen=True)
class And:
    a: "BoolExpr"
    b: "BoolExpr"


@dataclass(frozen=True)
class Or:
    a: "BoolExpr"
    b: "BoolExpr"


@dataclass(frozen=True)
class Not:
    a: "BoolExpr"


BoolExpr = Atom | And | Or | Not


def leaves(e: BoolExpr) -> list[PB]:
    if isinstance(e, Atom):
        return [e.phi]
    if isinstance(e, Not):
        return leaves(e.a)
    return leaves(e.a) + leaves(e.b)


def all_vars(e: BoolExpr) -> frozenset:
    """Variables of an expression. Evaluating at this world is ev₁ (every extracted fact true)."""
    return frozenset().union(*(l.variables() for l in leaves(e)))


def _subst(e: BoolExpr, x: int, v: bool) -> BoolExpr:
    if isinstance(e, Atom):
        return Atom(e.phi.condition(x, v))
    if isinstance(e, Not):
        return Not(_subst(e.a, x, v))
    return type(e)(_subst(e.a, x, v), _subst(e.b, x, v))


def eval_expr(e: BoolExpr, world: frozenset | set) -> bool:
    if isinstance(e, Atom):
        return e.phi.ev(world)
    if isinstance(e, Not):
        return not eval_expr(e.a, world)
    if isinstance(e, And):
        return eval_expr(e.a, world) and eval_expr(e.b, world)
    return eval_expr(e.a, world) or eval_expr(e.b, world)


def simplify_pos(e: BoolExpr) -> BoolExpr:
    """Fold ∧/∨ of atoms into one PosBool atom (homomorphic extension, law L6)."""
    if isinstance(e, Atom):
        return e
    if isinstance(e, Not):
        return Not(simplify_pos(e.a))
    a, b = simplify_pos(e.a), simplify_pos(e.b)
    if isinstance(a, Atom) and isinstance(b, Atom):
        return Atom(a.phi & b.phi) if isinstance(e, And) else Atom(a.phi | b.phi)
    return type(e)(a, b)


def prob_expr(e: BoolExpr, q: Mapping[int, float]) -> float:
    """Exact probability of a Bool[X] expression by Shannon expansion on its variables."""
    e = simplify_pos(e)
    xs = sorted(frozenset().union(*(l.variables() for l in leaves(e))))
    qv = tuple(float(q[x]) for x in xs)

    @lru_cache(maxsize=None)
    def go(expr: BoolExpr, i: int) -> float:
        # skip variables that no longer occur
        vs = frozenset().union(*(l.variables() for l in leaves(expr)))
        while i < len(xs) and xs[i] not in vs:
            i += 1
        if i == len(xs):
            return 1.0 if eval_expr(expr, frozenset()) else 0.0
        x = xs[i]
        p = qv[i]
        hi = go(_subst(expr, x, True), i + 1) if p > 0 else 0.0
        lo = go(_subst(expr, x, False), i + 1) if p < 1 else 0.0
        return p * hi + (1 - p) * lo

    return go(e, 0)
