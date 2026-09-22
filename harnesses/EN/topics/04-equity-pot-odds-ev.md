# Equity, pot odds and EV

- Stable ID: `04-equity-pot-odds-ev`
- Scope: Heads-up toy calculations with no rake, future betting, ties or side pots unless stated.
- Thai counterpart: [อิควิตี พอตออดส์ และมูลค่าคาดหวัง](../../TH/topics/04-equity-pot-odds-ev.md)

## Core idea

Equity is the share of the pot a hand or range expects at showdown. EV compares net outcomes, not the frequency of winning alone. If the pot before an opponent bets is P and their bet is B, calling B needs equity B/(P+2B) when action closes and realization is complete. With future streets, realized equity may differ from raw showdown equity. Estimate opponent range, remove blocked combos, calculate equity, then adjust for future betting, fold equity and costs.

## Separate three calculations

**Call price:** facing B into P, you call B to contest P+2B. The break-even raw equity is B/(P+2B) only if your share is fully realized and no later cost exists. **Bet EV:** when betting for value or bluffing, include fold, call and raise branches separately. **Range equity:** weight each opponent combo by its frequency; do not average hand classes equally when they contain different combo counts.

Authored calculation: With P=$60 and B=$30, calling needs 30/(60+60)=25%. If your hand has 30% realized equity, EV of calling is .30×$90 − .70×$30 = +$6. If a future river decision costs more, that +$6 is only the immediate model result.

## Worked example (authored; not quoted from source)

Authored example: P=$100, B=$50. Calling $50 competes for the $200 pot after your call, requiring 25% equity. At exactly 25%, EV = .25×$150 − .75×$50 = $0.

## Practice and boundary checks

Keep the pot accounting consistent. In the calling formula, P is the pot *before* the opponent’s current bet; if a hand history displays the pot after that bet, subtract B to recover P or derive the ratio directly from final pot size. Equity can be estimated against a hand or against a range, but the latter is normally more realistic. Ties contribute fractional pot share, not a full win or loss. Rake raises the required edge in cash games. For a decision with multiple future branches, construct an EV tree rather than forcing every situation into a single pot-odds fraction.

## Common errors

Using B/(P+B) as the calling threshold; counting gross winnings without subtracting the call.

## Source pages

[Poker Math Preflop Workbook, PDF p. 95](../sources/poker-math-preflop-workbook/pages-0089-0096.md#pdf-page-95) · [The Theory of Poker — David Sklansky, PDF p. 17](../sources/the-theory-of-poker/pages-0017-0024.md#pdf-page-17)

## Related

[Outs and implied odds](./05-outs-draws-implied-odds.md) · [Value betting, bluffing and sizing](./09-value-bluff-sizing.md) · [Equilibrium, mixing and exploitation](./11-gto-mixing-and-exploit.md) · [Topic index](../INDEX.md)