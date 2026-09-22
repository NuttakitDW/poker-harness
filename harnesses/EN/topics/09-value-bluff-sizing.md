# Value betting, bluffing and sizing

- Stable ID: `09-value-bluff-sizing`
- Scope: Heads-up toy formula for pure river bluff; real hands include calls, raises, rake and blockers.
- Thai counterpart: [เดิมพันเพื่อมูลค่า การบลัฟ และขนาดเดิมพัน](../../TH/topics/09-value-bluff-sizing.md)

## Core idea

A value bet wants calls from enough worse hands to outperform checking. A pure bluff has no showdown value and wants folds; for risk B into pot P, its break-even fold frequency is B/(P+B) if folds win P and calls lose B. Bet size changes what opponents call and therefore changes both value and bluff candidates. A half-pot bluff needs more than one-third folds to profit before rake. Do not call every weak hand a bluff: a weak pair with showdown value may do better by checking.

## Which hands want to bet?

- Start from the opponent’s **continuing range**, not the hand you hope they have. List worse hands that call and better hands that fold.
- For value, estimate whether betting beats checking after accounting for raises. Thin value can be good against a caller who overcalls and bad against a player who folds almost everything worse.
- For a pure bluff, use B/(P+B) as the fold threshold only when there is zero showdown equity and losing a call costs exactly B. With a draw, include its equity when called; with a weak pair, include its check EV.
- On the river, choose bluffs with relevant blockers and poor showdown value, then check whether the opponent has enough foldable combos.

## Worked example (authored; not quoted from source)

Authored example: Bluff $75 into $100. Break-even folds = 75/175 ≈ 42.9%; at 50% folds, EV = .5×100 − .5×75 = +$12.50.

## Practice and boundary checks

Sizing creates a tradeoff. A larger value bet wins more per call but may receive fewer calls; a smaller bet can be called by a wider set of marginal hands. The optimal size therefore depends on response frequency, not merely hand strength. A bluff bet risks the full B when caught; choosing a larger size can make stronger hands fold but demands a higher fold frequency for a zero-equity bluff. When estimating response, remove blocker-incompatible hands and include possible raises. In multiway pots, the chance that at least one player can continue often increases, so the simple heads-up threshold is insufficient.

## Common errors

Confusing bluff break-even frequency with calling equity; value betting only the nuts.

## Source pages

[Play Optimal Poker, PDF p. 59](../sources/play-optimal-poker/pages-0057-0064.md#pdf-page-59) · [The Theory of Poker — David Sklansky, PDF p. 115](../sources/the-theory-of-poker/pages-0113-0120.md#pdf-page-115) · [Cash Game Killer, PDF p. 27](../sources/cash-game-killer/pages-0025-0032.md#pdf-page-27)

## Related

[Equity, pot odds and EV](./04-equity-pot-odds-ev.md) · [Turn and river planning](./08-turn-river-planning.md) · [Equilibrium, mixing and exploitation](./11-gto-mixing-and-exploit.md) · [Topic index](../INDEX.md)