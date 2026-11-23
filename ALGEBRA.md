# The Annotated Fact Cube: formal specification (draft)

This document defines the data structure and the query operators. Some parts are not complete.
Section 8 lists the open items.

## 1. Objects

- **Corpus** `R = {r₁,…,r_N}`. Each report has an ID, a time `t(r)`, structured attributes `a(r)`, and text.
- **Concept lattice** `(L, ≤)`. This is a finite partial order from a public taxonomy. We add a top element ⊤.
  `ℓ ≤ ℓ'` means that ℓ is more specific than ℓ'. `↓ℓ` is the set of ℓ and all its descendants.
- **Time order** `(T, ≤)`. Time bins are in a total order. Day, month, quarter and year are levels.
  A change from one level to a higher level is a roll-up.
- **Attribute dimensions** `A = A₁ × … × A_k`. Examples: manufacturer, state, age band, aircraft type.
  An attribute can have a hierarchy.
- **Fact** `f = (r, ℓ, t, a, s, q)`. Report r states concept ℓ at time t, with attributes a.
  Span s is the text that supports the fact. `q ∈ [0,1]` is the extractor score.

## 2. The annotation semiring

**Idea.** Annotate each report in a cell with the *event* "the report really states a concept in this cell".
Events form a semiring, and roll-up is the semiring sum. Moments of the count are read from the events by
a separate evaluation step. (This is the lineage construction for probabilistic databases: Green, Karvounarakis
and Tannen, 2007, for the semirings, and the possible-worlds semantics for the probabilities. Check both.)

**Annotations.** Each fact `f` has an independent Bernoulli variable `x_f` with `P(x_f = 1) = q_f` (the fact is
correct). Let `X` be the set of all fact variables, and let `S = PosBool[X]` be the monotone Boolean functions
over `X`, with `∨` as ⊕, `∧` as ⊗, `0 = false` and `1 = true`. This is a commutative semiring (a distributive
lattice). The annotation of a report r in the cell of concept ℓ is the formula
`φ_r(ℓ) = ⋁ { x_f : f is a fact of r with concept ≤ ℓ }`.
A cell value is the vector `(φ_r)_{r ∈ cell}`, in `S^R` (reports of different cells are different reports).
In practice we store the set of fact IDs of each report, which is the formula.

**Roll-up is a semiring sum.** Union of fact sets is ⊕ in `S`. Thus the concept roll-up uses only
the semiring operation, for every poset `L`, and it does not depend on the probabilities.

**Evaluation (not a semiring component).** From a cell value we read:

1. **Distinct bitmap.** The map `ev₁ : S → 𝔹` (set all `x_f = 1`) is a semiring homomorphism. Thus,
   `ev₁(φ_r(ℓ)) = 1` iff r has a fact under ℓ. The set of reports with `ev₁ = 1` is the bitmap of Proposition 1.
   Because `ev₁` is a homomorphism, it commutes with roll-up and with ∧, ∨ (the bitmap algebra is the
   image of the formula algebra).
   **Negation.** `PosBool[X]` has no ¬. Roll-up needs only ⊕, so the cube stores `PosBool` formulas. A query
   predicate with ¬ is evaluated in the Boolean algebra `Bool[X]` of all Boolean functions over `X`, which contains
   `PosBool[X]`. The map `ev₁ : Bool[X] → 𝔹` is a Boolean-algebra homomorphism (it also commutes with ¬), so
   `p ∧ ¬q` maps to the set difference of the bitmaps.
2. **Probability.** `π_r = P(φ_r = 1)` under independent `x_f`. This map is a valuation, not a homomorphism:
   `P(a ∨ b) = P(a) + P(b) − P(a ∧ b)`. For a disjunction of single facts, `P(φ) = 1 − ∏_{f ∈ S}(1 − q_f)`, where `S`
   is its fact set. For a conjunction of two such formulas with fact sets `S_A`, `S_B`:
   `P(A ∧ B) = 1 − N(S_A) − N(S_B) + N(S_A ∪ S_B)`, with `N(S) = ∏_{f∈S}(1 − q_f)`.
   Also `P(A ∧ ¬B) = P(A) − P(A ∧ B)`. For a conjunction of k predicates, inclusion–exclusion has `2^k` terms,
   which is fine for the small k we expect.
3. **Moments.** For a cell, `N_cell = Σ_r 1[φ_r]`. If different reports are independent,
   `E[N_cell] = Σ_r π_r` and `Var[N_cell] = Σ_r π_r(1 − π_r) = Σπ − Σπ²`. We store `(n, Σπ, Σπ²)` for each
   base cell (`n` is the number of reports with `π_r > 0`). Over disjoint time bins the means and the
   variances add, so prefix arrays of this triple give any time range. This triple is written 𝔼₂ in other parts of
   these documents. It is the evaluation of the cell, not a second semiring component. It is similar in spirit
   to the second-order expectation semiring of Li and Eisner (2009), but we do not use their ⊗ rule.
   **What the moments do and do not measure.** A variable `x_f` exists only for an extracted fact. A concept that
   the extractor missed has no variable. Thus `Σπ − Σπ²` is the variance from false positives only, given the
   extractions and calibrated scores. It ignores missed facts (recall) and calibration error. A cell with `q = 1`
   for all facts has variance 0 (Section 9), which is not a real uncertainty. Use these moments only for the
   uncorrected cube (the ablation "no correction"). Every answer that we report with an interval uses the
   corrected estimator of Section 5 and the variance of Proposition 2, which comes from the audit set and
   covers both error types. `Σπ` is the `Σ f_r` term of that estimator. `Σπ²` is not used by it.
4. **Provenance.** The polynomial semiring `ℕ[X]` of Green et al. maps onto `S` by a homomorphism. If we want
   citations with multiplicity, we use `ℕ[X]` where we now use `S`. Each fact variable has a source span, so
   the formula gives citations and audit samples.

**Assumptions.** (i) The events `x_f` of different facts are independent, including facts of one report.
(ii) The scores `q_f` are calibrated. These are modelling assumptions about the extractor, not properties of the
algebra. They matter only for the uncorrected moments and for the scores `f_r = π_r`. The corrected estimator of
Section 5 does not depend on (i) and (ii) for its unbiasedness or its intervals (Proposition 2(a), (c)). If (i) or
(ii) is false, the corrected intervals stay valid, but they can get wider.

**Why this design.** Roll-up uses ⊕ exactly, so a report with two child concepts is one report in the parent
(its formula is `x_f ∨ x_g`, and `P = 1 − (1−q_f)(1−q_g)`, not `q_f + q_g`). A plain counting semiring cannot do this.
The probability is not a homomorphism. The natural semiring on `[0,1]`, `a ⊕ b = a + b − ab` with
`a ⊗ b = ab`, is not distributive. Keeping formulas, and evaluating at the end, avoids this.

