# TASK 3: Master Comparative Discrepancy & Pedagogical Audit Report

## Objective
Compare the $N$ faithful articles in `output/set_1_faithful/` (Set 1) against the $N$ corrected articles in `output/set_2_corrected/` (Set 2) and produce a single, exhaustive Markdown report at `output/AUDIT_REPORT.md`.

## Required Structure for `output/AUDIT_REPORT.md`

### 1. Executive Summary Table
Provide a summary table listing all $J = 1 \dots N$ articles with columns:
- `Article Index (J) & Topic`
- `Set 1 File` (`output/set_1_faithful/J_...md`)
- `Set 2 File` (`output/set_2_corrected/J_...md`)
- `Errors / Flawed Assumptions Fixed` (Count)
- `Missing Prerequisites / Expansions Added` (Count)

### 2. Detailed Article-by-Article Audit ($J = 1 \dots N$)
For every article $J \in \{1, \dots, N\}$, create a dedicated section `# Article J: <Topic Name>` containing two structured subsections:

#### A. Mistakes, Flawed Assumptions & Logical Errors Corrected
List every mathematical, statistical, or logical flaw present in Article $J$ of Set 1 and show how it was fixed in Article $J$ of Set 2. (If Article $J$ in Set 1 had zero errors, explicitly write: *"No mathematical, logical, or conceptual errors were present in Set 1."*):
- **Error #[k]: [Short Descriptive Title]**
  - **Where in Set 1 (`output/set_1_faithful/J_...md`):** Exact section heading and paragraph/equation reference.
  - **What Was Written in Set 1:** Exact quote or LaTeX equation from Set 1.
  - **Why It Was Wrong:** Detailed explanation of the flawed assumption, invalid proof step, missing regularity condition, or incorrect conclusion.
  - **Where & How It Was Corrected in Set 2 (`output/set_2_corrected/J_...md`):** Exact section heading in Set 2 and the corrected mathematical statement or proof step.

#### B. Missing Information & Zero-Prerequisite Expansions Added
List every foundational definition, theorem, intuition, or intermediate derivation that did not exist in Article $J$ of Set 1 and was added to Article $J$ of Set 2 to make the article complete and accessible to any student:
- **Addition #[m]: [Name of Concept, Definition, Theorem, or Derivation Added]**
  - **Where the Gap Occurred in Set 1 (`output/set_1_faithful/J_...md`):** Which section or transition in Set 1 assumed prior knowledge or skipped steps.
  - **Why It Was Necessary:** Why a student without prior background needed this information to understand the topic completely.
  - **Where It Was Added in Set 2 (`output/set_2_corrected/J_...md`):** Exact section heading in Set 2 and a concise summary of the newly added material.