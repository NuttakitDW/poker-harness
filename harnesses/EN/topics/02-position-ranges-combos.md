# Position, ranges and combinations

- Stable ID: `02-position-ranges-combos`
- Scope: Hold’em; no universal opening chart.
- Thai counterpart: [ตำแหน่ง เรนจ์ และจำนวนคอมโบ](../../TH/topics/02-position-ranges-combos.md)

## Core idea

Position is the order of action: acting last after the flop reveals more information before committing chips. Start from a range of plausible hands, not a single guessed holding. There are 1,326 unordered two-card deals: 6 pair combos per rank, 4 suited and 12 offsuit combos per distinct-rank holding before blockers. A visible ace reduces AA from six to three combos. Stack depth, prior action, blind structure, opponent tendencies and rake change which parts of a range can profitably enter. Use weighted frequencies when a hand is played only sometimes.

## Apply ranges instead of hand guesses

1. Write the opening range by seat, then narrow it after a call, raise or fold. A button open generally starts from a different candidate set than an early-position open because fewer opponents remain and postflop position is better.
2. Count unblocked combinations, not labels. For a pair: 4 choose 2 = 6; for AK: 4×4 = 16, split into four suited and twelve offsuit.
3. Weight partial actions. If a player three-bets A5s only half the time, its four pre-blocker combos contribute an effective two to the three-bet range.
4. Recount after board cards appear and avoid treating a software range chart as a fact about the actual opponent.

Authored check: If A♠ and K♠ are visible, AK has 3×3 = 9 possible combos; three are suited (hearts, diamonds, clubs) and six offsuit.

## Worked example (authored; not quoted from source)

Authored example: A♠ on the board leaves three possible AA pairs, and A♠K♠ is impossible. Remove blocked hands before counting a river value-to-bluff ratio.

## Practice and boundary checks

Range construction should include frequency and context. If a player opens 30% of hands on the button, it does not mean every specific hand is opened 30% of the time; some hands may be always opened and borderline ones mixed. After a tight player calls a large three-bet, weigh hands that plausibly call such a size more heavily than hands they usually four-bet or fold. On later streets, blockers matter in both directions: holding a card from the opponent’s likely value hands reduces those combos, while holding a card from their likely bluffs makes a hero call less attractive. State which range segment a blocker affects before using it.

## Common errors

Treating 16 AK combos as one hand; keeping preflop ranges fixed after new cards and actions.

## Source pages

[Poker Math Preflop Workbook, PDF p. 52](../sources/poker-math-preflop-workbook/pages-0049-0056.md#pdf-page-52) · [The Grinder's Manual, PDF p. 43](../sources/grinders-manual/pages-0041-0048.md#pdf-page-43)

## Related

[Preflop decision sequence](./06-preflop-decisions.md) · [Flop texture and continuation bets](./07-flop-texture-and-cbet.md) · [Equilibrium, mixing and exploitation](./11-gto-mixing-and-exploit.md) · [Topic index](../INDEX.md)