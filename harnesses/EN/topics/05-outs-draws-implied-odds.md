# Outs and implied odds

- Stable ID: `05-outs-draws-implied-odds`
- Scope: Hold’em draws; clean outs require a specified opponent range.
- Thai counterpart: [เอาต์และออดส์จากเงินในอนาคต](../../TH/topics/05-outs-draws-implied-odds.md)

## Core idea

An out is a future card that changes a losing hand into a winner against the relevant range. Count unseen cards, then discount outs that complete a stronger opposing hand or cause redraws. On the flop, a clean nine-out flush draw has 9/47 probability to improve on the turn and 1−(38/47)(37/46) over two cards, about 35%. The latter is useful only if both cards can be seen at the stated cost. Implied odds add realistic future winnings when a draw hits; reverse implied odds subtract future losses when a made draw is second best.

## Test whether an out is clean

1. State the hand you need to beat. A card making a flush is not a winning out against an opponent’s higher flush on the same card.
2. Subtract your own and board cards from the deck, then count genuinely unseen improving cards. On the flop there are 47 unseen cards for a known two-card hand and three-card board.
3. Decide whether you pay to see one card or two. A turn call with a possible river bet must not use the full two-card probability as though the river were free.
4. For implied odds, estimate how often the opponent pays after you improve and how much effective stack remains. Reverse implied odds are especially severe for low flushes and weak straights.

Authored check: An open-ended straight draw usually starts with eight rank-completing cards, but a four-flush board may make some of them losers; count clean outs against the range, not “eight” by habit.

## Worked example (authored; not quoted from source)

Authored example: A low flush draw facing a range with higher flush draws cannot safely count all nine suit cards as winning outs.

## Practice and boundary checks

Approximation rules such as “four times outs on the flop” and “twice outs on the turn” are fast but imperfect. The exact one-card probability is clean outs divided by unseen cards; the exact two-card probability uses the complement of missing twice. In Omaha, a player knows more private cards and must use exactly two at showdown, so transplanting a Hold’em nine-out estimate can be wrong. Even in Hold’em, some outs can be counterfeited by a paired board or a higher flush. An implied-odds call should identify a realistic payer, not merely enough chips behind.

## Common errors

Using two-card odds to call one street with no guaranteed free river; assuming all future winnings are collectible.

## Source pages

[Poker Math Preflop Workbook, PDF p. 129](../sources/poker-math-preflop-workbook/pages-0129-0136.md#pdf-page-129) · [Poker Math Preflop Workbook, PDF p. 110](../sources/poker-math-preflop-workbook/pages-0105-0112.md#pdf-page-110) · [Crushing the Microstakes, PDF p. 220](../sources/crushing-the-microstakes/pages-0217-0224.md#pdf-page-220)

## Related

[Equity, pot odds and EV](./04-equity-pot-odds-ev.md) · [Flop texture and continuation bets](./07-flop-texture-and-cbet.md) · [Four-card pot-limit Omaha](./15-omaha-pot-limit.md) · [Topic index](../INDEX.md)