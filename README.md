# CubeRAG: an algebraic fact cube for counting and trend questions

Status: proposal, 2026-10-20. Target: ICML 2027 (deadline Jan 16–22, 2027, AoE).
New to the project? Read [STUDENT_START.md](STUDENT_START.md) first.

## The problem

Users often ask two types of question about a large set of reports:

- **Count:** "How many infusion-pump reports in 2025 describe an occlusion alarm with patient injury?"
- **Trend:** "How did runway-incursion reports per 100,000 flights change from 2018 to 2023?"

Current structured RAG methods (GraphRAG, HyperGraphRAG, tree RAG, temporal-graph RAG) do not answer these
questions well. They retrieve only the top few results. Then the LLM adds numbers in free text.
This gives counts that are too low, totals that are not correct, and no error bars.

To answer a count or a trend, a method must:

1. look at all the reports, not only the top results;
2. do the arithmetic exactly;
3. give an uncertainty for each answer;
4. use time as an axis for measurement, not only as a filter.

## The idea

We replace the retrieval graph with an **Annotated Fact Cube**:

1. An LLM extracts facts from each report one time, when we build the index.
2. We put each fact in a grid with three axes: concept × time × attributes.
3. Each cell keeps three values: the set of report IDs, the sums needed for a variance, and links to source text.
4. The LLM translates each question into a short formal expression. The cube calculates the answer.
   The LLM does not do arithmetic.
5. A small audit set (reports with known labels) corrects extraction errors in the cube.
6. A last step makes the counts agree with the concept hierarchy. For example, a child concept cannot have a
   larger count than its parent.

## Data

We use public data only: FDA MAUDE, VAERS and NASA ASRS. Each dataset has fields that the agency codes.
We hide these fields from the method. We use them only as the correct answers (ground truth).

## Files

| File | Contents |
|---|---|
| [STUDENT_START.md](STUDENT_START.md) | First tasks, rules, handoff steps, schedule for the first two weeks |
| [PROPOSAL.md](PROPOSAL.md) | Motivation, research questions, method, contributions, timeline, risks |
| [ALGEBRA.md](ALGEBRA.md) | Formal definitions, operators, propositions to prove, examples |
| [RELATED_WORK.md](RELATED_WORK.md) | Literature table (2024–2026) and how CubeRAG is different |
| [EXPERIMENTS.md](EXPERIMENTS.md) | Benchmark, baselines, metrics, ablations, compute |

This project is separate from `mcic_rag_test`. That project studies sampling estimators for one query at a time.
This project studies a data structure that we build one time and use again for many queries.
