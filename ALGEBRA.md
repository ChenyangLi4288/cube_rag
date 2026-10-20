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
  consistent vectors: parts of a partition add up to the total (equalities), and a child is not more than its
  parent (inequalities). We solve `min_x (x − y)ᵀ W⁻¹ (x − y)` subject to `x ∈ 𝒦`.
  This is a weighted projection (MinT-type), a quadratic program with inequalities.
- **Drift test.** We test if the extractor error rates change with time τ. For this test, we stratify the audit
  by time. If the rates change, we correct each time block separately.

## 6. Propositions to prove

1. **Distinct counts are correct.** If we evaluate the bitmaps first, `γ_count(𝒞[ℓ,τ,a])` is equal to the number
   of distinct reports in (τ,a) that state at least one concept in ↓ℓ. This is true for each lattice and for
   extraction with many labels.
2. **Validity.** Under the audit design, the corrected cells are unbiased (Rogan–Gladen: asymptotically;
   PPI form: exactly). Wald or PPI intervals have the nominal coverage asymptotically. This is also true for each
   linear function `w·θ`, and (with the delta method) for ratios and slopes.
3. **Reconciliation does not make results worse.** If the true values are in the convex set 𝒦, the W-projection
   does not increase the W-weighted MSE. (A projection onto a closed convex set is non-expansive.)
4. **Complexity.** The index size is O(|facts| + |L|·|T|·|A_nonempty|). A range count takes O(log|T|) for each cell.
   A slope over k bins takes O(k).
5. **Cost over many queries.** For m queries, CubeRAG costs `C_index + C_audit + Σ_j (C_parse + C_lazy(j))`.
   Per-query sampling costs `Σ_j C_sample(j)`. Find the value of m where the two costs are equal.

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

1. Define the ⊗ rule for the 𝔼₂ component with the `(1, π, π²)` encoding. Check it against Li and Eisner (2009).
2. Decide the assumption for Boolean combinations (independence or a copula).
3. Decide if the same event_type field can be a filter attribute and a hidden field at the same time (Section 7).
4. Make a toy example with 20 reports, 5 concepts and 4 time bins. Calculate all operators by hand.
