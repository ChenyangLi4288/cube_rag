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
4. **Provenance.** The polynomial semiring `ℕ[X]` of Green et al. maps onto `S` by a homomorphism. If we want
   citations with multiplicity, we use `ℕ[X]` where we now use `S`. Each fact variable has a source span, so
   the formula gives citations and audit samples.

**Assumptions.** (i) The events `x_f` of different facts are independent, including facts of one report.
(ii) The scores `q_f` are calibrated. These are modelling assumptions about the extractor, not properties of the
algebra. The audit set corrects the cell totals in Section 5 and does not depend on (i) and (ii)
for its unbiasedness (Proposition 2(a)).

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
- **Boolean predicates.** `p ∨ q` is ⊕ and `p ∧ q` is ⊗ on the per-report formulas. The probability of the result
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
  (or a PPI rectifier). The corrected cell is `θ̂ = (θ_raw − (1 − Sp)) / (Se + Sp − 1)` (Rogan–Gladen),
  or the PPI++ form. The variance includes the uncertainty from the audit.
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
- **Intervals after reconciliation.** Let `y ~ N(x*, Σ)` asymptotically, with `Σ̂` from Proposition 2, and let
  `c = χ²_{d,1−α}`. For a target `w·x`, the interval is `[min, max]` of `w·x` over
  `{x ∈ 𝒦 : (x − y)ᵀ Σ̂⁻¹ (x − y) ≤ c}`. Because the region contains `x*` whenever the unconstrained ellipsoid does,
  and `x* ∈ 𝒦`, the coverage is at least `1 − α` asymptotically. It is conservative (it uses d degrees of freedom
  and ignores that the constraints cut the region). The point estimate is the projection of Section 5 and the
  interval does not have to be centred on it. Report the width and the empirical coverage.
  A simpler fallback is to clip each Proposition 2 interval to the range allowed by 𝒦.
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
   Hence this proposition is the statement that `ev₁` commutes with ⊕ and ⊗.
   The sum of the child counts is not equal to this number when a report has facts under more than one child:
   it is larger by `Σ_r (m_r − 1)`, where `m_r ≥ 1` is the number of children of ℓ under which r has a fact
   (if no fact is at ℓ itself; the toy cube in Section 9 has an example).
2. **Validity.** Fix a cell set and a cell total `θ = Σ_{r∈R} y_r`, where `y_r ∈ {0,1}` is the reference label.
   The extractor gives a score `f_r ∈ [0,1]` for each report. The audit set `U` is drawn by a design with known
   inclusion probabilities `p_r > 0` (stratified on cells, without replacement).
   - **(a) PPI form.** `θ̂ = Σ_{r∈R} f_r + Σ_{r∈U} (y_r − f_r)/p_r` is exactly design-unbiased for θ. This needs no
     assumption on the extractor.
   - **(b) Rogan–Gladen form.** Suppose Se and Sp are constant within the stratum and `Se + Sp > 1`. Then the
     estimator is asymptotically unbiased as the audit size in the stratum goes to infinity.
   - **(c) Intervals.** In both forms, `θ̂ ± z_{1−α/2} · SE` has asymptotic coverage `1 − α`. The SE includes the
     audit variance. This is true for each linear function `w·θ` (this includes OLS slopes with fixed time points)
     and, by the delta method, for each smooth `g(w·θ)` with `∇g ≠ 0` (this includes ratios and rates).
     It is not claimed for Theil–Sen slopes or change-points.
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
     O(log|T|) with a Fenwick tree (this is needed if we add data). This is valid because each report is in one
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
   Proposition 2 intervals as a fallback. Open: tightness. The width may be large for large d. The hypothesis H3
   (92–97% coverage) may not hold for these intervals, because they are conservative and can cover more than 97%.
   Report coverage and width together.

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
