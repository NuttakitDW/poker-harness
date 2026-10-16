# Near-Exact Computation of ICM Placement Probabilities (DE-ICM) — Wataru Inariba, 2026

Source: [Near-Exact Computation of ICM Placement Probabilities (DE-ICM) — Wataru Inariba, 2026](../../EN/sources/de-icm-inariba-2026/index.md) · 26 physical PDF pages · [original PDF](../../../sources/pdf/arxiv/2610.06028v1-de-icm.pdf)

## Reading route

Use the topic map below for the major sections, then open the linked physical PDF page and its page-faithful Markdown. PDF page numbers include covers and front matter; printed page numbers in the book may differ. The extracted text can omit diagrams, suits, tables, and page layout. Check the [source-quality notes](../sources/source-quality.md) for extraction limits.

## Original chapter route

9 paper sections mapped to their physical PDF pages; 5 study themes explained below.

- [Abstract and introduction](../../../sources/pdf/arxiv/2610.06028v1-de-icm.pdf#page=1)
- [Background and the integral representation](../../../sources/pdf/arxiv/2610.06028v1-de-icm.pdf#page=3)
- [Quadrature on a fixed double-exponential grid](../../../sources/pdf/arxiv/2610.06028v1-de-icm.pdf#page=4)
- [Stable leave-one-out deconvolution](../../../sources/pdf/arxiv/2610.06028v1-de-icm.pdf#page=8)
- [Numerical results](../../../sources/pdf/arxiv/2610.06028v1-de-icm.pdf#page=11)
- [Related work](../../../sources/pdf/arxiv/2610.06028v1-de-icm.pdf#page=14)
- [Discussion and conclusion](../../../sources/pdf/arxiv/2610.06028v1-de-icm.pdf#page=15)
- [Proofs](../../../sources/pdf/arxiv/2610.06028v1-de-icm.pdf#page=18)
- [Numerical settings and validation suite](../../../sources/pdf/arxiv/2610.06028v1-de-icm.pdf#page=24)

## Explained study themes

### ICM as a stack-weighted finishing order

ICM draws the winner with probability proportional to stack, then the next place among the rest, and so on (Equation 1); the paper notes this is the Plackett-Luce model. Placement probabilities form an n by n matrix, and every prize structure's equity is a linear sum over it.

Evidence: [PDF p. 3](../../../sources/pdf/arxiv/2610.06028v1-de-icm.pdf#page=3) · [extracted page](../../EN/sources/de-icm-inariba-2026/pages-0001-0008.md#pdf-page-3)

### Exponential clocks and the integral formula

Give each player an exponential clock with rate equal to stack; sorting the clocks reproduces the ICM order (Lemma 2.1). Fixing one player's clock, the number of opponents ahead is Poisson-binomial, so each placement probability is one integral over time (Theorem 2.2).

Evidence: [PDF p. 3](../../../sources/pdf/arxiv/2610.06028v1-de-icm.pdf#page=3) · [extracted page](../../EN/sources/de-icm-inariba-2026/pages-0001-0008.md#pdf-page-3)

### One fixed double-exponential grid

Stacks are scaled so the largest is 1/20 and the substitution t = exp(x - e^-x) puts every integrand on one trapezoidal grid. Truncation errors have closed-form bounds and the step follows from field size, about 1/16 at 100 players and 1/64 at 4,000 (Table 2 and Section C).

Evidence: [PDF p. 5](../../../sources/pdf/arxiv/2610.06028v1-de-icm.pdf#page=5) · [extracted page](../../EN/sources/de-icm-inariba-2026/pages-0001-0008.md#pdf-page-5) · [PDF p. 7](../../../sources/pdf/arxiv/2610.06028v1-de-icm.pdf#page=7) · [extracted page](../../EN/sources/de-icm-inariba-2026/pages-0001-0008.md#pdf-page-7) · [PDF p. 24](../../../sources/pdf/arxiv/2610.06028v1-de-icm.pdf#page=24) · [extracted page](../../EN/sources/de-icm-inariba-2026/pages-0017-0024.md#pdf-page-24)

### Stable leave-one-out division

One product of all players' factors is formed per node, then each player's own factor is divided out. The division runs forward when that player's q is at least 1/2 and backward otherwise (Theorem 4.1), with each step clamped to [0, C_r]; Table 4 shows single-direction division overflowing.

Evidence: [PDF p. 9](../../../sources/pdf/arxiv/2610.06028v1-de-icm.pdf#page=9) · [extracted page](../../EN/sources/de-icm-inariba-2026/pages-0009-0016.md#pdf-page-9)

### Accuracy and speed

On 1,511 exactly solvable instances up to 4,000 players, the worst equity error is 4.0e-14 relative and the worst placement error 1.1e-14 absolute. The full matrix takes 0.2 s for 1,000 players on one core and 7.58 s for 4,000 (Table 5). Small probabilities are accurate only in absolute terms.

Evidence: [PDF p. 11](../../../sources/pdf/arxiv/2610.06028v1-de-icm.pdf#page=11) · [extracted page](../../EN/sources/de-icm-inariba-2026/pages-0009-0016.md#pdf-page-11) · [PDF p. 13](../../../sources/pdf/arxiv/2610.06028v1-de-icm.pdf#page=13) · [extracted page](../../EN/sources/de-icm-inariba-2026/pages-0009-0016.md#pdf-page-13)

## Scope and verification

This is a source-specific study map and paraphrase, not a reproduction of the book or a solver-approved strategy. Work numerical examples, hand charts, quizzes, and figures against the linked original pages. Promotional/front-matter text and historical claims are not treated as current poker rules or proven results.

Assumed use: computing ICM equities and finishing-place probabilities for large fields (the paper tests up to 4,000 players with stack ratios up to 10^9). It is a numerical method for the ICM itself, not a claim that ICM predicts real finishes, and it gives no strategy advice. The author works at GTO Wizard; an earlier version runs in its solver, but the paper's code is not released.