## 3. The cube

`𝒞 : L × T × A → K`

`𝒞[ℓ,τ,a] = ⨁ { ann_r(↓ℓ) : t(r) ∈ τ, a(r) ∈ a }`

`ann_r(↓ℓ) = φ_r(ℓ)` is the formula of Section 2: it combines all facts of report r under ↓ℓ into one value for the
report. `K = S^R` is the cell value space, with ⊕ and ⊗ pointwise.

- **Roll-up on L (zeta transform).** `𝒞[ℓ,τ,a] = ⨁_{ℓ' ≤ ℓ} 𝒞₀[ℓ',τ,a]`, where ⊕ is the semiring sum of Section 2.
  This is an exact fold in the semiring. We do not recompute anything: the moments are read from the result
  (Section 2, evaluation).
- **Roll-up on T.** The reports of different time bins are different reports, so their moments add and subtract
  exactly. Prefix arrays `P[τ]` (Fenwick tree) of the evaluated moments `(n, Σπ, Σπ²)` give a range aggregate in
  O(log |T|). We do not need prefix sums of the formulas.
- **Boolean predicates.** `p ∨ q` is ⊕ and `p ∧ q` is ⊗ on the per-report formulas. `¬p` is evaluated in
  `Bool[X]` (Section 2). The probability of the result
  comes from the exact formulas in Section 2 (evaluation). The only assumption is that the facts of one report
  are independent events (Section 2). We do not need an independence assumption between predicates.

## 4. Query algebra `Q`

| Operator | Meaning | Output |
|---|---|---|
| `σ_θ` | Slice on attributes or a time range | Sub-cube |
| `ρ_{ℓ→ℓ'}`, `ρ_{τ→τ'}` | Roll-up or drill-down | Cube |
| `γ_count`, `γ_sum(v)`, `γ_mean` | Aggregate | Value or vector, with variance |
| `Δ(x,y)` | Difference | Value with variance. Add a covariance term if x and y overlap. |
| `x ÷ y` | Ratio | Value with variance (delta method) |
| `∇(series)` | Slope (OLS or weighted). Theil–Sen is the robust option. | Slope with confidence interval |
| `κ(series)` | Change-point (binary segmentation or PELT on the corrected series) | Locations with bootstrap interval |
| `÷E` | Divide by exposure `E[τ,a]` (public data) | Rate series |

Each answer is `g(w·θ)`. Here, `w` is a fixed weight vector over the cell means θ, and `g` is a smooth function.
Thus, `Var ≈ ∇gᵀ Σ_w ∇g`, and we calculate it from the stored moments.

Grammar (draft):

```
Query  := Agg(Pred, Slice, Group?) | Δ(Query, Query) | Query ÷ Query | ∇(Series) | κ(Series)
Series := Agg(Pred, Slice) BY TimeBin [÷E]
Pred   := Concept | Pred ∧ Pred | Pred ∨ Pred | ¬Pred
```

## 5. Correction and reconciliation

- **Audit set** `U ⊂ R`, with |U| = n (100 to 500). We take U with a known sample design, stratified on cube cells.
  The oracle labels come from the agency-coded fields (or from a person).
- **Correction in the cube.** For each concept ℓ, we estimate sensitivity Se and specificity Sp on U
  (or a PPI rectifier). Rogan–Gladen works on proportions. Let `N` be the number of reports in the slice
  `(τ, a)` and `p_raw = θ_raw / N`. The corrected proportion is `p̂ = (p_raw − (1 − Sp)) / (Se + Sp − 1)`, clipped to
  `[0, 1]`, and the corrected count is `θ̂ = N·p̂`. The other option is the PPI form (Proposition 2(a)). PPI++ tunes a
  weight λ on the same data. This lowers the variance, but the estimator is then only asymptotically unbiased.
  The variance includes the uncertainty from the audit.
- **Reconciliation.** Let `y` be the vector of corrected cells over the lattice. Let 𝒦 be the set of
  consistent vectors. A report can have facts under more than one child, so the children of a concept do not
  partition its reports. For a concept ℓ with children c₁…c_k, the distinct counts satisfy
  `max_i x[c_i] ≤ x[ℓ] ≤ Σ_i x[c_i]` (inequalities). If ℓ has facts of its own, the upper bound adds `x[ℓ-own]`.
  Equalities (`x[ℓ] = Σ_i x[c_i]`) hold only for a single-label partition, for example when each report has
  exactly one child label, or for the cells of the time and attribute axes (each report is in one bin).
  Use equalities on those axes and inequalities on the concept axis.
  We solve `min_x (x − y)ᵀ W⁻¹ (x − y)` subject to `x ∈ 𝒦`.
  This is a weighted projection (MinT-type), a quadratic program. MinT itself assumes summing equalities, so we
  use it only for the time and attribute axes, and the concept axis needs the inequality version.
- **Intervals after reconciliation.** For a target `w·x`, choose a small set `J` of cells: the target cells, and
  their parents and children in the same time and attribute bin. Let `𝒦_J` be the constraints of 𝒦 that use only
  cells in `J`, and `d = |J|`. Let `y_J ~ N(x*_J, Σ_J)` asymptotically, and `c = χ²_{d,1−α}`.
  The interval is `[min, max]` of `w·x` over `R_J = {x ∈ 𝒦_J : (x − y_J)ᵀ Σ̂_J⁻¹ (x − y_J) ≤ c}`.
  Because `x*_J ∈ 𝒦_J` and the ellipsoid contains `x*_J` with probability `1 − α`, the coverage is at least
  `1 − α` asymptotically. A smaller `J` keeps this true (fewer constraints only make `𝒦_J` larger) and gives a
  smaller `c`, so the interval is tighter. Keep `d` small (about 3 to 10).
  - **Covariance.** `Σ_J` is the joint covariance of the cells in `J`. A parent cell and a child cell share reports,
    so they are correlated. Proposition 2 must give the joint covariance (the audit residuals of a report enter
    each cell that contains it), not only the variance of each cell.
  - **Empty region.** If `R_J` is empty, then the ellipsoid misses 𝒦, which has probability at most α under
    the model. Report the clipped interval below, and count the event in the diagnostics.
  - It is conservative (it uses d degrees of freedom and ignores that the constraints cut the region).
    The point estimate is the projection of Section 5 and the interval does not have to be centred on it.
    Report the width and the empirical coverage.
  - A simpler fallback is to clip each Proposition 2 interval to the range allowed by 𝒦.
