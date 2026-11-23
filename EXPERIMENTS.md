# Experiments

## 1. Data (public only)

| Dataset | Scope | Text | Filter attributes | Hidden ground truth | Lattice | Exposure |
|---|---|---|---|---|---|---|
| FDA MAUDE | FRN (infusion pumps), insulin pumps, continuous glucose monitors, implantable cardiac defibrillators. Up to about 10⁶ reports. | `mdr_text` | Dates, manufacturer, brand, product code | `event_type`, device and patient problem codes | FDA device and patient problem code hierarchy | None. Second measure: share of all reports for the same product code. |
| VAERS | Domestic reports, 2019 and 2021–2023 | `SYMPTOM_TEXT` | Received date, state, age, sex, vaccine type | `DIED`, `HOSPITAL`, `ER_ED_VISIT`, MedDRA `SYMPTOMS` | MedDRA (PT → HLT → SOC) if the licence permits. If not, clusters of symptom terms. | CDC doses given |
| NASA ASRS | 2018–2023 | Narrative, Synopsis | Date, aircraft, state, flight phase | Anomaly, Primary Problem | ASRS anomaly taxonomy | FAA/BTS flight operations |

Remove the hidden fields from the index. Use them only for ground truth and for the audit oracle.

## 2. CubeQA benchmark

To make the questions:

1. Make question templates from the hidden fields, attribute slices and time ranges.
2. Calculate the ground truth with SQL on the hidden fields.
3. Use an LLM to paraphrase each question.
4. Check a sample of the paraphrases by hand.

| Type | Example | Ground truth | Share |
|---|---|---|---|
| Count | How many … in …? | SQL on hidden fields | 25% |
| Group-by / top-k | Which manufacturers have the most …? | Ranked list | 10% |
| Boolean | … with X but not Z? | SQL | 10% |
| Ratio / proportion | What fraction of …? | SQL | 10% |
| Difference | Did … change from A to B? | Difference and sign | 10% |
| Trend over many periods | Monthly or quarterly series. Slope sign and size. | OLS on the true series | 15% |
| Change-point | When did … change? | PELT on the true series, with tolerance ε | 5% |
| Rate trend | … per unit of exposure, from A to B | True counts ÷ exposure | 10% |
| Not answerable | The concept or attribute is not in the data. | The system must not answer. | 5% |

Target size: 1,500 questions (500 for each dataset). Freeze the dev/test split.
Report rare concepts (prevalence less than 0.5%) separately.

## 3. Systems to compare

- Vanilla dense RAG
- Long-context LLM (full context if possible, or map-reduce)
- GraphRAG, LightRAG, HippoRAG2, HyperGraphRAG, TG-RAG, KAG
- TAG / TableRAG on extracted tables
- LOTUS, UQE
- Extract-then-SQL (same extractor as CubeRAG, without correction or reconciliation)
- **CubeRAG** (full) and its ablations

Use the same LLMs for all systems: one open-weight model of about 8B, one of about 70B, and one frontier model
on a subset.

## 4. Metrics

- **Accuracy:** relative error, RMSE, percentage of answers within ±5% and ±10%, NDCG for group-by.
- **Trends:** slope sign accuracy, slope relative error, change-point F1 within tolerance, rate error.
- **Calibration:** coverage of 95% intervals, median interval width, precision of "no answer" decisions.
- **Cost:** LLM calls, tokens, GPU hours to build the index, latency for each query, total cost over a workload.
- **Parser:** exact match of the predicted `Q` expression with the gold expression.
  This metric separates parser errors from cube errors.

## 5. Experiments

| ID | Question | Design |
|---|---|---|
| X1 | How do graph-RAG systems fail on counts and trends? | Run all baselines on CubeQA. Put each error into one of the causes C1–C4. |
| X2 | Is CubeRAG more accurate than the baselines? (RQ1, RQ2) | Main table for each dataset and question type |
| X3 | Are the intervals calibrated? (RQ3) | Coverage for audit size n = 50, 100, 200, 500. Rare and common concepts. |
| X4 | What is the cost over many queries? (RQ4) | Total cost against the number of queries. Break-even point against UQE and LOTUS. |
| X5 | Is CubeRAG robust? (RQ5) | 8B and 70B extractors. Lattice variants: full, flat, clusters from embeddings. |
| X6 | Does exposure change the conclusions? | ASRS 2018–2023 and VAERS 2019 against 2021–2023. Raw counts against rates. |
| X7 | Can CubeRAG add new concepts? | Remove some concepts from the lattice. Measure the cost and accuracy of new nodes. |

