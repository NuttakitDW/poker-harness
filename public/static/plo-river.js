/* River buckets for the PLO4 explorer, computed in the browser (plo_premium_proof.postflop, street 3).
   On the river a hand's bucket is only its strength: the share of all two-card holdings (from the cards
   not on the board) whose best Omaha hand beats it, cut into 10 bins. Card ids are rank * 4 + suit with
   ranks 2..A = 0..12 and suits c d h s = 0..3, as in the solver.
   PloRiver.comboOrder(classRows) lists every four-card hand in plo-classes.json order (the order of the
   flop and turn tables); PloRiver.buckets(order, board) gives the river bucket of each, 65535 where the
   hand holds a board card. */
(function (root) {
  "use strict";
  const NO_BUCKET = 65535;
  const EDGES = [0, 0.001, 0.01, 0.03, 0.06, 0.12, 0.2, 0.3, 0.5];  // postflop.STRENGTH_EDGES
  const PERMS = (function permute(rest) {
    if (rest.length === 0) return [[]];
    return rest.flatMap((x, i) => permute([...rest.slice(0, i), ...rest.slice(i + 1)]).map(tail => [x, ...tail]));
  })([0, 1, 2, 3]);
  const RANKS = "23456789TJQKA", SUITS = "cdhs";
  const cardId = text => RANKS.indexOf(text[0]) * 4 + SUITS.indexOf(text[1]);

  // Strength of five cards: larger is better, equal for hands that tie.
  function eval5(a, b, c, d, e) {
    const ranks = [a >> 2, b >> 2, c >> 2, d >> 2, e >> 2];
    const suit = a & 3;
    const flush = (b & 3) === suit && (c & 3) === suit && (d & 3) === suit && (e & 3) === suit;
    const counts = new Array(13).fill(0);
    let mask = 0;
    for (const r of ranks) { counts[r]++; mask |= 1 << r; }
    let straightHigh = -1;
    if (ranks.length === 5 && popcount(mask) === 5) {
      if (mask === 0b1000000001111) straightHigh = 3;  // A-2-3-4-5
      else { const low = mask & -mask; if (mask === low * 31) straightHigh = 31 - Math.clz32(mask); }
    }
    if (straightHigh >= 0) return ((flush ? 8 : 4) << 20) | straightHigh;
    // ranks by (count, rank), highest first
    const groups = [];
    for (let r = 12; r >= 0; r--) if (counts[r]) groups.push([counts[r], r]);
    groups.sort((p, q) => q[0] - p[0] || q[1] - p[1]);
    const shape = groups.map(g => g[0]).join("");
    const category = flush ? 5 : shape === "41" ? 7 : shape === "32" ? 6 : shape === "311" ? 3
      : shape === "221" ? 2 : shape === "2111" ? 1 : 0;
    let value = category;
    for (const [, r] of groups) value = value * 16 + r;
    for (let k = groups.length; k < 5; k++) value *= 16;
    return value;
  }

  function popcount(x) { let n = 0; while (x) { x &= x - 1; n++; } return n; }

  function canonical(a, b, c, d) {
    let best = Infinity;
    for (const p of PERMS) {
      const w = [(a >> 2) * 4 + p[a & 3], (b >> 2) * 4 + p[b & 3], (c >> 2) * 4 + p[c & 3], (d >> 2) * 4 + p[d & 3]]
        .sort((x, y) => x - y);
      const key = ((w[0] * 52 + w[1]) * 52 + w[2]) * 52 + w[3];
      if (key < best) best = key;
    }
    return best;
  }

  // Every four-card hand (card ids, ascending) grouped by class in ``classRows`` order.
  function comboOrder(classRows) {
    const index = new Map();
    classRows.forEach((cards, i) => {
      const ids = cards.map(cardId).sort((x, y) => x - y);
      index.set(((ids[0] * 52 + ids[1]) * 52 + ids[2]) * 52 + ids[3], i);
    });
    const lists = classRows.map(() => []);
    for (let a = 0; a < 52; a++) for (let b = a + 1; b < 52; b++) for (let c = b + 1; c < 52; c++) for (let d = c + 1; d < 52; d++) {
      const i = index.get(canonical(a, b, c, d));
      if (i === undefined) throw new Error("hand class missing");
      lists[i].push(a, b, c, d);
    }
    const order = new Uint8Array(270725 * 4);
    let at = 0;
    for (const list of lists) { order.set(list, at); at += list.length; }
    return { cards: order, sizes: lists.map(list => list.length / 4) };
  }

  function buckets(order, board) {
    const on = new Uint8Array(52);
    for (const card of board) on[card] = 1;
    const triples = [];
    for (let x = 0; x < 5; x++) for (let y = x + 1; y < 5; y++) for (let z = y + 1; z < 5; z++) triples.push([board[x], board[y], board[z]]);
    const pairBest = new Int32Array(52 * 52);
    const dist = [];
    for (let a = 0; a < 52; a++) {
      if (on[a]) continue;
      for (let b = a + 1; b < 52; b++) {
        if (on[b]) continue;
        let best = -1;
        for (const [x, y, z] of triples) { const v = eval5(a, b, x, y, z); if (v > best) best = v; }
        pairBest[a * 52 + b] = best;
        dist.push(best);
      }
    }
    const sorted = Int32Array.from(dist).sort();
    const n = sorted.length;
    const above = v => {  // holdings strictly stronger than v
      let lo = 0, hi = n;
      while (lo < hi) { const mid = (lo + hi) >> 1; if (sorted[mid] <= v) lo = mid + 1; else hi = mid; }
      return n - lo;
    };
    const cards = order.cards, out = new Uint16Array(cards.length / 4);
    for (let i = 0; i < out.length; i++) {
      const h0 = cards[4 * i], h1 = cards[4 * i + 1], h2 = cards[4 * i + 2], h3 = cards[4 * i + 3];
      if (on[h0] || on[h1] || on[h2] || on[h3]) { out[i] = NO_BUCKET; continue; }
      const best = Math.max(pairBest[h0 * 52 + h1], pairBest[h0 * 52 + h2], pairBest[h0 * 52 + h3],
        pairBest[h1 * 52 + h2], pairBest[h1 * 52 + h3], pairBest[h2 * 52 + h3]);
      const better = above(best);
      let bin = EDGES.length;
      if (better === 0) bin = 0;
      else for (let k = 1; k < EDGES.length; k++) if (better / n <= EDGES[k]) { bin = k; break; }
      out[i] = bin;
    }
    return out;
  }

  const api = { comboOrder, buckets, eval5, cardId, NO_BUCKET };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.PloRiver = api;
})(typeof window !== "undefined" ? window : globalThis);