- **Drift test.** We test if the extractor error rates change with time τ. For this test, we stratify the audit
  by time. If the rates change, we correct each time block separately.

## 6. Propositions to prove

Draft statements. Each one gives the assumptions. Chenyang must review them before anyone writes a proof.

Notation: `B₀[ℓ',τ,a] = {r : t(r) ∈ τ, a(r) ∈ a, r has a fact with concept ℓ'}` is the base bitmap. Each report has
one time and one attribute value, so the cells of `T × A` partition the reports.

1. **Distinct counts are correct.** Let `(L, ≤)` be any finite partial order. Define
   `B[ℓ,τ,a] = ⋃_{ℓ' ≤ ℓ} B₀[ℓ',τ,a]`. Then `|B[ℓ,τ,a]| = |{r : t(r) ∈ τ, a(r) ∈ a, ∃ fact (r,ℓ',…) with ℓ' ≤ ℓ}|`.
   For Boolean predicates, `p ∧ q`, `p ∧ ¬q` and `p ∨ q` map to `∩`, `∖` and `∪` of the bitmaps, and the cardinality
   of the result is the number of distinct reports that satisfy the predicate (when each fact is correct).
   In the semiring of Section 2, the bitmap is the image of the cell value under the homomorphism `ev₁`.
   Hence this proposition is the statement that `ev₁` commutes with ⊕ and ⊗ (and with ¬ in `Bool[X]`).
   The sum of the child counts is not equal to this number when a report has facts under more than one child:
   it is larger by `Σ_r (m_r − 1)`, where `m_r ≥ 1` is the number of children of ℓ under which r has a fact
   (if no fact is at ℓ itself; the toy cube in Section 9 has an example).
2. **Validity.** Fix a cell set and a cell total `θ = Σ_{r∈R} y_r`, where `y_r ∈ {0,1}` is the reference label.
   The extractor gives a score `f_r ∈ [0,1]` for each report. The audit set `U` is drawn by a design with known
   inclusion probabilities `p_r > 0` (stratified on cells, without replacement).
   - **(a) PPI form.** `θ̂ = Σ_{r∈R} f_r + Σ_{r∈U} (y_r − f_r)/p_r` is exactly design-unbiased for θ. This needs no
     assumption on the extractor.
     With an estimated PPI++ weight λ̂, the estimator is only asymptotically unbiased.
   - **(b) Rogan–Gladen form.** Suppose Se and Sp are constant within the stratum and `Se + Sp > 1`. Then the
     estimator `N·p̂` (Section 5) is asymptotically unbiased as the audit size in the stratum goes to infinity.
   - **(c) Intervals.** In both forms, `θ̂ ± z_{1−α/2} · SE` has asymptotic coverage `1 − α`. The SE includes the
     audit variance. This is true for each linear function `w·θ` (this includes OLS slopes with fixed time points)
     and, by the delta method, for each smooth `g(w·θ)` with `∇g ≠ 0` (this includes ratios and rates).
     It is not claimed for Theil–Sen slopes or change-points.
   - **(c′) Joint covariance.** The same result holds jointly for a vector of cells, with the covariance matrix
     estimated from the audit residuals. Cells that share reports (a parent and its child) have a covariance term.
     Section 5 needs this for the intervals after reconciliation.
   - **(d) Drift.** If Se or Sp change with time, (b) and (c) are true only when we stratify the audit and the
     correction by time block.
   - These are asymptotic results. We expect the intervals to fail for rare concepts with few audited positives.
     This is what RQ3 tests.
3. **Reconciliation does not make results worse.** Let `𝒦 ⊂ ℝᵈ` be closed, convex and not empty, and let `W` be a
   fixed symmetric positive definite matrix (not a function of `y`). Let
   `P(y) = argmin_{x∈𝒦} (x − y)ᵀ W⁻¹ (x − y)`. If the true vector `x*` is in 𝒦, then for every `y`:
   `‖P(y) − x*‖_{W⁻¹} ≤ ‖y − x*‖_{W⁻¹}`. Thus, `E‖P(y) − x*‖²_{W⁻¹} ≤ E‖y − x*‖²_{W⁻¹}` for any distribution of y.
   Remarks: the guarantee holds for the loss with the same W. It is not claimed for other losses, or for the case
   where W is estimated from the same y. P is not linear when 𝒦 has inequalities, so P(y) is biased.
   Thus, the intervals of Proposition 2 do not carry over to the reconciled point values. For intervals, use the
   constrained-region intervals of Section 5 (valid, and conservative).
4. **Complexity.** Let `F` be the number of facts, `h` the largest number of ancestors of one concept, and
   `A_ne` the set of non-empty attribute values.
   - **Build:** O(F·h) time to compute `π_r(ℓ)` for each report and each ancestor ℓ.
   - **Size:** O(F·h) for the sparse cells and bitmaps, plus O(|L|·|T|·|A_ne|) for the prefix arrays (worst case).
   - **Range count** over a time range, for one concept and one attribute value: O(1) with static prefix arrays,
     O(log|T|) with a Fenwick tree (this is needed if we add data). An attribute range (for example ages 12–29)
     costs this times the number of attribute values in the range. This is valid because each report is in one
     time bin. Thus, the numeric components `(n, Σπ, Σπ²)` of different bins add and subtract exactly.
     We do not need prefix sums of bitmaps, and union has no inverse.
   - **Slope** over k bins: O(k) for the weighted sum and its variance (O(k log|T|) with a Fenwick tree).
   - A Boolean predicate costs O(size of the compressed bitmaps), not O(log|T|).
5. **Cost over many queries.** Measure cost in LLM calls (or tokens). Let `C_index`, `C_audit` be the fixed costs.
   Assume each query has a parse cost at most `c_p`, and a probability ρ of a new concept that costs `c_new`.
   Assume a per-query sampling method uses `c_s` calls for each query. We set `c_s` from the baseline's own
   settings (measured). For a Hoeffding-based design (error ε, failure δ) on a proportion, a sufficient sample
   size is `ln(2/δ) / (2ε²)`. This is not a lower bound on what any method needs. If `c_s > c_p + ρ·c_new`, the expected
   cost of CubeRAG is lower for all `m ≥ m*`, where
   `m* = (C_index + C_audit) / (c_s − c_p − ρ·c_new)`.
   For H4, we need the ratio `(C_index + C_audit + m(c_p + ρ·c_new)) / (m·c_s) ≤ 0.1` at `m = 300`.
   This is an accounting result. The student must measure the values of all c-terms.

## 7. Examples