## 6. Ablations

Remove or change one part at a time:

- No bitmap (add counts, which gives double counts)
- No moments (point estimates only, no intervals for the uncorrected cube)
- No correction
- No reconciliation
- Reconciliation with only the time and attribute sum equalities (no concept-axis inequalities)
- No exposure
- Independent facts within a report against a Gaussian copula for Boolean predicates
- Grammar-limited parsing against free-form parsing

## 7. Compute (estimate)

- Extraction: about 1.5 million reports, one pass with an 8B model. One pass with a 70B model on about 10%.
- Graph-RAG baselines: if the full corpus costs too much, build the index on a stratified subsample of
  50,000 reports or less for each dataset. Document the method.
- Experiments use cached extractions and labels. Runs with a new seed do not need a GPU.

## 8. Small-scale pilot (2026-11-19)

The goal was to check that the finalized algebra (ALGEBRA.md Section 10) runs end to end, and to see how it
compares with plain retrieval. This is a pilot, not a result for the paper.

**Setup.** 5,000 public MAUDE reports for product code FRN (infusion pumps). There are 1,000 per year for
2020–2024: the first 250 openFDA returns per quarter, so this is **not a random sample** (`scripts/fetch_maude.py`,
manifest in `data/raw/`). Split: 40% train, 60% eval (3,000 reports, seed 0). Hidden fields: `product_problems`
(ground truth) and `event_type` (not used).
- Lattice: a provisional hand grouping of 40 frequent FDA problem terms into 8 groups under ⊤. Two leaves have two
  parents. This is not the official hierarchy (task 4 replaces it).
- Extractor: **no LLM is configured**, so we used a local stand-in: TF-IDF plus logistic regression for each leaf,
  trained on the train split with the hidden codes (38 leaves). A fact is emitted if q ≥ 0.05 (11,409 facts).
  On eval at threshold 0.5, the extractor is weak: mean sensitivity is 0.19, and mean PPV is 0.55.
- Cube: quarter bins with a year level, a manufacturer attribute (5 groups). Build time is 2 s.
- Queries: 296 count queries (concept × {all, each year, 3 manufacturers}) and 83 Boolean queries (`A∧B`, `A∧¬B`
  for group pairs). We kept only queries with a true count ≥ 3. There are also 45 yearly-slope queries.
- Baselines: BM25 (our own code) and dense retrieval with `BAAI/bge-small-en-v1.5`, run locally (offline, from the
  HF cache). Both get the slice as a metadata pre-filter, so they are given every advantage. The count baseline is
  a top-k reader with an **oracle**: it counts the true positives in the top k. This is an upper bound for a top-k
  RAG answer.
- Audit: SRSWOR, n = 150 from the eval split. We repeated the draw 200 times.

**Ranking (all 379 queries; the cube ranks by π, with BM25 to break ties).**

| Method | Recall@10 | Recall@100 | R-precision | MRR |
|---|---|---|---|---|
| BM25 | 0.081 | 0.304 | 0.198 | 0.472 |
| Dense (bge-small) | 0.087 | 0.345 | 0.210 | 0.434 |
| Cube (π ranking) | 0.203 | 0.568 | 0.464 | 0.755 |

Caveat: the cube's extractor is **supervised** on codes from the train split. BM25 and dense are zero-shot.
Most of this gain comes from the supervision, not from the algebra. Recall@k is not what the cube is for anyway,
because the cube does not need a fixed k.

**Counts (median relative error; all 379 queries).**

| Method | Median rel. error |
|---|---|
| Top-k oracle reader, BM25 @10 / @50 | 0.978 / 0.891 |
| Top-k oracle reader, dense @10 / @50 | 0.975 / 0.833 |
| Cube, threshold π ≥ 0.5 ("extract-then-SQL") | 0.919 |
| Cube raw `Σπ` | 0.426 (median `Σπ`/truth = 0.58: the weak extractor undercounts) |
| Cube PPI, one audit of n = 150 | 0.552 |
| Cube PPI, mean over 200 audits | 0.028 (unbiased, as L10 says) |

