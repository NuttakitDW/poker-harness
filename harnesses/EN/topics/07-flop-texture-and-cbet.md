# Flop texture and continuation bets

- Stable ID: `07-flop-texture-and-cbet`
- Scope: Hold’em single-raised pots; multiway pots require tighter assumptions.
- Thai counterpart: [ลักษณะ flop และ continuation bet](../../TH/topics/07-flop-texture-and-cbet.md)

## Core idea

Read a flop by high-card distribution, connectedness, suits and available draws. Ask which preflop range has more strong made hands and which has more near-nut hands. A continuation bet is a postflop bet by the previous aggressor, but initiative alone does not justify betting. Decide whether the bet seeks calls from worse, folds from better, or protection against meaningful equity. Check some strong hands and playable draws when checking has value. In multiway pots, each opponent adds possible strong hands and reduces automatic bluff success.

## Build a flop plan

1. Mark the strongest possible hands and major draws on the actual board. Compare which preflop range contains them more often.
2. Split your candidate hands into clear value, draws that benefit from folds, showdown hands that may check, and air.
3. Choose a size that serves the range objective. A small bet may pressure broad weak ranges; a larger bet may target calls from strong draws or polarize a range, but there is no universal mapping.
4. After a call, record which hands survive into turn. After a raise, reassess rather than continuing with every automatic c-bet.

Authored comparison: On A♣7♦2♠, an early-position raiser can credibly hold many strong aces. On 9♠8♠7♦, a blind caller can hold many two-pair, straight and draw combinations. The bettor’s plan should reflect that shift.

## Worked example (authored; not quoted from source)

Authored example: A♣7♦2♠ is dry; 9♠8♠7♦ is connected and draw-heavy. The same preflop raiser need not use one bet frequency or size on both.

## Practice and boundary checks

The phrase “range advantage” describes how often a range is ahead overall; “nut advantage” describes concentration of the very strongest hands. They can differ. On a low connected board, a preflop raiser may still have many overpairs while a blind defender has more straights and two pair. Sizing choices should reflect both. A small bet into several opponents has to get through multiple ranges, so a heads-up c-bet plan often overbluffs multiway. Before firing again on the turn, mark what the flop call removed from the opponent’s range and which draws were added by the new card.

## Common errors

Auto-cbetting every flop; treating a multiway spot as heads-up.

## Source pages

[The Grinder's Manual, PDF p. 846](../sources/grinders-manual/pages-0841-0848.md#pdf-page-846) · [Crushing the Microstakes, PDF p. 132](../sources/crushing-the-microstakes/pages-0129-0136.md#pdf-page-132)

## Related

[Preflop decision sequence](./06-preflop-decisions.md) · [Turn and river planning](./08-turn-river-planning.md) · [Value betting, bluffing and sizing](./09-value-bluff-sizing.md) · [Topic index](../INDEX.md)