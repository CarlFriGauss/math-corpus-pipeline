# TASK 1: Topic Classification & Faithful, Lossless Pedagogical Compilation (Set 1)

## Objective
Extract all theoretical content from the source directories defined in `GEMINI.md`, classify every piece of information into specific topics, and compile one concise, logically structured educational Markdown article per topic in `output/set_1_faithful/`.

## Step 1: Automated Extraction & Topic Classification
1. Write and run a Python extraction script in `scripts/` (using `nbformat`/`json` for `.ipynb`, regex/text parsing for `.Rmd`/`.qmd`/`.md`, and `pypdf`/`pymupdf` for verified personal `.pdf` files) so that no file or mathematical block is missed or truncated.
2. Analyze all extracted theoretical blocks and categorize them into specific, cohesive academic topics (e.g., *Linear Regression*, *Fourier Transform*, *Expectation-Maximization Algorithm*, *Variational Autoencoders*, *Brownian Motion*, *Markov Chains*, *Singular Value Decomposition*, *Metric Spaces & Compactness*, etc.).
3. Record the complete mapping of `[Topic J] <- [List of Source Files & Sections]` in `output/00_ingestion_manifest.md`. Let the total number of distinct topics be $N$.

## Step 2: Compiling Set 1 Articles (`output/set_1_faithful/`)
For each topic $J \in \{1, \dots, N\}$, generate a single Markdown file named `output/set_1_faithful/J_<topic_slug>.md` (e.g., `01_linear_regression.md`, `02_fourier_transform.md`) adhering to these four mandatory laws:

### Law 1: 100% Lossless Information Preservation (NOT a Summary)
- You must include **100% of the unique information, definitions, theorems, proof steps, mathematical derivations, assumptions, intuitions, and examples** present across all source files mapped to Topic $J$.
- Do **NOT** summarize, abstract away, or omit details. Every distinct mathematical statement or explanation written in the source notes must survive into the final article.

### Law 2: Conciseness via Strict Deduplication
- Because the same topic may be discussed across multiple `.md`, `.ipynb`, `.Rmd`, `.qmd`, and `.pdf` files, identical definitions, formulas, or explanations will appear multiple times in the raw sources.
- Eliminate all redundancy: merge repeated statements into a single, clean formulation while preserving every unique nuance, edge case, or alternative perspective found across the files.

### Law 3: Logical Educational & Teaching Structure
- Do **not** simply concatenate fragments file-by-file.
- Organize the compiled material into a cohesive, pedagogical progression designed to teach the subject clearly from start to finish (e.g., *Motivation & Intuition -> Setup & Definitions -> Core Mathematical Formulation -> Derivations & Proofs -> Properties & Special Cases*).
- You may write smooth transitional phrases and section headers to connect the user's points into a unified article, and standardize LaTeX formatting (`$...$` and `$$...$$`).

### Law 4: ZERO Critique, ZERO Fact-Checking, ZERO External Additions
- **CRITICAL CONSTRAINT:** In Task 1, you are a faithful compiler and pedagogical organizer—**NOT** a reviewer or fact-checker.
- Even if a source file contains a mathematically false statement, a flawed assumption, an invalid proof step, an incomplete derivation, or a wrong conclusion, **you MUST preserve and present the user's exact claim faithfully as written**.
- Do **NOT** correct errors, do **NOT** add warnings or footnotes pointing out mistakes, and do **NOT** inject external theorems, missing prerequisites, or textbook facts that were not present in the user's source files.