By the true count:

| True count | Queries | PPI rel. err | Raw rel. err | Dense@50 rel. err | PPI 95% coverage | Raw coverage |
|---|---|---|---|---|---|---|
| 3–19 | 152 | 1.20 | 0.75 | 0.67 | 0.41 | 0.24 |
| 20–49 | 80 | 0.54 | 0.42 | 0.85 | 0.76 | 0.35 |
| 50–149 | 80 | 0.28 | 0.22 | 0.87 | 0.91 | 0.35 |
| ≥ 150 | 67 | 0.11 | 0.22 | 0.96 | 0.94 | 0.09 |

**Trends (yearly OLS slope over 5 years, 39 concepts with |true slope| ≥ 1).** Sign accuracy: cube raw 0.97,
cube PPI (mean over audits) 1.00, top-k@50 0.80 (BM25) and 0.87 (dense), top-k@10 0.67 and 0.62.
PPI slope CI coverage is 0.84. These are trends of the sample composition (fixed 1,000 reports per year), not
trends in MAUDE.

**Bitmap vs. sum of children.** With true labels, the sum of the child counts overstates the distinct count by 36%
for Material Integrity (1,529 vs 1,124) and by 6% for Flow/Infusion. With this weak extractor, the no-bitmap
ablation had a *lower* raw error (0.22 vs 0.26), because its double counting partly cancels the extractor's
undercount. That is two errors cancelling, not evidence against the bitmap. It does show that the ablation will
look good whenever the extractor undercounts, so the paper should report it after correction.

**What this pilot shows.**
1. The algebra runs end to end, and all 29 law and toy tests pass.
2. Top-k retrieval cannot answer counts: it has 83–98% median error even with an oracle reader (cause C1).
3. Raw cube moments are biased by extractor recall, and their intervals cover the truth only 26% of the time.
   This confirms item 8.6 of ALGEBRA.md: never report raw intervals.
4. PPI correction is unbiased, and its intervals reach nominal coverage (0.91–0.94) for counts ≥ 50. They fail for
   rare cells (0.41 for counts < 20), because an audit of n = 150 out of 3,000 sees almost no positives. This is the
   failure that RQ3 predicts. With this weak extractor, a single PPI estimate is noisier than the raw estimate for
   small cells. A better (LLM) extractor makes the residuals smaller, and the audit then helps more.
5. Next: an LLM extractor, an audit stratified by score (ALGEBRA.md 10.7, question 4), and a threshold-free dense
   baseline.

## 9. Pilot, round 2: audit designs, threshold baselines, local LLM extractor (2026-11-19)

Same data, split, lattice, cube, and the same 379 count/Boolean queries and 45 yearly-slope queries as Section 8.
Section 8 stays as it was. Script: `scripts/run_audit_eval.py`. Results: `results/audit_eval_<tag>.json` and
`.log`. Every PPI number below averages over **1,000 replicate audits** (n = 150), or 300 where marked. The
vectorized estimator used for the replicates is cross-checked against `cuberag.query.ppi_moments` and
`evaluate(..., "ppi")` on every run (max |diff| ≤ 1e-12). The theory is ALGEBRA.md Section 11. Laws L12 and L13
are tested in `tests/test_audit_design.py`, and all 39 tests pass.

**Audit designs (all n = 150, all exactly unbiased, ALGEBRA 11.2–11.3).**
- `uniform`: SRSWOR, one stratum (Section 8).
- `cell`: strata = year × manufacturer group (25 cells), proportional allocation.
- `score`: 6 quantile strata of the predicted squared residual `d_r = Σ_ℓ ê²_rℓ`, Neyman allocation
  (14 to 37 per stratum). `ê²` comes from an isotonic calibration of 5-fold **cross-fitted train-split** scores,
  so the design uses no eval labels.
- `score_rare`: the same, with rarity weights `d_r = Σ_ℓ ê²_rℓ / N̂_ℓ²` (the summed relative variance).
- `poisson`: Poisson/IPW with `p_r ∝ √d_r` (rarity-weighted) and a 20% uniform floor (p from 0.043 to 0.129).
- `oracle_diag`: **diagnostic only, not a method**. Strata and Neyman allocation come from the *true* eval
  residuals, which breaks the design rule of ALGEBRA 11.1. It is an upper bound on what a better score design
  could gain.

