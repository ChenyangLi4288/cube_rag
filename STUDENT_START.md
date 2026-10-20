# Start here (student handoff)

This document tells you what to do first. Read it before the other files.

## 1. Read in this order

1. [README.md](README.md): the problem and the idea (10 minutes).
2. [PROPOSAL.md](PROPOSAL.md): research questions, timeline and scope cuts.
3. [ALGEBRA.md](ALGEBRA.md): the formal method. Sections 2–5 are the most important.
4. [EXPERIMENTS.md](EXPERIMENTS.md): the benchmark and the experiment list.
5. [RELATED_WORK.md](RELATED_WORK.md): read the papers marked **must read** in Section 5 below.

## 2. Rules

- **Use public data only.** Use MAUDE, VAERS and ASRS. Do not use hospital or patient data.
- **Do not show hidden fields to the method.** Hidden fields are the ground truth. Keep them in a separate table.
- **Record each data download.** Write the source URL, date, file names and row counts in a manifest file.
- **Freeze data before experiments.** After the freeze, do not change the data. If you must change it, make a new version.
- **Version all prompts.** Give each prompt an ID and a version number. Do not edit a prompt after you use it in a run.
- **Fix random seeds.** Record the seed for each run.
- **Verify each citation.** Before you cite a paper, open its arXiv page and check the ID, title and venue.

## 3. Compute

- Use your GPU instance for development and for runs with small models (about 8B parameters).
- Large runs (70B models, frontier models, full-corpus extraction with large models) go through Chenyang.
  To ask for a run, send a JSON job file. The file gives: job ID, model, prompt ID and version, decoding settings,
  and report IDs. Chenyang sends back a Parquet label file and a run log.
- Experiments must read cached labels. Do not call an LLM again when you repeat an experiment with a new seed.

## 4. First two weeks (Oct 20 – Nov 2, 2026)

Do these tasks in this order. Each task has a "done when" condition.

| # | Task | Done when |
|---|---|---|
| 1 | Clone the GitHub repository `ChenyangLi4288/cube_rag`. Do not commit data files (see `.gitignore`). | You can push a branch. |
| 2 | Download MAUDE (more product codes than FRN), VAERS (2019, 2021–2023) and ASRS (2018–2023). VAERS and ASRS need a manual download through their websites. | Raw files and a manifest for each dataset exist. |
| 3 | For each dataset, write a table of fields: text fields, filter fields, hidden fields. | Table is in `data/README.md`. |
| 4 | Build the concept hierarchy for each dataset: FDA problem codes for MAUDE, the ASRS anomaly taxonomy, and MedDRA for VAERS. Check the MedDRA licence first. If we cannot use it, use clusters of VAERS symptom terms. | Each hierarchy is a file of (child, parent) pairs. |
| 5 | Get the exposure data: CDC vaccine doses and FAA/BTS flight operations, by month. | One CSV per dataset with columns `period, value, source`. |
| 6 | Write exact statements of Propositions 1–5 in ALGEBRA.md. Define the ⊗ (multiply) rule for the 𝔼₂ component. | Chenyang reviews and agrees. |
| 7 | Make a toy cube by hand: 20 reports, 5 concepts, 4 time bins. Calculate counts, a roll-up and a slope on paper. | The toy example is in `ALGEBRA.md`. Later, you use it as the first unit test. |

## 5. Papers to read first (must read)

- GraphRAG (2404.16130) and HyperGraphRAG (2503.21322): the methods that we compare against.
- TG-RAG (2510.13590): the nearest temporal method.
- UQE (2407.09522) and LOTUS (2407.11418): query engines for unstructured text.
- PPI (2301.09633) and PPI++ (2311.01453): the statistics for our correction step.
- Green, Karvounarakis and Tannen, "Provenance Semirings", PODS 2007: the algebra.
- Li and Eisner, "First- and Second-Order Expectation Semirings", EMNLP 2009: the 𝔼₂ component.
- Wickramasuriya, Athanasopoulos and Hyndman, MinT reconciliation, JASA 2019: the reconciliation step.

## 6. Meetings and reports

- Meet with Chenyang one time each week. Bring a short written update: done, blocked, next.
- Tell Chenyang immediately if a task in the critical path (PROPOSAL.md, Section 5) is more than one week late.
- Decisions that need Chenyang: changes to scope, dataset, or baselines; any new data source; GPU job requests.

## 7. Open decisions (default answers)

Use these default answers. If you find a problem with a default, tell Chenyang.

1. **VAERS lattice: use MedDRA.** The VAERS `SYMPTOMS` field already uses MedDRA Preferred Terms.
   - In week 1, ask MSSO for an academic (non-commercial) MedDRA licence.
   - Do not put MedDRA hierarchy files in the public benchmark. Release the VAERS terms (public data) and a script
     that builds the hierarchy from the user's own MedDRA copy.
   - If we do not have a licence by Nov 2, use clusters of symptom terms. Do not wait longer.
2. **MAUDE: add insulin pumps, continuous glucose monitors and implantable cardiac defibrillators to FRN.**
   - These devices have many reports, and the defibrillators have more death and injury reports.
   - Their recalls and safety notices have known dates. We use these dates as real change-points.
   - Find the product codes. Check the report counts with openFDA count queries before you download.
3. **MAUDE exposure: do not divide by external exposure data.** There is no good public denominator.
   - Use MAUDE for counts, raw trends and change-points.
   - For a second measure, divide by all reports for the same product code (proportional reporting).
   - Use exposure data only for VAERS (doses) and ASRS (flight operations).
4. **Boolean predicates: use independence, then correct the combined cell with the audit set.**
   - A copula needs a correlation for each pair of concepts. The audit set is too small to estimate them.
   - Use a Gaussian copula only as an ablation.
   - Also calculate the Fréchet–Hoeffding bounds as a check.
