"""Count nodes/terminals of a proposed OPEN3BET-v0 preflop tree. No payoffs, no solving.

Actions, all sized in bb, stacks in bb, one betting round (preflop only):
  unopened : fold, open(r1), allin
  vs raise : fold, call, 3bet(r2 = 3x facing raise), allin
  vs 3bet+ : fold, call, allin            (4bet is allin only)
  vs allin : fold, call
Cap: at most `cap` players may still hold cards at the end of preflop (GTO Wizard: 3).
"""
import itertools, sys

F, C, R, A = "f", "c", "r", "a"

def count(n, stacks, sb=0.5, bb=1.0, ante=0.0, cap=3, r1=2.2, mult=3.0):
    nodes = 0
    terminals = {"allfold": 0, "uncontested": 0, "allin_show": 0, "flop": 0}
    flop_ways = {}

    def walk(seat, invested, live, last_raise, raises):
        nonlocal nodes
        if seat == n or (len(live) == 1 and seat > n - 1):
            return
        if seat == n:
            return
        # terminal checks handled by caller
        pass

    # explicit recursion over seats in order, one pass (no limp/re-open of action after BB)
    def rec(seat, invested, live, cur_bet, raises):
        nonlocal nodes
        if seat == n:
            close(invested, live, cur_bet)
            return
        if len(live) == 1 and seat >= n - 1 and cur_bet > bb:
            close(invested, live, cur_bet); return
        acts = []
        st = stacks[seat]
        facing = cur_bet > bb or (cur_bet == bb and seat < n - 1)
        if cur_bet <= bb and seat < n - 1:   # unopened, not the BB
            acts = [F, R, A]
        elif cur_bet <= bb:                  # BB, unopened -> walk
            close(invested, live, cur_bet); return
        else:
            acts = [F, C, R, A] if raises < 2 else [F, C, A]
        if len(live) >= cap:                 # cap reached: everyone left must fold
            for s in range(seat, n):
                pass
            close(invested, live, cur_bet); return
        raise_size = min(st, cur_bet * mult if raises else r1)
        if raise_size >= st - 1e-9:
            acts = [a for a in acts if a != R]
        nodes += 1
        for a in acts:
            if a == F:
                rec(seat + 1, invested, live, cur_bet, raises)
            elif a == C:
                rec(seat + 1, invested | {seat: min(st, cur_bet)}, live | {seat}, cur_bet, raises)
            elif a == R:
                rec(seat + 1, invested | {seat: raise_size}, live | {seat}, raise_size, raises + 1)
            else:
                rec(seat + 1, invested | {seat: st}, live | {seat}, max(cur_bet, st), raises + 1)

    def close(invested, live, cur_bet):
        if len(live) == 0:
            terminals["allfold"] += 1
        elif len(live) == 1:
            terminals["uncontested"] += 1
        else:
            allin = all(invested.get(s, 0.0) >= stacks[s] - 1e-9 for s in live)
            if allin:
                terminals["allin_show"] += 1
            else:
                terminals["flop"] += 1
                key = (len(live), round(sum(invested.values()), 2))
                flop_ways[key] = flop_ways.get(key, 0) + 1

    rec(0, {}, set(), bb, 0)
    return nodes, terminals, len(flop_ways)

for n in (2, 3, 6, 9):
    for depth in (15, 30):
        st = tuple([float(depth)] * n)
        nodes, term, kinds = count(n, st)
        tot = sum(term.values())
        print(f"n={n} {depth}bb  nodes={nodes:5d}  terminals={tot:5d}  {term}  distinct flop (players,pot)={kinds}")