`relerr` is the median over queries of the mean absolute relative error of one audit (the Section 8 "PPI, one
audit" number). `cov` is the coverage of the 95% interval. `design rel. SE` is the exact design SE (ALGEBRA 11.2,
no Monte Carlo noise) divided by the truth, median over queries. `0-width` is the share of audits whose
interval has zero width.

### 9.1 Stand-in extractor (TF-IDF + LR, Se 0.19, PPV 0.55): audit design

| Design | relerr (all) | cov (all) | design rel. SE | 3–19: relerr / cov | 20–49 | 50–149 | ≥150 | slope cov | slope sign (1 audit) |
|---|---|---|---|---|---|---|---|---|---|
| §8 pilot (uniform, 200 audits) | 0.552 | — | — | 1.20 / 0.41 | 0.54 / 0.76 | 0.28 / 0.91 | 0.11 / 0.94 | 0.84 | — |
| uniform | 0.554 | 0.681 | 0.693 | 1.22 / 0.41 | 0.54 / 0.76 | 0.28 / 0.91 | 0.11 / 0.93 | 0.84 | 0.82 |
| cell | 0.554 | 0.679 | 0.704 | 1.16 / 0.41 | 0.55 / 0.75 | 0.28 / 0.90 | 0.11 / 0.93 | 0.83 | 0.82 |
| **score** | **0.499** | **0.706** | **0.633** | 1.10 / 0.44 | 0.49 / 0.81 | 0.25 / 0.91 | 0.10 / 0.94 | 0.86 | 0.83 |
| score_rare | 0.538 | 0.699 | 0.665 | 1.14 / 0.45 | 0.54 / 0.79 | 0.28 / 0.90 | 0.11 / 0.93 | 0.85 | 0.83 |
| poisson | 0.530 | 0.698 | 0.669 | 1.15 / 0.44 | 0.53 / 0.78 | 0.28 / 0.90 | 0.11 / 0.94 | 0.86 | 0.83 |
| *oracle_diag (not a method)* | *0.418* | *0.831* | *0.524* | *0.62 / 0.75* | *0.42 / 0.85* | *0.26 / 0.89* | *0.14 / 0.92* | *0.91* | *0.85* |

Raw `Σπ` (no audit) is unchanged: median relative error 0.426, and `Σπ`/truth = 0.58. The mean over audits is
unbiased for every design (median relative error of the mean over 1,000 audits is 0.010 to 0.012). The share of
zero-width intervals for counts < 20 is 0.31 for uniform, 0.28 for score and 0.10 for oracle_diag.

**Audit size (300 replicates each).** Coverage and error by audit size, for uniform → score:

| n | relerr (all) | cov (all) | cov 3–19 | cov 20–49 | design rel. SE | oracle_diag cov 3–19 |
|---|---|---|---|---|---|---|
| 150 | 0.554 → 0.499 | 0.68 → 0.71 | 0.41 → 0.44 | 0.76 → 0.81 | 0.693 → 0.633 | 0.75 |
| 300 | 0.369 → 0.342 | 0.79 → 0.80 | 0.59 → 0.63 | 0.88 → 0.88 | 0.477 → 0.429 | 0.88 |
| 500 | 0.280 → 0.257 | 0.85 → 0.86 | 0.73 → 0.76 | 0.91 → 0.91 | 0.356 → 0.316 | 0.92 |

**Semi-synthetic extractor (a sensitivity analysis, not a result).** `--simulate-se` draws scores from the hidden
labels with a chosen sensitivity and PPV ≈ 0.8: hits get `q ~ U(0.55, 0.99)`, and 5% of non-hits get
`q ~ U(0.05, 0.4)`. The question is what a better extractor buys for the same audit (n = 150, 300 replicates):

