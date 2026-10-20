# CubeRAG: Semiring-Annotated Fact Cubes for Counting and Trend Question Answering

Draft research proposal, 2026-10-20. Target: ICML 2027.

## 1. Motivation

Structured RAG methods use graphs (GraphRAG, LightRAG, HippoRAG2), hypergraphs (HyperGraphRAG, Hyper-RAG),
trees (RAPTOR) or temporal graphs (T-GRAG, TG-RAG, Zep). These methods help with multi-hop questions and
summary questions. But they do not answer two types of question well:

1. **Count questions** ("How many X in Y?"). These include counts, counts by group, ratios, and
   Boolean combinations ("X but not Z").
2. **Trend questions** ("What is the trend of X from A to B?"). These include series over many periods, slopes,
   change-points, and rates per unit of exposure.

These question types are frequent in safety monitoring and incident reports.

We found four causes of failure. RELATED_WORK.md gives the evidence.

| Cause | Where it occurs | Result |
|---|---|---|
| **C1 Recall limit.** Retrieval ranks the results and keeps only the top few (top-k, PageRank, path pruning). | All graph and vector RAG | Counts are too low. The error has no bound. |
| **C2 Arithmetic in free text.** The LLM adds numbers from summaries. | GraphRAG, RAPTOR, ArchRAG | Double counts, incorrect totals, no error bar |
| **C3 Time is only a filter.** The method uses time to select facts "as of" a date. | T-GRAG, TG-RAG, STAR-RAG, Zep | No slopes, no change-points, no rates |
| **C4 No uncertainty.** The method does not carry extraction errors into the answer. | LOTUS, Palimpzest, DocETL, KAG, TableRAG | Answers look certain but are incorrect. Errors increase with roll-up. |

Database theory already has the necessary tools: provenance semirings (K-relations), aggregation semimodules,
expectation semirings, OLAP cubes, prefix-sum indexes, and hierarchical reconciliation. But no RAG index
uses them together. Some query engines (UQE, ABae) give guarantees for one aggregate query. But they sample
again for each new query. SemReuse (2026) uses certified filters again, but it does not do counts or trends.

## 2. Method: the Annotated Fact Cube

### 2.1 Build the index (one time)

1. **Extract** facts from each report: `(concept ℓ, time t, attributes a, source span s)`.
   The concepts come from a public taxonomy. We make the taxonomy into a lattice (a partial order with joins).
   We use the FDA device-problem codes for MAUDE, MedDRA for VAERS, and the ASRS anomaly taxonomy for ASRS.
2. **Annotate** each fact with a value from the product semiring `K = 𝔹ᴿ × 𝔼₂ × ℕ[S]`:
   - `𝔹ᴿ`: a bitmap of report IDs. With this bitmap, we count each report only one time.
   - `𝔼₂`: a second-order expectation semiring value. It keeps the sums that we need for a mean and a variance.
   - `ℕ[S]`: a provenance polynomial of source spans. We use it for citations and audits.
3. **Build** the cube `𝒞[ℓ, τ, a]`. Each cell combines the annotations of its facts.
   - Roll-up on the concept axis uses the union of bitmaps (zeta transform).
   - Roll-up on the time axis uses prefix sums (Fenwick tree).

### 2.2 Answer a query

4. **Parse.** The LLM translates the question into an expression in a small grammar `Q`.
   The operators are: σ (slice), ρ (roll-up), γ (aggregate), Δ (difference), ∇ (slope), κ (change-point),
   ÷E (divide by exposure). The grammar limits the LLM output. The LLM does not do arithmetic.
5. **Calculate.** The cube calculates `Q`. Each answer is a linear function of cell values, or a smooth
   function of them (delta method). Thus, each answer has a confidence interval.
6. **Correct.** A small audit set gives the error rates of the extractor for each concept. We correct the cells
   with these rates (Rogan–Gladen or prediction-powered correction).
7. **Reconcile.** We project the corrected cells onto the set of consistent values. In this set, a child count is
   not more than its parent count, and the parts of a partition add up to the total. This step comes from
   hierarchical forecasting (MinT). No RAG method uses it yet.
8. **Generate.** The LLM writes the answer. It gives the numbers and the confidence interval from the cube.
   It also cites example reports from the provenance links.
9. **New concepts.** If a question uses a concept that is not in the lattice, we add a new node.
   A cheap proxy model selects candidate reports, and the LLM labels them. Later queries use the new node again.

### 2.3 How this is different from "table + text-to-SQL"

1. The bitmaps make Boolean and roll-up results exact when one report has many labels.
2. Each cell keeps its uncertainty. The uncertainty goes through all operations.
3. The lattice gives consistency constraints. We use these constraints to correct errors.
4. Time-series operators and exposure data are part of the algebra.

## 3. Research questions and hypotheses

- **RQ1 Count accuracy.** H1: CubeRAG decreases the median relative error on count questions by 5 times or more,
  compared with the best graph-RAG baseline, at a similar index cost.
- **RQ2 Trends.** H2: the slope sign is correct for 95% or more of trend questions. Change-point F1 is much higher
  than TG-RAG and long-context baselines. For ASRS, division by flight operations changes at least one
  conclusion (because flights decreased during COVID).