- **MAUDE (FRN infusion pumps).** "How many 2025 reports describe an occlusion alarm with injury?"
  → `γ_count(σ_{year=2025}(↓Occlusion ∧ Injury))`.
  `Injury` is a concept extracted from the text, so the Boolean rule of Section 2 gives its uncertainty.
  The ground truth comes from the hidden field `event_type`. A field is a filter attribute or a hidden field,
  never both (Section 8, item 3).
- **VAERS.** "What is the trend of myocarditis reports per million doses, 2021 Q1 to 2023 Q4, ages 12–29?"
  → `∇(Agg(↓Myocarditis, σ_{age∈[12,29]}) BY quarter ÷E doses)`. Lattice: MedDRA. Exposure: CDC doses.
- **ASRS.** "Did runway-incursion reports change from 2018 to 2023, when we include the change in traffic?"
  → `κ(Agg(↓RunwayIncursion) BY month ÷E operations)`.
  The raw counts decrease in 2020 because there were fewer flights. They do not show a change in safety.

## 8. Open items

> Remaining checks are tracked in GitHub Issues: citations in [#7](https://github.com/ChenyangLi4288/cube_rag/issues/7), reconciliation-interval tightness with the rare-cell work in [#11](https://github.com/ChenyangLi4288/cube_rag/issues/11).

Decisions below are the working defaults. Chenyang can overrule them. A decision marked *check* is not complete
until a source or a proof is checked.

1. **Semiring.** Decided: use `PosBool[X]` with evaluation (Section 2). The earlier product ring is dropped.
   *Check:* the construction against Green, Karvounarakis and Tannen (2007), and the relation to Li and Eisner (2009),
   from the original papers. The student does this when they verify citations. Describe the method as an
   application of lineage semirings, not as a new algebra.
2. **Boolean combinations.** Decided: exact given independent facts within a report (Section 2). No independence
   assumption between predicates. A Gaussian copula is an ablation for dependence between the facts of one
   report, with the audit set correcting the combined cell. The Fréchet–Hoeffding bounds are a check on the
   combined probability of a conjunction.
3. **`event_type` as filter and hidden field.** Decided: no. Each field is exactly one of text, filter or hidden
   (STUDENT_START.md, task 3). In MAUDE, `event_type` stays hidden. A question about injury uses an extracted
   `Injury` concept, and the answer is checked against `event_type`. A question that filters on a structured
   field uses only fields that the method may see. Do not write a question template that uses one field both ways.
4. **Toy example.** Decided: counts, roll-up, slope, Boolean predicate and reconciliation are in Section 9. Correction (Se, Sp)
   and change-points are added when the code exists, as part of the unit tests, not by hand.
5. **Intervals after reconciliation.** Decided: constrained-region intervals (Section 5), with the clipped
   Proposition 2 intervals as a fallback. Use a local cell set `J` to keep `d` small. Open: tightness, and the joint
   covariance estimator (Proposition 2(c′)). H3 now asks for at least 95% coverage and a report of the width.
6. **Uncertainty from the moments.** Decided: the stored moments `(n, Σπ, Σπ²)` give an uncertainty for the
   uncorrected cube only (Section 2). Reported intervals come from Proposition 2. Do not describe the cube as
   carrying the full uncertainty through roll-up without the audit correction.

## 9. Toy cube (hand calculation, first unit test)

20 reports, 5 concepts, 4 time bins (Q1–Q4). Use it as the first unit test. All numbers are exact.

**Lattice.** Occlusion ≤ Mechanical ≤ Problem, Leak ≤ Mechanical, Electrical ≤ Problem. Problem is ⊤.
Facts have `q = 1` unless the table says otherwise. A report with no `q` shown has `q = 1` for each fact.

| Bin | Reports and facts |
|---|---|
| Q1 | r1 Occ; r2 Occ, Leak (q=½); r3 Elec; r4 Leak; r5 Elec |
| Q2 | r6 Occ; r7 Occ; r8 Occ, Elec (q=½); r9 Leak; r10 Elec |
| Q3 | r11 Occ; r12 Occ; r13 Occ; r14 Occ, Leak (q=½); r15 Elec |
| Q4 | r16 Occ; r17 Occ; r18 Occ; r19 Occ; r20 Elec (q=⅘) |

**Cells.** `n` is the number of distinct reports, `S₁ = Σπ`, `S₂ = Σπ²`, and `Var = S₁ − S₂`.
`Var` is the uncorrected, false-positive-only variance (Section 2). The zeros do not mean that the counts are certain.
The columns are Q1, Q2, Q3, Q4.

| Concept | n | S₁ | S₂ | Var |
|---|---|---|---|---|
| Occlusion | 2, 3, 4, 4 | 2, 3, 4, 4 | 2, 3, 4, 4 | 0, 0, 0, 0 |
| Leak | 2, 1, 1, 0 | 3/2, 1, 1/2, 0 | 5/4, 1, 1/4, 0 | 1/4, 0, 1/4, 0 |
| Mechanical | 3, 4, 4, 4 | 3, 4, 4, 4 | 3, 4, 4, 4 | 0, 0, 0, 0 |
| Electrical | 2, 2, 1, 1 | 2, 3/2, 1, 4/5 | 2, 5/4, 1, 16/25 | 0, 1/4, 0, 4/25 |
| Problem | 5, 5, 5, 5 | 5, 5, 5, 24/5 | 5, 5, 5, 116/25 | 0, 0, 0, 4/25 |

**Roll-up on the concept axis (Proposition 1).** Mechanical in Q1 is `{r1, r2} ∪ {r2, r4} = {r1, r2, r4}`, so
`n = 3`. The sum of the child counts is `2 + 2 = 4`, which counts r2 two times. In Q3, Mechanical is
`{r11..r14} ∪ {r14}`, so `n = 4`, but the child sum is 5. In Q2 and Q4 the children do not overlap, so both numbers agree.
This is why Section 5 uses `max(children) ≤ parent ≤ sum(children)` and not an equality: in Q1,
`max(2, 2) = 2 ≤ 3 ≤ 4 = 2 + 2`.
For r2, the Mechanical formula is `x_{Occ} ∨ x_{Leak}` with `q = 1` and `q = ½`, so `π = 1 − (1−1)(1−½) = 1`, not `1 + ½`.

**Boolean predicate (Section 2).** Q1, `Leak ∧ Mechanical` for r2: `S_A = {x_Leak}`, `S_B = {x_Occ, x_Leak}`.
`N(S_A) = ½`, `N(S_B) = 0`, `N(S_A ∪ S_B) = 0`, so `P = 1 − ½ − 0 + 0 = ½`. This is equal to `P(Leak)`, as it must be,
because Leak is under Mechanical. `Occlusion ∧ Leak` for r2: `S_A` and `S_B` are disjoint, so
`P = 1·½ = ½`. We checked the formula against enumeration of all worlds, for these cases and for an overlapping
case with `q = (0.3, 0.5, 0.7)`.

**Roll-up on the time axis.** Occlusion for Q2–Q4 is `3 + 4 + 4 = 11`. With prefix sums
`P = (2, 5, 9, 13)`, this is `P[4] − P[1] = 13 − 2 = 11`.

**Slope (∇, OLS on the series, x = 1, 2, 3, 4).** `x̄ = 5/2`, `Sxx = 5`, so the weights are
`w = (x − x̄)/Sxx = (−0.3, −0.1, 0.1, 0.3)`. The slope is `Σ wₖ S₁ₖ` and its variance is `Σ wₖ² Varₖ`
(independent reports in different bins).

| Series | Values (S₁) | Slope | Variance | SE |
|---|---|---|---|---|
| Occlusion | 2, 3, 4, 4 | 0.70 | 0 | 0 |
| Mechanical | 3, 4, 4, 4 | 0.30 | 0 | 0 |
| Electrical | 2, 1.5, 1, 0.8 | −0.41 | 0.0169 | 0.13 |
| Leak | 1.5, 1, 0.5, 0 | −0.50 | 0.025 | ≈0.158 |

Check for Electrical: slope `= −0.3·2 − 0.1·1.5 + 0.1·1 + 0.3·0.8 = −0.6 − 0.15 + 0.1 + 0.24 = −0.41`;
variance `= 0.09·(4/25) + 0.01·(1/4) = 0.0144 + 0.0025 = 0.0169`. Problem in Q4 has `S₁ = 24/5` because r20 has
`π = 4/5`, so its slope is `−3/50 = −0.06` with variance `9/625`.

**Reconciliation (Section 5, concept axis, Q1, identity weights).** Suppose the corrected cells are
`y = (Occ, Leak, Mech) = (2, 2, 1.5)`. The constraints are `Occ ≤ Mech`, `Leak ≤ Mech` and `Mech ≤ Occ + Leak`.
Mechanical is below both children, so the first two are active. Set `Occ = Leak = Mech = t`.
Then `min (t−2)² + (t−2)² + (t−1.5)²` gives `t = (2 + 2 + 1.5)/3 = 11/6`, and `Mech ≤ Occ + Leak` holds
(`11/6 ≤ 11/3`). Both multipliers are positive, so this is the projection. We checked it with a numeric solver.
With weights `W = diag(1, 1, 1/4)` (Mechanical is four times less variable), the same steps give
`t = (2 + 2 + 1.5·4)/(1 + 1 + 4) = 10/6 = 5/3`. The more certain cell moves less (`1.5 → 5/3`, and the children move `2 → 5/3`).

**Not covered yet:** correction (Se, Sp) and change-points. Add them as unit tests when the code exists.

## 10. Finalized specification (v1.0, 2026-11-19)

Sections 1–9 stay as the derivation and the record of earlier decisions. This section is the normative version:
where it is more precise than Sections 1–9, this section wins. The reference implementation (`cuberag/`) and the
law tests (`tests/test_laws.py`, `tests/test_toy.py`) follow this section. Items marked **[user]** need Chenyang's
judgment (Section 10.7).

### 10.1 Objects

| Object | Definition |
|---|---|
| Reports `R` | Each `r` has one base time bin `t(r) ∈ T₀` and one value `a_d(r)` per attribute dimension `d` (a missing value is the explicit value `NA`). |
| Concepts `(L, ≤)` | A finite poset with top ⊤, given as (child, parent) pairs. **Multiple parents are allowed (DAG).** It need not be a lattice: no join is used anywhere. `↓ℓ` is the down-set. |
| Calendar `(T₀, ≤)` | Base bins `0..|T₀|−1` in a total order. A level is a monotone map `λ : T₀ → T_λ`, so each coarse bin is an interval of base bins. A time slice is an interval `[lo, hi]` of base bins. |
| Fact | `f = (r, ℓ, q, s)`: report, concept, score `q ∈ [0,1]`, source span. Its time and attributes are those of r. **One variable per (report, concept)**: duplicates merge, `q = max`, all spans are kept as provenance (D3). |
| Lineage semiring `S` | `PosBool[X]`, `X` = one Bernoulli variable `x_f` per merged fact. Canonical form: an antichain of monomials (minimal monotone DNF). This form is unique, so equality of formulas is equality of functions. `⊕ = ∨`, `⊗ = ∧`, `0 = false`, `1 = true`. |
| Predicate algebra | `Bool[X] ⊇ PosBool[X]`, used only to evaluate predicates with `¬`. No canonical form is stored. |
| Cube value | `K = S^R` (finitely supported maps report → formula), ⊕ and ⊗ pointwise. |

### 10.2 The cube

- Base cell: `C₀[ℓ](r) = ⋁ { x_f : f fact of r with concept exactly ℓ }`.
- Concept roll-up (zeta transform): `C[ℓ] = ⨁_{ℓ' ∈ ↓ℓ} C₀[ℓ']`.
- A cell `(ℓ, σ)` for a slice σ is the restriction `C[ℓ]|_σ`. Because each report has one time bin and one value per
  dimension, slicing is a restriction of the support and needs no recomputation.
- Evaluations of a cell value `v ∈ K`, all read at the end:
  - `ev_w : S → 𝔹` for a world `w ⊆ X`: a semiring homomorphism. `ev₁ = ev_X` gives the distinct bitmap.
  - `π_r = P(v(r))` under independent `x_f ~ Bernoulli(q_f)` (exact: Shannon expansion over the report's variables).
  - Moments `(n, Σπ, Σπ²)` per base cell, stored as prefix arrays over `T₀` for each attribute combination.
  - Provenance: the variables of `v(r)` and their spans.

### 10.3 Operations (complete list)

| Operator | Type | Definition |
|---|---|---|
| Slice / dice `σ_θ` | `K → K` | `θ = (time interval, value set per dimension)`. Dice is a slice on several dimensions. `σ_θ ∘ σ_θ' = σ_{θ∧θ'}` (meet = interval and set intersection). |
| Concept roll-up `ρ_ℓ` | read `C[ℓ]` | Zeta transform above. Drill-down reads the stored `C[c]` of a child. Roll-up has no inverse; we never need one. |
| Time roll-up `ρ_λ` | vector → vector | Sum of the base-bin counts in each coarse bin of level λ. |
| Predicate `⟦p⟧` | `K` (or `Bool[X]^R`) | Homomorphic extension: `⟦ℓ⟧ = C[ℓ]`, `⟦p∧q⟧ = ⟦p⟧ ⊗ ⟦q⟧`, `⟦p∨q⟧ = ⟦p⟧ ⊕ ⟦q⟧`, `⟦¬p⟧ = ¬⟦p⟧` in `Bool[X]`. |
| Count `γ_count(p, σ)` | random variable | `N = Σ_{r ∈ σ} 1[⟦p⟧(r)]`. Point value `Σπ`, bitmap `{r : ev₁(⟦p⟧(r))}`. |
| Sum / mean `γ_sum(v)`, `γ_mean(v)` | random variable | `Σ_r v(r) 1[⟦p⟧(r)]` for a numeric attribute v; mean = sum ÷ count (delta method). *Specified, not yet implemented.* |
| Series `BY λ` / group-by `BY d` | vector of counts | One count per coarse time bin / per listed value of dimension d. |
| `Δ(x, y)`, `x ÷ y`, `∇`, `÷E` | normal form | See 10.5. `÷E` divides bin k by a fixed exposure `E_k`. `∇` is the OLS slope with fixed x. |
| `κ` (change-point) | outside the normal form | Point locations only; no interval claim (Prop 2(c) excludes it). *Not implemented.* |

Composition is the grammar of Section 4. A group-by over a concept's children is allowed but is **not** a partition
(a report can be under several children); it returns a vector with its full covariance.

### 10.4 Laws (each one is a test)

| # | Law | Test |
|---|---|---|
| L1 | `(S, ⊕, ⊗, 0, 1)` is a commutative semiring and a bounded distributive lattice: associativity, commutativity, identities, annihilation by 0, **idempotence** of ⊕ and ⊗, both distributive laws, absorption, `a ⊕ 1 = 1`. | `test_L1_*` |
| L2 | Every `ev_w` (and `ev₁`) is a semiring homomorphism to 𝔹. Formulas are equal iff they agree on every world (canonical form). `φ.implies(ψ)` is the pointwise order. | `test_L2_*` |
| L3 | `P` is a valuation, not a homomorphism: `P(0)=0`, `P(1)=1`, monotone, modular `P(a∨b)+P(a∧b)=P(a)+P(b)`. `P(a∧¬b)=P(a)−P(a∧b)`. The closed forms of Section 2 agree with enumeration. | `test_L3_*` |
| L4 | Zeta = recursive roll-up: `C[ℓ] = C₀[ℓ] ⊕ ⨁_{c child of ℓ} C[c]`, for any DAG. This needs idempotence of ⊕ (a descendant reachable by two paths is added twice). Roll-up is monotone: `ℓ ≤ ℓ' ⇒ (C[ℓ](r) ⇒ C[ℓ'](r))`, so bitmaps and `π` grow. | `test_L4_*` |
| L5 | Proposition 1: `|ev₁(C[ℓ]|_σ)|` equals the brute-force number of distinct reports in σ with a fact under ℓ, and `max_c n_c ≤ n_ℓ ≤ Σ_c n_c + n_{ℓ-own}`. | `test_L5_*` |
| L6 | Predicates are homomorphic (`⟦p∧q⟧ = ⟦p⟧⊗⟦q⟧`, `⟦p∨q⟧ = ⟦p⟧⊕⟦q⟧`). Bitmaps of `∧, ∨, ∧¬` are `∩, ∪, ∖`. Expected counts are modular (`E N(p∨q) + E N(p∧q) = E N(p) + E N(q)`) and complementary (`E N(p) + E N(¬p) = |σ|`). | `test_L6_*` |
| L7 | Slices: `σ∘σ' = σ'∘σ = σ_{θ∧θ'}`, `σ∘σ = σ`. Slicing commutes with predicate formation and roll-up (it is a restriction). Counts are additive over any partition of the time or attribute axis. Prefix-array range moments equal the direct sums. | `test_L7_*` |
| L8 | Time roll-ups compose: `ρ_{q→y} ∘ ρ_{m→q} = ρ_{m→y}`, and totals are preserved. | `test_L8_*` |
| L9 | Linear operators: OLS weights satisfy `Σw = 0` and `Σ w x = 1`; the slope ignores an added constant and scales linearly. The variance of a linear query is `wᵀΣw` with the **exact** covariance `Cov(N, N') = Σ_r [P(e_r ∧ e'_r) − π_r π'_r]`. This equals the variance over all possible worlds. | `test_L9_*` |
| L10 | Proposition 2(a): the PPI estimator is exactly design-unbiased (checked by enumeration of every SRSWOR sample). | `test_L10_*` |
| L11 | Proposition 3: the projection is in 𝒦, is idempotent, and is non-expansive in the `W⁻¹` norm toward any `x* ∈ 𝒦`. | `test_L11_*` |

**Non-laws (stated so that nobody relies on them).**
- `n_ℓ ≠ Σ_c n_c` in general (multi-label reports). The gap is `Σ_r (m_r − 1)`.
- `P` does not commute with ⊕ and ⊗: `P(a ∨ b) = P(a) + P(b) − P(a)P(b)` only if a and b have disjoint variables.
- ⊕ has no inverse, so there are no prefix sums of formulas. Only the evaluated moments have prefix arrays.
- Negation does not commute with roll-up: `⟦¬ℓ⟧ ≠ ⨁_{ℓ'≤ℓ} ⟦¬ℓ'⟧`. Negation is applied after roll-up and is never stored.
- The projection is not linear, and the reconciled values are biased (Proposition 3, remark).
- Raw-moment variances are false-positive-only. They are **not** valid intervals (confirmed in the pilot,
  EXPERIMENTS.md Section 8).

### 10.5 How a query is evaluated

1. **Parse** (LLM, later): question → expression of the grammar. An unknown concept goes to the "new concept" path
   (not in the reference code).
2. **Compile** to the normal form `(N, g)`: a vector of component counts `N_i = γ_count(p_i, σ_i)` and a map g.
   Count, series, group-by, Δ, ∇ and ÷E give a linear g (`g(θ) = Aθ`). A ratio gives a smooth g.
3. **Cells**: for each component, restrict `⟦p_i⟧` to the reports of `σ_i`. The support comes from the bitmaps;
   for `¬` it is the whole slice.
4. **Estimate** θ and Σ with one of two estimators:
   - *raw*: `θ_i = Σ_r π_ir`, `Σ_ij` exact from the formulas (L9). For diagnostics only.
   - *ppi* (the default for every reported interval): `θ̂_i = Σ_r f_ir + Σ_h (N_h/n_h) Σ_{r∈U_h} (y_ir − f_ir)`, with
     `f_ir = π_ir 1[r ∈ σ_i]`, and joint covariance `Σ̂ = Σ_h N_h²(1 − n_h/N_h)/n_h · S_h`. Here `S_h` is the sample
     covariance of the residual vectors `e_r = y_r − f_r` in audit stratum h. This is the estimator of Prop 2(c′)
     and closes the open estimator of item 8.5. `y_ir` is the oracle label of the **combined** predicate `p_i`,
     not a combination of atom labels.
5. **Reconcile** (optional): project the component vector onto 𝒦 with `W = Σ̂` (fixed after estimation). Intervals
   come from the constrained-region rule of Section 5, not from the projected point.
6. **Answer**: `g(θ̂)` with covariance `J Σ̂ Jᵀ` (J = A for a linear g, a numerical Jacobian otherwise), and a normal
   95% interval.
7. **Cite**: the provenance spans of the variables of the reports with the highest π in each component.

### 10.6 Decisions (resolved here)

| # | Decision | Rationale |
|---|---|---|
| D1 | Store formulas in the canonical antichain form. | Equality and the order are syntactic (L2). The size stays small because atom cells are disjunctions of single variables. |
| D2 | Exact probabilities by Shannon expansion over the variables of a report. | Exact for any Bool[X] expression. A report has few variables (at most the number of concepts that the extractor emits for it). The closed forms of Section 2 are special cases (tested). |
| D3 | One variable per (report, concept). Duplicates merge with `q = max`. | Two spans that state the same concept are not independent evidence. If we treat them as independent, π is too large. **[user]** |
| D4 | The concept poset can be a DAG. No joins are needed. | Taxonomies (MedDRA, FDA codes) have terms with several parents. L4 holds for any poset because ⊕ is idempotent. |
| D5 | Time: one base bin per report. Levels are monotone maps. Slices are intervals. | Time roll-up is then exactly additive, and prefix arrays are valid. A time set that is not an interval is a union of slices (additive, L7). |
| D6 | Attributes: one value per dimension per report, with an explicit `NA`. A slice that does not list `NA` excludes it. | The cells stay a partition (L7). A multi-valued attribute (for example several devices in one report) must be a concept, not an attribute. |
| D7 | Δ, ratio and group-by use the exact covariance (raw) or the joint audit covariance (ppi), never an independence assumption. | Overlapping slices share reports. The formulas give the covariance exactly (L9). |
| D8 | PPI is the default correction. Rogan–Gladen is an ablation. | PPI is exactly unbiased with no assumption on the extractor (L10, Prop 2(a)). Rogan–Gladen needs constant Se and Sp in each stratum. **[user]** |
| D9 | The correction is applied to the combined predicate cell, with oracle labels for the combined predicate. | Se and Sp of `A ∧ ¬B` are not functions of the atom Se and Sp without independence. Item 8.2 already says to correct the combined cell. |
| D10 | Change-points (κ), `γ_sum`, `γ_mean` and Rogan–Gladen are specified but not in the reference code. | This follows the scope-cut order of PROPOSAL.md Section 5. |

### 10.7 Questions for Chenyang

> Tracked in [issue #12](https://github.com/ChenyangLi4288/cube_rag/issues/12) (2026-11-20).

1. D3: merge duplicate facts with `q = max`, or use noisy-or over spans? Noisy-or assumes that the spans are independent.
2. D8: is PPI the headline estimator, with Rogan–Gladen only as an ablation?
3. The pilot (EXPERIMENTS.md Section 8) shows that a top-k reader is a weak count baseline by construction.
   Should the paper also include a "retrieve all above a threshold" dense baseline, which has no fixed k?
4. Should the audit be stratified by extractor score (more efficient for rare concepts) instead of by cell?
   The estimator in 10.5 supports any strata.

### 10.8 Reference implementation

- Code: `cuberag/posbool.py` (S, Bool[X], probabilities), `cuberag/lattice.py`, `cuberag/cube.py` (cube, slices,
  predicates, counts), `cuberag/query.py` (normal form, raw and PPI estimators), `cuberag/reconcile.py`.
- Tests: `python -m pytest tests` (the Section 9 toy cube, and hypothesis tests of L1–L11).
- Pilot on public MAUDE data: `python scripts/fetch_maude.py`, then `python scripts/run_small_eval.py`.
  The results are in EXPERIMENTS.md, Section 8.

## 11. Addendum (2026-11-19): audit designs for the PPI estimator

This section adds to Section 10 and changes nothing in it. It answers question 4 of Section 10.7 (stratify
the audit by extractor score instead of by cell). The estimator of 10.5 already supports any strata. This section
gives the conditions under which a score-dependent design stays exactly unbiased, adds a Poisson (IPW) design,
says how to allocate the audit, and says what a design cannot fix. Code: `cuberag/audit.py` and the Poisson branch
of `cuberag/query.py::ppi_moments`. Tests: `tests/test_audit_design.py` (laws L12, L13).

### 11.1 Setup

The frame is the set of reports `R` (size N) that the cube was built on. A query in normal form has components
`i = 1..m`. For report r, `f_ir = π_ir 1[r ∈ σ_i]` (known for every report), `y_ir` is the oracle label of the
combined predicate `p_i` (known only for audited reports, D9), and `e_r = y_r − f_r ∈ ℝ^m`. The target is
`θ = Σ_r y_r = Σ_r f_r + Σ_r e_r`. The only random thing is the audit sample U. The extractor scores, and
everything computed from them, are fixed before the audit, so they are constants under the design.

**Design rule.** Strata, allocations and inclusion probabilities may depend on anything known before the audit:
extractor scores of the frame, concept rarity estimated from scores, time and attribute cells, and labels of a
*different* split (for example the train split). They must not depend on oracle labels of the frame. If they
did, the inclusion probabilities would be random, and 11.2 and 11.3 would not hold.

### 11.2 Stratified SRSWOR with arbitrary strata (score, rarity, or cell)

Strata `h` partition R (`N_h` reports), and `n_h` reports are drawn without replacement in each stratum.
The inclusion probability is `n_h/N_h`, so the design weight (inverse probability) is `N_h/n_h`. The estimator
is that of 10.5:

`θ̂ = Σ_r f_r + Σ_h (N_h/n_h) Σ_{r∈U_h} e_r`,  `Σ̂ = Σ_h N_h² (1 − n_h/N_h)/n_h · S_h(U)`,

where `S_h(U)` is the sample covariance (divisor `n_h − 1`) of the residual vectors in `U_h`.

**Proposition 5.** For any strata that satisfy the design rule, and any allocation with `n_h ≥ 2` or `n_h = N_h`:
(a) `E θ̂ = θ` (exactly, for every component);
(b) `Cov θ̂ = V := Σ_h N_h² (1 − n_h/N_h)/n_h · S_h^pop`, where `S_h^pop` is the covariance of `{e_r : r ∈ h}`
with divisor `N_h − 1`;
(c) `E Σ̂ = V`.
For a linear query `g(θ) = Aθ` (count, series, group-by, Δ, ∇, ÷E), the answer `Aθ̂` is unbiased with variance
`A V Aᵀ`, and `A Σ̂ Aᵀ` is unbiased for it. The joint covariance stays exact in the sense of Section 10 (D7):
no independence between components is assumed. Overlapping slices and Boolean combinations are handled because
`e_r` is a vector for the same report.

*Proof.* In each stratum, SRSWOR makes `(N_h/n_h) Σ_{U_h} e_r` unbiased for `Σ_{r∈h} e_r`. It has covariance
`N_h²(1 − n_h/N_h)/n_h · S_h^pop`, and `S_h(U)` is unbiased for `S_h^pop`. These are the standard results,
applied to each coordinate and each pair of coordinates. Strata are sampled independently, so the means and the
covariances add over h. The `Σ_r f_r` term is a constant. ∎

Proposition 2(a) of Section 10 (L10) is the special case of one stratum. A score-stratified audit is this same
estimator with strata defined by the extractor score. **No new estimator is needed, only a new design.**

### 11.3 Poisson sampling (inverse-probability weighting)

Each report is audited independently with a known probability `p_r ∈ (0, 1]`. Then

`θ̂ = Σ_r f_r + Σ_{r∈U} e_r/p_r`,  `Σ̂ = Σ_{r∈U} (1 − p_r)/p_r² · e_r e_rᵀ`.

**Proposition 6.** (a) `E θ̂ = θ`; (b) `Cov θ̂ = V := Σ_{r∈R} (1 − p_r)/p_r · e_r e_rᵀ`; (c) `E Σ̂ = V`.
*Proof.* The inclusion indicators `I_r` are independent Bernoulli(`p_r`). Then `E[I_r/p_r] = 1`,
`Var(I_r/p_r) = (1 − p_r)/p_r` and `E[I_r (1 − p_r)/p_r²] = (1 − p_r)/p_r`. ∎

A report with `p_r = 1` is a take-all unit and adds no variance. The sample size is random, with mean `Σ p_r`.
This design is the Horvitz–Thompson form of the residual (difference) estimator.

### 11.4 Allocation (efficiency only; unbiasedness never depends on it)

Let the objective be a weighted sum of component variances `Σ_ℓ w_ℓ Var(N̂_ℓ)` over the concept cells that the
cube will be asked about. With `w_ℓ = 1/N_ℓ²`, this is the summed *relative* variance, so rare concepts count as
much as common ones (the "concept rarity" option). Define the predicted squared residual of a report,
`d_r = Σ_ℓ w_ℓ ê²_rℓ`.

- Stratified: the strata are quantiles of `d_r`. The Neyman allocation is `n_h ∝ N_h S_h` with
  `S_h² = Σ_ℓ w_ℓ S²_hℓ ≈ mean_{r∈h} d_r`, with the bounds `2 ≤ n_h ≤ N_h`. The implementation solves
  `n_h = clip(λ N_h S_h, 2, N_h)`, `Σ n_h = n` for λ by bisection, then rounds by largest remainders.
- Poisson: minimizing `Σ_r (1/p_r − 1) d_r` subject to `Σ p_r = n` gives `p_r ∝ √d_r`, capped at 1.
  We mix in a uniform floor (20% of n). This bounds every weight `1/p_r` by `5N/n`, so a badly predicted `d_r`
  cannot produce a huge weight.
- `ê²_rℓ` must be computed before the audit. In the pilot it comes from the isotonic calibration
  `ĝ_ℓ(π) ≈ P(y = 1 | π)`, fitted on cross-fitted scores of the **train** split. Then
  `ê² = ĝ(1 − π)² + (1 − ĝ)π²`. If an extractor has no train-split run, a proxy `π(1 − π) + ε` is used
  (`ε = 0.005`). A wrong `ê²` costs efficiency, never bias (Propositions 5 and 6 hold for any fixed design).

### 11.5 What no design can fix (rare cells)

Normal intervals need the sampled residual sum to be close to Gaussian. Take a cell with K positives that the
extractor misses (`π ≈ 0`), spread over a stratum of size `N_h`. Under SRSWOR with `n_h` draws, the probability
that the audit sees none of them is about `(1 − K/N_h)^{n_h}`. In that event, `S_h(U)` has no contribution from
them, the interval is too narrow (often of zero width), and it misses the truth. In the pilot, `K ≈ 10`,
`N_h = 3000` and `n = 150` give `(1 − 1/300)^150 ≈ 0.61`. This is the 0.41 coverage for counts under 20 in
Section 8. Score strata help only if the missed positives are concentrated in strata that can be oversampled,
that is, if the score ranks them above the true negatives. Otherwise the remedies are fewer missed positives
(a better extractor), a larger audit, or an interval that does not rely on the CLT (future work). The design
bounds this failure but does not remove it. EXPERIMENTS.md Section 9 measures it.

### 11.6 Laws (each one is a test)

| # | Law | Test |
|---|---|---|
| L12 | Proposition 5: with two strata and unequal sampling fractions, enumerate every stratified sample of a 3-component query (two slices, one `A ∧ ¬B`, arbitrary 0/1 oracle labels). The mean of `θ̂` equals θ, the covariance of `θ̂` equals `V`, and the mean of `Σ̂` equals `V`. All three are exact. | `test_L12_stratified_unbiased_and_exact_covariance` |
| L13 | Proposition 6: the same three identities for Poisson sampling with unequal `p_r`, by enumeration of every subset weighted by its probability. | `test_L13_poisson_ipw_unbiased_and_exact_covariance` |
| L12–13 (simulation) | A yearly-slope query on a 400-report synthetic cube with missed positives, score strata with Neyman allocation, and Poisson with `p ∝ √d`. Over 3,000 replicate audits, the mean slope estimate is within 4 Monte Carlo SE of the truth, the Monte Carlo variance is within 8% of `wᵀVw`, and the mean of the estimated variances is within 6% of it. | `test_L12_L13_slope_covariance_by_simulation` |
| — | The allocation sums to n and respects `min(2, N_h) ≤ n_h ≤ N_h`. Poisson probabilities sum to n and are ≤ 1. Score strata keep a separate zero-score stratum. | `test_neyman_allocation_bounds`, `test_allocation_strata_and_probs` |

**Non-law.** A design chosen after looking at frame labels (for example, re-stratifying after a pilot audit of
the same frame and reusing those labels) is outside Propositions 5 and 6. A two-phase design needs its own
derivation and is not implemented.
