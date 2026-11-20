# TASK 2: Standalone Rigorous & Self-Contained Educational Articles (Set 2)

## Objective
Take the $N$ articles generated in `output/set_1_faithful/` (Set 1) and generate $N$ new, mathematically rigorous, self-contained educational articles in `output/set_2_corrected/` (Set 2).

## Mandatory Rules for Set 2 (`output/set_2_corrected/`)

### 1. Strict 1-to-1 Cardinality & Naming Parity
- If Task 1 produced $N$ articles in `output/set_1_faithful/`, Task 2 **MUST** produce exactly $N$ corresponding articles in `output/set_2_corrected/` using the **exact same index $J$ and filename** (e.g., `output/set_1_faithful/01_linear_regression.md` maps directly to `output/set_2_corrected/01_linear_regression.md`).

### 2. Pure Standalone Educational Articles (NOT a Critique)
- Every article in Set 2 must be written as a standalone, authoritative masterclass/textbook chapter on Topic $J$.
- **NEVER** refer to Set 1, the user's notes, or previous mistakes inside Set 2 articles. Phrases like *"In the previous version..."*, *"To correct the misconception that..."*, or *"Note: we added..."* are strictly forbidden inside `output/set_2_corrected/`.

### 3. Rigorous Error Correction
Carefully audit every claim, assumption, equation, proof, and conclusion in Article $J$ of Set 1:
- **Fix Wrong Assumptions:** If an assumption was omitted, misstated, or mathematically invalid (e.g., missing independence, homoscedasticity, integrability, positive-definiteness, or regularity conditions), write the exact, correct mathematical conditions in Set 2.
- **Fix Flawed Logic & Derivations:** If a derivation skipped non-trivial steps, used invalid algebraic/calculus operations, or drew a false conclusion, replace it with a rock-solid, step-by-step mathematical derivation.
- **Fix Imprecise Notation:** Standardize and disambiguate notation (e.g., distinguishing random variables from realizations, estimators from true parameters, matrix dimensions, and inner spaces).

### 4. Zero-Prerequisite Completeness (Accessible to Any Student)
- Each article in Set 2 must be **100% self-contained** so that a student without specialized prior background can understand the entire article from start to finish.
- Whenever Article $J$ in Set 1 relies on undefined concepts, unstated prerequisite theorems, or abrupt logical jumps, **inject the necessary foundational definitions, intuitive explanations, geometric/probabilistic interpretations, intermediate proof steps, and concrete examples** directly into Article $J$ in Set 2.
- Retain all valid topics, scope, and correct insights from Article $J$ in Set 1 so nothing valid is lost—only corrected, deepened, and completed.
