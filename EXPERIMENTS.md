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
- No 𝔼₂ (point estimates only)
- No correction
- No reconciliation
- Reconciliation with equalities only (no inequalities)
- No exposure
- Independence against copula for Boolean predicates
- Grammar-limited parsing against free-form parsing

## 7. Compute (estimate)

- Extraction: about 1.5 million reports, one pass with an 8B model. One pass with a 70B model on about 10%.
- Graph-RAG baselines: if the full corpus costs too much, build the index on a stratified subsample of
  50,000 reports or less for each dataset. Document the method.
- Experiments use cached extractions and labels. Runs with a new seed do not need a GPU.