- **RQ3 Calibration.** H3: with correction and reconciliation, 95% confidence intervals contain the true value
  92–97% of the time. Without these steps, coverage is much lower for rare concepts.
- **RQ4 Cost over many queries.** H4: for 300 questions, CubeRAG uses 10 times fewer LLM calls than UQE or LOTUS,
  at equal accuracy, because it uses the same index again.
- **RQ5 Robustness.** H5: reconciliation decreases the accuracy gap between an 8B and a 70B extractor by 50% or more.

## 4. Contributions

1. A formal data structure (the Annotated Fact Cube) and a query algebra for RAG. We prove:
   correct distinct counts, valid confidence intervals after correction, no increase in MSE after reconciliation,
   and bounds on query time.
2. A pipeline to build the index, with new concept nodes on demand.
3. **CubeQA**, a public benchmark of count and trend questions over 10⁵–10⁶ documents, with exact ground truth
   and cost data. No current benchmark has these properties.
4. A comparison with 12 baselines: vector, graph, hypergraph, temporal-graph, table-hybrid and query-engine methods.

## 5. Timeline: ICML 2027

Deadline: Jan 16–22, 2027 (AoE). Confirm the date on icml.cc. Internal freeze: Jan 11, 2027.

**How we present the paper.** ICML reviewers expect a contribution to ML or statistics, not a systems paper.
Thus, the main claim is *valid statistical inference for count and trend queries over LLM-extracted facts*.
The parts of this claim are: the annotation semiring, the correction in the cube, reconciliation as a projection
that decreases variance, and confidence intervals for slopes when the extractor error changes with time.
The data structure is how we do the inference. CubeQA is the evidence.
Working title: *"Algebraic Fact Cubes: Valid Inference for Counting and Trend Questions in Retrieval-Augmented
Generation."*

**Critical path.** Two tracks run at the same time.

| Weeks | Dates | Theory and writing | Data and systems | Done when |
|---|---|---|---|---|
| 1–2 | Oct 20 – Nov 2 | Write exact statements of Props 1–5. Define the ⊗ rule for 𝔼₂. | Get MAUDE, VAERS, ASRS. Build the lattices. Get exposure data (CDC doses, FAA/BTS flights). | Data, lattices and manifests are frozen. |
| 3–5 | Nov 3 – Nov 23 | Prove Props 1 and 3. Develop trend intervals for errors that change with time. | Extract facts: 8B model on all data, 70B model on about 10%. Build the cube. Make CubeQA and check a sample by hand. | Cube exists for all 3 datasets. CubeQA v1 is frozen. |
| 6–8 | Nov 24 – Dec 14 | Prove Prop 2 (validity) and Prop 5 (cost). | Add correction and reconciliation. Run core baselines: vanilla RAG, long-context, GraphRAG, LightRAG, HippoRAG2, HyperGraphRAG, TG-RAG, LOTUS, UQE, extract-then-SQL. | Main results table (X1, X2, X3) is complete. |
| 9–10 | Dec 15 – Dec 28 | Write the method and theory sections. | Run ablations, X4 (cost), X5 (robustness), X6 (exposure). | All figures are complete. |
| 11–12 | Dec 29 – Jan 11 | Write the full paper and the proof appendix. Do an internal review. | Make the code anonymous. Prepare the reproducibility package. | Freeze. |
| 13 | Jan 12 – Jan 16 | Register the abstract. Do the final edits. | Keep time for runs that we must do again. | Submit. |

**Scope cuts if we are late.** Do the cuts in this order:

1. Move X7 (new concepts) to the appendix.
2. Remove the KAG, TAG, TableRAG and StructRAG baselines.
3. Move Theil–Sen slopes and change-point intervals to future work.
4. Use ASRS only for the exposure case study.

**Do not cut:** count and slope results on all three datasets, interval coverage with correction and
reconciliation, and Props 1–3.

**After ICML:** send CubeQA to NeurIPS 2027 Datasets & Benchmarks (May 2027) as a separate paper.
Send a systems version to VLDB (monthly deadline).

**Compute:** one extraction pass over 10⁵–10⁶ reports with an 8B model, and one pass with a 70B model on a subset.
Graph-RAG baselines need much compute to build their index. If necessary, use a stratified subsample and report it.

## 6. Risks

| Risk | What we do |
|---|---|
| Low extraction recall limits cube accuracy. | Correct with the audit set. Add new concept nodes. Report recall for each concept. |
| The taxonomy does not match the words in the questions. | Link concepts with embeddings. Add new nodes. Measure parser accuracy separately. |
| Reconciliation changes rare-concept counts too much. | Use variance weights in the projection. Test without it (ablation). |
| The agency-coded fields have errors. | Label a small subset by hand. Report agreement. Call the fields a "reference", not "truth". |
| Baselines cost too much on large data. | Use a subsample. Document the method. |

## 7. Venues

Primary: **ICML 2027** (method and theory). Next: NeurIPS 2027 Datasets & Benchmarks (CubeQA),
VLDB or SIGMOD (systems version), EMNLP 2027 through ACL Rolling Review (fallback).
