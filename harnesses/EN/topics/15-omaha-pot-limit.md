# Four-card pot-limit Omaha

- Stable ID: `15-omaha-pot-limit`
- Scope: Standard high PLO with four hole cards; exactly two hole and three board cards form a hand.
- Thai counterpart: [Pot-limit Omaha ไพ่ 4 ใบ](../../TH/topics/15-omaha-pot-limit.md)

## Core idea

The two-plus-three rule changes board reading completely. Four hole cards create many draws, so nut potential, redraws, position and multiway equity matter more than apparent current hand strength. Double-suited connected hands often have more ways to make robust hands than isolated high cards, but exact value is situation-dependent. A bare low flush or small straight draw may be dominated. Pot-limit caps a raise according to the pot-limit calculation used by the room; verify local betting rules. Do not transfer hold’em odds or hand-rank logic without enforcing two hole cards.

## PLO mechanics and pot arithmetic

A four-card starting hand has six possible two-card pairs, but at showdown exactly one of those pairs combines with exactly three board cards. The strongest draw is often a **nut** draw plus a redraw, such as a nut straight draw with a flush redraw. A small “wrap” can be dominated by a larger wrap; count only outs that make the best or a sufficiently strong hand against the relevant range.

Authored pot-limit calculation: Before action, the pot is $100 and you face a $50 bet. To raise the maximum, first call $50, making the pot $200; you may then raise by $200 more, so the total amount you put in now is $250 (call $50 + raise $200), assuming no prior contribution on this street and standard pot-limit rules. Verify the room’s handling of previous contributions and minimum raises.

If you hold A♠K♠Q♦J♦ on T♠9♠2♣, spades can make a high flush, while several rank combinations can make straights. A later board pair can make an opponent’s full house; “many outs” is not equivalent to guaranteed nut equity.

## Worked example (authored; not quoted from source)

Authored example: Holding A♠K♦Q♥J♣ on a board of 9♠8♠7♠6♠5♠ does not give a flush: there is only one spade in the hand.

## Practice and boundary checks

PLO hand strength changes quickly because each player starts with more possible two-card pairs. A flopped straight without redraws can be fragile against a made straight plus higher straight or flush redraws. A flush on a paired board can lose to a full house. In a multiway pot, nut potential matters because several ranges can connect with the board. Evaluate a starting hand for connectivity, suits, high-card strength and the risk that its draws make second-best hands. A hand with four unrelated high cards may look impressive but coordinate poorly with flops compared with a connected double-suited holding.

## Common errors

Using one hole card in a PLO showdown; overvaluing non-nut draws in multiway pots.

## Source pages

[Pot-Limit Omaha — Jeff Hwang, PDF p. 35](../sources/pot-limit-omaha-jeff-hwang/pages-0033-0040.md#pdf-page-35) · [Pot-Limit Omaha — Jeff Hwang, PDF p. 47](../sources/pot-limit-omaha-jeff-hwang/pages-0041-0048.md#pdf-page-47) · [Doyle Brunson's Super System 2, PDF p. 264](../sources/super-system-2/pages-0257-0264.md#pdf-page-264)

## Related

[Rules, showdown and hand ranks](./01-rules-and-rankings.md) · [Outs and implied odds](./05-outs-draws-implied-odds.md) · [Omaha eight-or-better and five-card caveat](./16-omaha-hi-lo-and-five-card-caveat.md) · [PLO starting hands](./25-plo-starting-hands.md) · [PLO post-flop situations](./26-plo-postflop-situations.md) · [Topic index](../INDEX.md)