| Extractor | raw relerr | PPI uniform relerr / cov | cov 3–19 | cov 20–49 | score design relerr / cov |
|---|---|---|---|---|---|
| stand-in (Se 0.19) | 0.426 | 0.554 / 0.68 | 0.41 | 0.76 | 0.499 / 0.71 |
| simulated Se 0.5 | 0.380 | 0.576 / 0.86 | 0.81 | 0.85 | 0.571 / 0.86 |
| simulated Se 0.8 | 0.355 | 0.467 / 0.88 | 0.81 | 0.91 | 0.445 / 0.89 |

### 9.2 Fairer retrieval baselines: score threshold, τ tuned on train

For each concept, a dense retriever (bge-small) or BM25 keeps every report in the slice with a score ≥ τ_ℓ.
τ_ℓ is tuned on the **train split**, per concept (the same supervision that the stand-in extractor gets).
Boolean queries use set algebra on the kept sets, so the threshold retriever *can* express `¬`, unlike top-k.
Two thresholds: `τ_F1` maximizes the F1 of the kept set on train (mean train F1 0.22 dense / 0.24 BM25,
eval F1 0.19 / 0.20); `τ_count` makes the kept count equal the true train count. Two readers: *count-all*
(the answer is the number of kept reports, which is realistic) and *oracle* (counts the true positives among the
kept reports, an upper bound for any reader).

| Method (379 queries) | Median rel. err | 3–19 | 20–49 | 50–149 | ≥150 | Slope sign acc. (39) | Interval? |
|---|---|---|---|---|---|---|---|
| Top-k oracle, dense @10 / @50 | 0.976 / 0.842 | 0.92 / 0.67 | 0.96 / 0.85 | 0.97 / 0.87 | 0.99 / 0.95 | 0.62 / 0.87 | no |
| Top-k oracle, BM25 @10 / @50 | 0.978 / 0.891 | 0.97 / 0.75 | 0.96 / 0.89 | 0.97 / 0.92 | 0.98 / 0.93 | 0.67 / 0.72 | no |
| Threshold dense τ_F1, count-all | 1.182 | 2.61 | 1.83 | 1.96 | 0.52 | 0.38 | no |
| Threshold dense τ_F1, oracle reader | 0.600 | 0.71 | 0.73 | 0.49 | 0.53 | 0.69 | no |
| **Threshold dense τ_count, count-all** | **0.432** | 0.71 | 0.46 | 0.31 | **0.09** | **0.41** | no |
| Threshold BM25 τ_F1, oracle reader | 0.588 | 0.67 | 0.57 | 0.41 | 0.59 | 0.82 | no |
| Threshold BM25 τ_count, count-all | 0.776 | 0.92 | 0.62 | 0.93 | 0.34 | 0.41 | no |
| Cube raw `Σπ` (stand-in) | 0.426 | 0.75 | 0.42 | 0.22 | 0.22 | 0.97 | not valid |
| Cube PPI, score design, one audit | 0.499 | 1.10 | 0.49 | 0.25 | 0.10 | 0.83 (one audit), 1.00 (mean) | yes, cov 0.71 (0.91–0.94 for ≥ 50) |

The threshold retriever is a much stronger count baseline than top-k. With a count-matched τ it ties the
uncorrected cube on the median (0.432 vs 0.426), and it is better in the largest cells (0.09 vs 0.22).
It has no interval, it gets the sign of the yearly trend wrong 59% of the time (0.41 sign accuracy, against 0.97
for raw `Σπ`), and its threshold is calibrated on the train prevalence. That calibration works only because train
and eval come from the same distribution here (it fails under drift, which the slope result shows). The oracle
reader is worse than count-all at τ_count, because the kept set has low recall (F1 ≈ 0.2).

### 9.3 Local LLM extractor (Qwen3-4B, zero-shot, no training labels)

`scripts/extract_llm.py --backend hf --model Qwen/Qwen3-4B --batch-size 4`, run from `research/.venv` (CUDA
torch). The machine had no llama.cpp build and no GGUF weights. Settings: RTX A2000 12 GB, bf16, greedy
decoding, thinking off, prompt v1 (hash `02c025187d9426d3`), the same prompt and JSON contract as the OpenAI
backend. 3,000 eval reports took 3.4 h (4.1 s per report). There were 5 unparseable replies (counted as no
facts) and 4,234 facts, and 85% of the evidence spans occur verbatim in the report. Manifest:
`data/extract/hf_Qwen-Qwen3-4B/manifest_eval.json`. The facts were run with `scripts/run_audit_eval.py --facts
... --tag qwen3_4b` (1,000 audits). This extractor was run on the eval split only, so the score designs use the
*proxy* `ê² = π(1 − π) + 0.005` (ALGEBRA 11.4).

