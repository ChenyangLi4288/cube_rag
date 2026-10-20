# Related work (compiled 2026-10-20)

We checked the arXiv IDs on arXiv during the literature search. Some searches had rate limits.
`[k]` means a well-known older paper. We did not check it again. A venue with `?` is not confirmed.
**Before you cite a paper, open its arXiv page and check the ID, title and venue.**

## A. Structured RAG (graph, hypergraph, tree)

| System | arXiv | Structure | (a) Problem with counts | (b) Problem with trends |
|---|---|---|---|---|
| GraphRAG (Edge et al.) | 2404.16130 | Knowledge graph and community summaries. Map-reduce answers. | Counts are lost in text summaries. Map-reduce combines text, not numbers. | No time axis |
| LightRAG | 2410.05779 | Knowledge graph and vectors, two levels of keys | Top-k limits recall. | Updates replace old facts. No history. |
| HippoRAG / HippoRAG2 | 2405.14831 / 2502.14802 | Open knowledge graph and passages. Personalized PageRank. | Ranks results. Does not list all results. | No time |
| RAPTOR | 2401.18059 | Tree of recursive summaries | Summaries make counts unclear. | Clusters by topic, not time |
| KAG | 2409.13731 | Knowledge graph with a schema, linked to chunks. Logical forms. | Nearest to a solution (a count step in logical forms). But it needs complete extraction and has no uncertainty. | No time axis |
| StructRAG | 2410.08815 | Makes a structure (table, graph) for each query | Tables for each query lose data and cost much. | None |
| PathRAG | 2502.14902 | Relation paths, flow pruning | Paths are not good for set queries. | None |
| MiniRAG | 2501.06713 | Graph for small LMs | Not studied | None |
| NodeRAG | 2504.11544 | Graph with many node types, including attributes | No aggregate operator | None |
| ArchRAG | 2502.09891 | Hierarchy of communities with attributes | Summaries lose data. | None |
| HyperGraphRAG | 2503.21322 | Hyperedges with many entities | Keeps n-ary facts but does not aggregate them. | None |
| Hyper-RAG | 2504.08758 | Hypergraph (medical) | Not studied | None |
| Order-aware hypergraph RAG | 2604.12185 | Hyperedges with an order | Not studied | Order only, no numeric time |

## B. Temporal RAG

| System | arXiv | Problem with trends |
|---|---|---|
| T-GRAG | 2508.01680 | Time-dynamic graph. Solves conflicts between versions. Gives facts at one time only. |
| TG-RAG (with ECT-QA) | 2510.13590 | Two-level temporal graph. Gives text summaries for each period, not numeric series. |
| STAR-RAG | 2510.16715 | Summaries aligned with time. Gives facts at one time only. |
| Zep / Graphiti | 2501.13956 | Time intervals for agent memory. Not for analysis. |
| Entity-event KG | 2506.05939 | Narrative and causal order, not numeric trends |
| KG-IRAG | 2503.14234 | Retrieves one time window after another. Partial solution. |
| TimeRAG | 2412.16643 | Retrieval for time-series forecasts, not for questions about documents |

## C. Table/SQL hybrids and semantic query engines

| System | arXiv | Relation to CubeRAG |
|---|---|---|
| TAG | 2408.14717 | Exact SQL, but only on tables that exist. Standard methods are correct for 20% of questions or less. |
| TableRAG (HeteQA) | 2506.10380 | Does not make tables from text facts. |
| SUQL | 2311.09818 | SQL with free-text functions. No uncertainty. |
| LOTUS (semantic operators) | 2407.11418 | sem_agg makes a summary. No confidence interval for counts. |
| Palimpzest / Abacus | 2405.14696 / 2505.14661 | Optimises cost and quality. No confidence intervals for aggregates. |
| UQE | 2407.09522 | Unbiased aggregates by sampling for each query. No index to use again. |
| DocETL | 2410.12189 | Rewrites pipelines. No statistical guarantees. |
| ZenDB | 2405.04674 | Semantic tree for documents that use templates |
| Aryn / Sycamore / Luna | 2409.00847 | Translates questions into scripts. Better than RAG on NTSB reports. |
| EVAPORATE | 2304.09433 | The LLM writes extraction functions. Gives low-cost tables for the full corpus. Useful to build our index. |
| SemReuse | 2610.16035 | Uses certified filters again as views. Does not do counts or trends. |
| SemBench / SemCEB | 2511.01716 / 2606.23081 | Benchmarks. SemCEB shows that cardinality estimation is not solved. |
| Larch / Stretto / Sema / PLOP | 2606.07923 / 2602.04430 / 2603.11622 / 2604.09944 | Recent optimisers for semantic operators |
| HYVE | 2604.05400 | Hybrid views for LLM context over machine data |

