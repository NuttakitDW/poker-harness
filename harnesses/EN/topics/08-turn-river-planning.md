# Turn and river planning

- Stable ID: `08-turn-river-planning`
- Scope: No-limit hold’em; interpret new cards against both evolving ranges.
- Thai counterpart: [การวางแผน turn และ river](../../TH/topics/08-turn-river-planning.md)

## Core idea

After each action, remove or downweight hands that would rarely take that line. The turn often changes draw density and remaining stack geometry; before betting, specify which rivers permit value, bluff or check. On the river, no future card can rescue a weak showdown hand, so compare a call against the opponent’s value and bluff combos and a bet against the calling range. A river check may preserve showdown value. Large polar bets represent very strong hands and bluffs; modest bets may target thinner calls, depending on ranges.

## Plan by runout, not by street in isolation

- **Turn card:** ask whether it strengthens the caller, the aggressor or both. A draw-completing card changes who has nut advantage; a blank can preserve prior range shape.
- **Turn sizing:** calculate the river stack left after likely calls. Betting $75 into $100 with $225 behind leaves $150 and creates a $250 pot after a call, so a river shove is 60% pot.
- **River decision:** with no future card, a bluff catcher’s call needs enough opponent bluffs relative to value given its price. A value bet needs worse hands to call at sufficient frequency.
- **Evidence:** if an opponent checks twice, do not automatically set their strong-hand probability to zero; some ranges trap or protect checking.

## Worked example (authored; not quoted from source)

Authored example: If a turn bet leaves a half-pot river shove, list the cards on which you intend to shove before placing the turn bet.

## Practice and boundary checks

A turn barrel needs a reason that survives a call. For value, identify worse hands and draws that continue; for a bluff, identify better hands that fold now or on predictable rivers. If neither set exists, checking can retain equity and avoid an expensive river. On the river, consider whether the opponent’s missed draws would actually bluff; missed draws alone do not prove a bluffing frequency. Compare the chosen line with alternatives by asking how each part of your own range is played, since always betting strong hands and checking weak ones makes future decisions easier for opponents.

## Common errors

Using the flop range unchanged on the river; bluffing missed draws into an opponent who never folds made hands.

## Source pages

[The Grinder's Manual, PDF p. 1189](../sources/grinders-manual/pages-1185-1192.md#pdf-page-1189) · [The Grinder's Manual, PDF p. 1365](../sources/grinders-manual/pages-1361-1368.md#pdf-page-1365) · [The Theory of Poker — David Sklansky, PDF p. 126](../sources/the-theory-of-poker/pages-0121-0128.md#pdf-page-126)

## Related

[Flop texture and continuation bets](./07-flop-texture-and-cbet.md) · [Value betting, bluffing and sizing](./09-value-bluff-sizing.md) · [Check-raise, protection and slowplay](./10-checkraise-and-slowplay.md) · [Topic index](../INDEX.md)