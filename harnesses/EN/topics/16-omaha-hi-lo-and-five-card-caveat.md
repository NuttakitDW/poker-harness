# Omaha eight-or-better and five-card caveat

- Stable ID: `16-omaha-hi-lo-and-five-card-caveat`
- Scope: Omaha eight-or-better uses exactly two hole cards for each high/low hand; five-card Omaha is a distinct variant and must be checked at the table.
- Thai counterpart: [Omaha แบ่งสูงต่ำ และข้อควรระวังเกมห้าใบ](../../TH/topics/16-omaha-hi-lo-and-five-card-caveat.md)

## Core idea

In Omaha eight-or-better, the low half exists only when a qualifying five-card low (eight or lower, five distinct ranks) is possible. An ace can be low; straights and flushes do not disqualify the low hand. High and low may use different two-card pairs from the same four-card holding. “Scooping” both halves is much stronger than winning only one; sharing a low half can lead to being quartered. The supplied PLO chapter explicitly teaches four hole cards and the exactly-two rule. Phrases such as “five-card hand” describe the final hand, not a five-hole-card Omaha ruleset; verify any five-hole-card variant separately.

## Separate high and low evaluations

First ask whether the board contains at least three distinct ranks eight or below; without them no one can qualify for low. Then select exactly two hole cards and three board cards for a five-rank low, with no duplicate low ranks. Evaluate the high side independently; it may use a different hole-card pair. If two players tie for low and a third wins high, each low player receives a quarter of the whole pot before odd-chip rules.

Authored split: In a $120 pot, one player wins high while two others tie low. High receives $60; each tied low receives $30. Rake and house splitting rules can change the final chips. A bare A-2 can be shared often; look for scoop potential and protection against being quartered.

## Worked example (authored; not quoted from source)

Authored example: A-2-9-K on board 3-4-8-Q-Q can use A-2 plus 3-4-8 for an eight-low; high is evaluated separately with exactly two hole cards.

## Practice and boundary checks

Low evaluation is lexicographic from the highest card downward: 8-6-4-2-A beats 8-7-3-2-A because six is lower than seven at the first differing rank. A board with only two low ranks cannot produce a qualifying low in Omaha even if a player holds many low cards, because exactly three board cards are compulsory. A high-only hand can still win the whole pot when no low qualifies, but it competes for only the high half when one does. The same A-2 low may be shared by several players; seek high equity or a stronger low redraw rather than assuming half-pot ownership.

## Common errors

Assuming every board has a low; valuing a shared nut low as though it wins half the whole pot.

## Source pages

[Doyle Brunson's Super System 2, PDF p. 166](../sources/super-system-2/pages-0161-0168.md#pdf-page-166) · [Doyle Brunson's Super System 2, PDF p. 177](../sources/super-system-2/pages-0177-0184.md#pdf-page-177) · [Pot-Limit Omaha — Jeff Hwang, PDF p. 39](../sources/pot-limit-omaha-jeff-hwang/pages-0033-0040.md#pdf-page-39)

## Related

[Rules, showdown and hand ranks](./01-rules-and-rankings.md) · [Four-card pot-limit Omaha](./15-omaha-pot-limit.md) · [Limit hold’em and stud family](./17-limit-holdem-and-stud.md) · [Topic index](../INDEX.md)