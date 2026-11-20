# Synthetic Foundations: Sets and Equivalence Relations

## 1. Basic Set Operations

A set $A$ is a well-defined collection of distinct elements. Given two sets $A$ and $B$ inside an ambient universe $\mathcal{U}$, we write $x \in A$ when $x$ is an element of $A$, and we say that $A$ is a subset of $B$, written $A \subseteq B$, whenever every $x \in A$ also satisfies $x \in B$. Two sets are equal precisely when $A \subseteq B$ and $B \subseteq A$. The union $A \cup B$ collects all elements belonging to at least one of $A$ or $B$, while the intersection $A \cap B$ collects elements common to both. The Cartesian product $A \times B$ consists of all ordered pairs $(a, b)$ with $a \in A$ and $b \in B$.

For any indexed family $\{A_i\}_{i \in I}$ of subsets of $\mathcal{U}$, De Morgan's laws express complements of unions and intersections through dual operations:

$$
\begin{aligned}
\mathcal{U} \setminus \bigcup_{i \in I} A_i &= \bigcap_{i \in I} (\mathcal{U} \setminus A_i), \\[10pt]
\mathcal{U} \setminus \bigcap_{i \in I} A_i &= \bigcup_{i \in I} (\mathcal{U} \setminus A_i).
\end{aligned}
$$

These identities hold for arbitrary index sets $I$, whether finite or infinite, and reduce reasoning about complements of compound sets to membership tests on individual elements.

## 2. Equivalence Relations

A binary relation $R$ on a set $A$ is any subset $R \subseteq A \times A$, where we write $a \sim b$ in place of $(a, b) \in R$. Equivalence relations formalize notions of structural sameness across mathematical objects and enable quotient constructions.

> **Definition 1.1 — Equivalence Relation.** A binary relation $\sim$ on a set $A$ is an *equivalence relation* if it is reflexive ($a \sim a$ for all $a \in A$), symmetric ($a \sim b$ implies $b \sim a$), and transitive ($a \sim b$ and $b \sim c$ imply $a \sim c$).

Given $a \in A$, the equivalence class of $a$ is $[a] = \{x \in A : x \sim a\}$. Notice that two classes are either disjoint or identical, which establishes a canonical correspondence with partitions of $A$.

> **Theorem 1.2 — Partition Correspondence.** Let $\sim$ be an equivalence relation on a nonempty set $A$. The collection of distinct equivalence classes $\mathcal{P} = \{[a] : a \in A\}$ forms a partition of $A$ into nonempty, pairwise disjoint subsets whose union equals $A$.

**Proof.** Every class $[a]$ is nonempty because reflexivity guarantees $a \in [a]$, and therefore $\bigcup_{a \in A} [a] = A$. To show pairwise disjointness, suppose $[a] \cap [b] \neq \emptyset$ and choose $z \in [a] \cap [b]$. Then $a \sim z$ and $b \sim z$. By symmetry, $z \sim b$, and by transitivity, $a \sim b$. For any $x \in [a]$, we have $x \sim a$ and hence $x \sim b$, yielding $[a] \subseteq [b]$; symmetry gives the reverse inclusion $[b] \subseteq [a]$, so $[a] = [b]$. $\square$