## D. Approximate query processing and inference

- ABae 2108.06313 (VLDB 2021): stratified sampling with a proxy score. Gives confidence intervals.
- BlazeIt 1805.01046: control variates.
- PPI 2301.09633 (Science 2023), PPI++ 2311.01453, Cross-PPI 2309.16598: valid inference with model predictions.
- BARGAIN 2509.02896: model cascades with precision and recall guarantees.
- AQP with proxy models for AI workflows: 2607.00254.

CubeRAG uses these ideas one time, to correct the cube. It does not sample again for each query.

## E. Algebraic foundations

- Provenance semirings (K-relations): Green, Karvounarakis, Tannen, PODS 2007 [k].
- Aggregation with semimodules: Amsterdamer, Deutch, Tannen, PODS 2011 [k].
- Expectation semirings: Eisner 2002; Li and Eisner, EMNLP 2009 [k].
- Factorized databases: Olteanu and Schleich, 2016 [k].
- Text cube: Lin et al., EDBT 2008 [k].
- Hierarchical forecast reconciliation (MinT): Wickramasuriya, Athanasopoulos, Hyndman, JASA 2019 [k].
- Tensor models for knowledge graphs: RESCAL, TuckER [k].
- PAGR 2609.06127: semiring provenance with sheaf and quiver structure for certified retrieval.
  It is the only RAG paper that we found with semirings. It certifies grounding, not aggregates.

## F. Benchmarks that show the gap

GraphRAG-Bench ("When to use graphs in RAG") 2506.05690; GraphRAG-Bench (Xiao et al.) 2506.02404;
RAG vs. GraphRAG 2502.11371; In-depth analysis of graph-based RAG 2503.04338; HoloBench 2410.11996;
WildGraphBench 2602.02053; "Do We Still Need GraphRAG?" 2604.09666; CRAG 2406.04744; Loong 2406.17419;
Oolong 2511.02817; Counting-Stars 2403.11802; long-context counting with CoT 2609.38958; MultiHop-RAG 2401.15391;
FRAMES 2409.12941; NoLiMa 2502.05167; BABILong 2406.10149; TimeQA 2108.06314; TRAM 2310.00835;
UnSeenTimeQA 2407.03525.

No benchmark tests counts and trends together over 10⁵–10⁶ documents, with exact ground truth and cost data.

## Comparison

| Capability | Graph/hypergraph RAG | Temporal RAG | Semantic query engines | Table hybrids | **CubeRAG** |
|---|---|---|---|---|---|
| Looks at all reports | ✗ | ✗ | ✓ | ✓ (if tables exist) | ✓ |
| Exact distinct counts when one report has many labels | ✗ | ✗ | partial | ✗ | ✓ (bitmap) |
| Uncertainty kept through roll-up | ✗ | ✗ | for each query | ✗ | ✓ (𝔼₂ and correction) |
| Answers agree with the hierarchy | ✗ | ✗ | ✗ | ✗ | ✓ (reconciliation) |
| Slopes, change-points, rates | ✗ | ✗ | ✗ | with SQL | ✓ (operators) |
| Uses the index again for new queries | ✓ | ✓ | filters only (SemReuse) | ✓ | ✓ |
| Cites source text | ✓ | ✓ | partial | ✗ | ✓ (provenance) |
