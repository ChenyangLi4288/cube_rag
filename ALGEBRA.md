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

`K = 𝔹ᴿ × 𝔼₂ × ℕ[S]`. Each operation applies to each component separately.

1. **Distinct bitmap** `𝔹ᴿ = (2^R, ∪, ∩, ∅, R)`. The annotation of a fact from report r is `{r}`.
2. **Second-order expectation semiring** `𝔼₂` (Li and Eisner, 2009).
   - The value for one report with calibrated probability π is `(1, π, π²)`.
   - ⊕ adds the components: a cell holds `(n, Σπ, Σπ²)`.
   - The expected count of a cell is `Σπ`. The variance (independent Bernoulli reports) is `Σπ − Σπ²`.
   - We count distinct reports. Thus, we first make one value for each report:
     `π_r(ℓ)` = P(report r states at least one concept in ↓ℓ). Then we add the reports (Proposition 1).
   - **The ⊗ rule (draft, to check against Li and Eisner).** ⊗ applies only to the values of one report, to
     combine independent facts of that report (for example the predicate `p ∧ q`). It is componentwise:
     `(n₁, a₁, b₁) ⊗ (n₂, a₂, b₂) = (n₁n₂, a₁a₂, b₁b₂)`. For single-report values `(1, π, π²)`, the result is
     `(1, π₁π₂, (π₁π₂)²)`, which is the encoding of a report with probability π₁π₂. The unit is `(1,1,1)` and the
     zero is `(0,0,0)`. This is the product ring `ℕ × ℝ × ℝ`, so ⊕ and ⊗ satisfy the semiring laws
     (including distributivity). We never multiply two aggregated cells: ⊗ happens before ⊕ over reports.
     Li and Eisner (2009) define a different ⊗ for tuples `(p, r, s, t)` (with cross terms such as `r₁s₂ + r₂s₁`).
     Ours does not need those terms because we track only the first two moments of an indicator.
     A union of concepts inside one report is not ⊕ of the 𝔼₂ values. We compute it as
     `π_r(ℓ) = 1 − ∏_f (1 − q_f)` over the facts f of r under ↓ℓ, which assumes that the facts of one report are
     independent.
3. **Provenance** `ℕ[S]`. These are polynomials over span IDs. ⊕ is +, and ⊗ is ×.
   We use this component only for citations and audit samples.

**Why this design.** The bitmap component uses union. Thus, a report with two child concepts counts one time
in the parent. The 𝔼₂ component adds only over distinct reports. A plain counting semiring cannot do both.

## 3. The cube

`𝒞 : L × T × A → K`

`𝒞[ℓ,τ,a] = ⨁ { ann_r(↓ℓ) : t(r) ∈ τ, a(r) ∈ a }`

`ann_r(↓ℓ)` combines all facts of report r under ↓ℓ into one value for the report.

- **Roll-up on L (zeta transform).** The bitmap of ℓ is the union of the bitmaps of all ℓ' ≤ ℓ.
  We calculate the 𝔼₂ value again from this union. We do not add the 𝔼₂ values of the children.
- **Roll-up on T.** Prefix arrays `P[τ] = ⨁_{τ' ≤ τ} 𝒞[τ']` (Fenwick tree). A range aggregate takes O(log |T|).
- **Boolean predicates.** We calculate `p ∧ q`, `p ∧ ¬q` and `p ∨ q` on the bitmaps first.
  Then we combine the report probabilities. We must state the assumption (independence or a copula).
  We test both assumptions (ablation).

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
   Thus, the intervals of Proposition 2 do not carry over to the reconciled values. Open item 5 below.
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
  → `γ_count(σ_{year=2025, event_type=Injury}(↓Occlusion))`.
  Note: `event_type` is hidden for evaluation of extraction. Here we use it as a filter attribute.
- **VAERS.** "What is the trend of myocarditis reports per million doses, 2021 Q1 to 2023 Q4, ages 12–29?"
  → `∇(Agg(↓Myocarditis, σ_{age∈[12,29]}) BY quarter ÷E doses)`. Lattice: MedDRA. Exposure: CDC doses.
- **ASRS.** "Did runway-incursion reports change from 2018 to 2023, when we include the change in traffic?"
  → `κ(Agg(↓RunwayIncursion) BY month ÷E operations)`.
  The raw counts decrease in 2020 because there were fewer flights. They do not show a change in safety.

## 8. Open items

1. The ⊗ rule for the 𝔼₂ component is drafted in Section 2. It still needs a check against Li and Eisner (2009)
   and Chenyang's agreement.
2. Decide the assumption for Boolean combinations (independence or a copula). The default is independence
   (STUDENT_START.md, Section 7).
3. Decide if the same event_type field can be a filter attribute and a hidden field at the same time (Section 7).
4. Toy example: done (Section 9). It has counts, roll-up and slope. It does not yet have reconciliation, correction
   or change-points.
5. Intervals after reconciliation (Proposition 3 remark): find a result, or report only the pre-reconciliation
   intervals.

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
For r2, the Mechanical probability is `1 − (1−1)(1−½) = 1`, not `1 + ½`.

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

**Not covered yet:** correction (Se, Sp), reconciliation, and change-points. Add them to this example later.
