"""CubeRAG reference implementation (small-scale, pure Python). See ALGEBRA.md Section 10."""
from .posbool import PB, Atom, And, Or, Not, prob, prob_expr, eval_expr
from .lattice import Lattice, Calendar
from .cube import Cube, Fact, Report, Slice, C, PAnd, POr, PNot, CountRV
from .query import (Count, Series, GroupBy, Diff, Ratio, Slope, Audit, Answer, evaluate,
                    compile_query, ols_weights)
from .reconcile import Constraints, project
from .audit import (PoissonAudit, quantile_strata, neyman_allocation, proportional_allocation,
                    draw_stratified, poisson_probs, draw_poisson, stratified_design_cov, poisson_design_cov)
