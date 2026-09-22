# Limit hold’em and stud family

- Stable ID: `17-limit-holdem-and-stud`
- Scope: Fixed-limit betting; stud variants use exposed upcards rather than community boards.
- Thai counterpart: [Limit Hold’em และตระกูล Stud](../../TH/topics/17-limit-holdem-and-stud.md)

## Core idea

In fixed-limit hold’em, bet and raise increments are prescribed, so drawing and value decisions often involve a different price structure from no-limit. Seven-card stud distributes private and exposed cards across streets; track dead cards visible in opponents’ upcards and the changing order of action. Stud eight-or-better splits high and qualifying low, and a low-looking draw can be quartered or fail to qualify. Razz is low-only seven-card stud, commonly ace-to-five low. Each game’s bring-in, betting cap and qualifier should be verified before play.

## Why this is not one game

In fixed-limit hold’em, a call or raise has a prescribed increment; pot odds can become favorable for draws, but calling a dominated draw can still lose future bets. In stud high, each player’s upcards expose part of their hand; track dead outs and remember action order can depend on exposed strength. Stud eight-or-better requires a qualifying low, so evaluate scooping and quartering, not only the chance of making any low. Razz uses low-only ranking and many high upcards can indicate a weak low draw, but exposed dead low cards also matter.

Authored check: If a stud player needs one of four sevens and two sevens are visible in opponents’ upcards, at most two remain unseen; treating it as four outs doubles the apparent draw strength.

## Worked example (authored; not quoted from source)

Authored example: In stud, if two opponents show the same rank you need to complete a pair, fewer such cards remain unseen than in a board-only estimate.

## Practice and boundary checks

The stud family demands memory of exposed cards. In hold’em, all players share the board; in stud, every opponent’s upcards remove distinct cards from the unseen deck and provide partial range evidence. This affects both draw probability and likely made hands. In split-pot stud, high and low goals can conflict; a draw that makes a respectable high may still fail to win any low half. In fixed-limit play, capped bet increments alter the value of implied odds: even when a draw completes, the amount collectable per street is bounded by the structure. Keep variant and betting cap attached to every strategy note.

## Common errors

Applying no-limit sizing logic to fixed-limit; forgetting exposed dead cards or low qualifiers.

## Source pages

[Doyle Brunson's Super System 1, PDF p. 28](../sources/super-system-1/pages-0025-0032.md#pdf-page-28) · [Doyle Brunson's Super System 2, PDF p. 224](../sources/super-system-2/pages-0217-0224.md#pdf-page-224) · [Doyle Brunson's Super System 2, PDF p. 251](../sources/super-system-2/pages-0249-0256.md#pdf-page-251)

## Related

[Rules, showdown and hand ranks](./01-rules-and-rankings.md) · [Omaha eight-or-better and five-card caveat](./16-omaha-hi-lo-and-five-card-caveat.md) · [Draw, lowball and triple draw](./18-draw-lowball-triple-draw.md) · [Topic index](../INDEX.md)