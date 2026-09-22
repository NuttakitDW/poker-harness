# Stack depth and pot geometry

- Stable ID: `03-stack-depth-and-spr`
- Scope: No-limit hold’em; use effective stack, the smaller stack available between two players.
- Thai counterpart: [ความลึกสแตกและรูปทรงพอต](../../TH/topics/03-stack-depth-and-spr.md)

## Core idea

Measure stack in big blinds and compare remaining effective chips with the current pot: SPR = effective stack / pot at the start of a street. A low SPR makes commitment with strong one-pair hands more plausible; a high SPR increases the cost of dominated draws and non-nut made hands. Stack depth also changes preflop implied odds and whether a three-bet leaves room to maneuver. Count the amount already invested as sunk when choosing the next action.

## Stack decisions

- **Preflop:** use the shorter of the two stacks for heads-up exposure. If you have 200 BB and the caller 35 BB, only 35 BB per player can enter their shared pot; your extra chips do not create implied odds against that caller.
- **Postflop:** compute SPR after preflop action, then map possible bet sizes across the remaining streets. At SPR 1, a pot-sized bet already covers the effective stack. At SPR 8, a single pot bet leaves substantial money for later decisions.
- **Commitment:** compare the EV of folding, calling and raising from the current point. “I have already put in 40 BB” describes history, not a reason to continue with a losing call.
- **Multiway:** each opponent has a separate effective stack and side pots can produce different incentives.

## Worked example (authored; not quoted from source)

Authored example: In a $20 pot with $80 effective behind, SPR is 4. A $20 turn bet would leave $60 behind; plan how river calls or bets work before making it.

## Practice and boundary checks

Stack depth is a relationship, not a permanent player label. A player with 100 BB against a 20 BB shover is effectively 20 BB deep in that confrontation, while remaining 100 BB deep against another 100 BB player. In tournaments, stack in blinds can shrink without losing a chip because blinds rise. Recompute the effective stack after every pot and before speculative calls. A low SPR does not make every top pair automatic all-in: opponent range, board, number of players and tournament payout pressure still matter. Use SPR to plan bet geometry, then use range EV to decide whether commitment is profitable.

## Common errors

Using your own full stack when opponent is shorter; calling solely because you already invested chips.

## Source pages

[The Grinder's Manual, PDF p. 53](../sources/grinders-manual/pages-0049-0056.md#pdf-page-53) · [The Grinder's Manual, PDF p. 1035](../sources/grinders-manual/pages-1033-1040.md#pdf-page-1035)

## Related

[Equity, pot odds and EV](./04-equity-pot-odds-ev.md) · [Preflop decision sequence](./06-preflop-decisions.md) · [Tournament stacks, ICM and push/fold](./13-tournaments-icm-pushfold.md) · [Topic index](../INDEX.md)