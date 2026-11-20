# Synthetic Foundations: Sets and Equivalence Relations

## 1. Basic Set Operations

A set $A$ is a collection of elements. We write $x \in A$ if $x$ belongs to $A$, and $A \subseteq B$ when every element of $A$ belongs to $B$. Union $A \cup B$, intersection $A \cap B$, and Cartesian product $A \times B$ combine sets in standard ways.

De Morgan's laws state that for an indexed family $\{A_i\}_{i \in I}$ inside a universe $\mathcal{U}$, complements swap unions and intersections:

$$
\begin{aligned}
\mathcal{U} \setminus \bigcup_{i \in I} A_i &= \bigcap_{i \in I} (\mathcal{U} \setminus A_i), \\[10pt]
\mathcal{U} \setminus \bigcap_{i \in I} A_i &= \bigcup_{i \in I} (\mathcal{U} \setminus A_i).
\end{aligned}
$$

## 2. Equivalence Relations

A relation $\sim$ on $A$ is an equivalence relation if it is reflexive, symmetric, and transitive. For any $a \in A$, its equivalence class is $[a] = \{x \in A : x \sim a\}$. Equivalence classes form a partition of $A$ because overlapping classes coincide.
