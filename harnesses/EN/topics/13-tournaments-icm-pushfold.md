# Tournament stacks, ICM and push/fold

- Stable ID: `13-tournaments-icm-pushfold`
- Scope: Tournament rules and payout structure must be specified; chip EV and prize EV differ.
- Thai counterpart: [สแตกทัวร์นาเมนต์ ICM และ shove/fold](../../TH/topics/13-tournaments-icm-pushfold.md)

## Core idea

Tournament blinds and antes rise; lost chips may be irreplaceable. Express stack in big blinds and note players behind, payout jumps and risk of elimination. ICM maps stacks and payouts to estimated prize equity under an explicit model, so a positive chip-EV call may be poor near a bubble or major pay jump. At short stacks, open-shove, reshove and fold can replace small opens and calls, but correct thresholds depend on position, antes, ranges, stack distribution and payouts. Check whether a source’s chart is for chip EV or ICM before applying it.

## Payout-aware short-stack process

1. Convert every relevant stack to big blinds and record antes, positions, players behind, remaining field and exact payouts.
2. Decide whether the question is about **chip EV** or **prize EV**. In winner-take-all, the two align more closely; under multiple prizes, survival and pay jumps matter.
3. Compare shove, smaller raise, call and fold using plausible response ranges. A shove can win the pot uncontested but risks elimination; a small raise can create a committed stack.
4. Recalculate when another player is shorter or a pay jump is imminent; the same hand can change value without its cards changing.

Authored ICM toy: Three players have equal stacks and prizes $60/$30/$0. Symmetry gives each player $30 prize equity before the hand: (60+30+0)/3. A fair all-in against one opponent has zero chip EV, but if you lose you get $0 and if you win you are not guaranteed $60 because the third player remains. Under simple ICM, a win leaves stacks 2:0:1. The winner’s prize equity is (2/3)×$60 + (1/3)×$30 = $50; a loss pays $0. Thus a 50% all-in has prize EV  $25, below the $30 before the hand, despite zero chip EV. This ignores blind changes and future skill edges.

## Worked example (authored; not quoted from source)

Authored example: With equal chips at the final table, risking elimination to win a small pot may have a different prize EV from the same risk in a winner-take-all event.

## Practice and boundary checks

An ICM result is model-dependent. It assigns finishing probabilities from stack shares and payouts; it does not know that one player is much stronger, that blind positions differ, or that future table selection changes. Even so, it captures a critical point: when prizes are non-linear, chips won and chips lost need not have equal money value. Short-stack pressure also depends on who covers whom. A 12 BB shove into a 50 BB leader threatens the short stack’s tournament life; a 50 BB player calling that shove risks only 12 BB against that player. Recompute ranges for each role and check whether a chart includes antes.

## Common errors

Using cash-game call thresholds near payout jumps; following a shove chart without its ante and payout assumptions.

## Source pages

[DN Workbook 9036, PDF p. 65](../sources/dn-workbook-9036/pages-0065-0072.md#pdf-page-65) · [Gripsed MTT Strategy Guide, PDF p. 24](../sources/gripsed-mtt-strategy-guide/pages-0017-0024.md#pdf-page-24) · [DN Workbook 9036, PDF p. 68](../sources/dn-workbook-9036/pages-0065-0072.md#pdf-page-68)

## Related

[Stack depth and pot geometry](./03-stack-depth-and-spr.md) · [Equity, pot odds and EV](./04-equity-pot-odds-ev.md) · [Mental game, performance and bankroll](./19-mental-game-and-bankroll.md) · [Topic index](../INDEX.md)