**Extractor quality (threshold 0.5): mean Se 0.24, mean PPV 0.22.** This is honestly worse than the supervised
stand-in on PPV (0.55). Every leaf is flagged at least once (the stand-in never flags 13 leaves), but there are
many false positives. The best leaves are Fluid/Blood Leak (Se 0.88, PPV 0.64), Display Difficult to Read
(0.61 / 0.96) and Failure to Read Input Signal (0.56 / 0.51). Rare, vague leaves (Mechanical Problem, Failure to
Calibrate) have PPV ≤ 0.03. Its verbalized probabilities are coarse (mostly 0.7 to 0.9).

| Extractor | raw relerr (Σπ/truth) | PPI uniform: relerr / cov | best design: relerr / cov | cov 3–19 | cov 20–49 | cov ≥ 50 | slope cov / sign (1 audit) |
|---|---|---|---|---|---|---|---|
| Stand-in TF-IDF+LR (§8, §9.1) | 0.426 (0.58) | 0.554 / 0.68 | score 0.499 / 0.71 | 0.41–0.44 | 0.76–0.81 | 0.90–0.94 | 0.84–0.86 / 0.82–0.83 |
| Qwen3-4B zero-shot | 0.719 (1.04) | 0.726 / 0.79 | cell 0.716 / 0.79 | 0.62–0.63 | 0.84–0.85 | 0.92–0.95 | 0.90 / 0.73 |

PPI removes the bias for both extractors (the mean over audits is within 1–2% of the truth). With the LLM,
coverage is higher at every count band (0.62 vs 0.41 for counts < 20). The LLM's errors are spread over many
reports (false positives with π > 0), so the audit sees residuals and the variance estimate is less often zero.
But its residuals are larger, so the single-audit error is larger (0.73 vs 0.55). With the proxy design,
score/Poisson strata give **no** gain over uniform (design rel. SE 0.93 against 0.93). Even the oracle diagnostic
gains little (0.928). A design is only as good as its predicted residuals, and a poorly calibrated zero-shot
extractor predicts them badly.

### 9.4 What round 2 shows

> Follow-up work: rerun on v1 data [#9](https://github.com/ChenyangLi4288/cube_rag/issues/9), LLM extraction [#10](https://github.com/ChenyangLi4288/cube_rag/issues/10), rare-cell intervals [#11](https://github.com/ChenyangLi4288/cube_rag/issues/11).

1. **Score-stratified PPI works as the theory says, but the gain is modest.** It is exactly unbiased (L12, L13
   and the replicate means), and its intervals are as valid as uniform. With a train-calibrated design and the
   stand-in extractor, the exact design SE falls by 9% (variance −17%, about a 20% larger audit for free), the
   single-audit median error falls from 0.554 to 0.499, and coverage rises from 0.68 to 0.71. Cell strata give
   nothing, and the rarity weighting and the Poisson design are between the two. The oracle diagnostic shows
   about twice as much headroom (rel. SE 0.52). Better residual prediction (a calibrated extractor, and train-split
   LLM scores for the calibration) is where further design gains would come from.
2. **Rare-cell coverage is an extractor and audit-size problem, not a design problem** (ALGEBRA 11.5). For
   counts < 20, coverage goes from 0.41 to 0.59 to 0.73 for n = 150, 300, 500 (uniform). It reaches 0.81 with a
   simulated Se of 0.5 to 0.8 extractor, and 0.62 with the zero-shot 4B LLM. None of these reach 0.95 at n = 150.
3. **The score-threshold retriever is a much fairer baseline than top-k.** It ties raw `Σπ` on median count error
   (0.432 vs 0.426) when τ is count-calibrated on train. But it has no interval, and it gets the trend sign right
   only 41% of the time (cube 0.97 raw, 1.00 PPI mean). The paper must include it.
4. **A small zero-shot LLM is not a better extractor than a supervised bag-of-words model here** (PPV 0.22). The
   frontier-model run (`gpt-6.1-sol`, prepared but not run) is the next data point.
