/* O8 river buckets in the browser: a port of o8_fl/exact.py (river_sums_fast) and the river grid of
   o8_fl/exact_tables.py, step for step, so every hand gets the same bucket as in training.
   Exact hi-lo pot shares against every opponent hand (first-order card removal), against a random hand
   and against the strong range, then the grid lookup. Card ids are rank * 4 + suit (2..A, c d h s).
   O8River.load(gridUrl, tableUrl) once, then O8River.buckets(order, board) with order from
   PloRiver.comboOrder (hands in o8-classes.json order). */
(function (root) {
  "use strict";
  const NO_LOW = 9 ** 5;
  const NO_BUCKET = 65535;
  const BASE5 = 13 ** 5;
  const OPPONENTS = 178365;  // C(47, 4)
  let grid = null;  // {bins, edges, weights (per class), table (Uint16Array)}
  let classOfLex = null;

  // ---------- evaluator (o8_fl/evaluator.py) ----------
  function straightTop(mask) {
    for (let top = 12; top > 3; top--) {
      const window = 0b11111 << (top - 4);
      if ((mask & window) === window) return top;
    }
    const wheel = (1 << 12) | 0b1111;
    return (mask & wheel) === wheel ? 3 : -1;
  }

  const counts13 = new Int32Array(13);
  function high5(c0, c1, c2, c3, c4) {
    counts13.fill(0);
    counts13[c0 >> 2]++; counts13[c1 >> 2]++; counts13[c2 >> 2]++; counts13[c3 >> 2]++; counts13[c4 >> 2]++;
    const suit = c0 & 3;
    const flush = (c1 & 3) === suit && (c2 & 3) === suit && (c3 & 3) === suit && (c4 & 3) === suit;
    let mask = 0, distinct = 0;
    for (let r = 0; r < 13; r++) if (counts13[r]) { mask |= 1 << r; distinct++; }
    if (distinct === 5) {
      const top = straightTop(mask);
      if (top >= 0) return (flush ? 8 : 4) * BASE5 + top;
    }
    let value = 0, maxCount = 0, pairs = 0;
    for (let count = 4; count > 0; count--) {
      for (let r = 12; r >= 0; r--) {
        if (counts13[r] === count) {
          value = value * 13 + r;
          if (count > maxCount) maxCount = count;
          if (count === 2) pairs++;
        }
      }
    }
    for (let i = distinct; i < 5; i++) value *= 13;
    const category = flush ? 5 : maxCount === 4 ? 7 : maxCount === 3 ? (pairs === 1 ? 6 : 3)
      : pairs === 2 ? 2 : pairs === 1 ? 1 : 0;
    return category * BASE5 + value;
  }

  const LOW_VALUE = [2, 3, 4, 5, 6, 7, 8, 0, 0, 0, 0, 0, 1];
  function low5(c0, c1, c2, c3, c4) {
    let mask = 0;
    for (const card of [c0, c1, c2, c3, c4]) {
      const v = LOW_VALUE[card >> 2];
      if (v === 0 || (mask >> v) & 1) return NO_LOW;
      mask |= 1 << v;
    }
    let code = 0;
    for (let v = 8; v > 0; v--) if ((mask >> v) & 1) code = code * 9 + v;
    return code;
  }

  // ---------- combo ranks: position in combinations(range(52), 4) ----------
  const choose = (n, k) => { let r = 1; for (let i = 0; i < k; i++) r = r * (n - i) / (i + 1); return Math.round(r); };
  const START = [3, 2, 1].map(k => { const s = [0]; for (let x = 0; x < 52; x++) s.push(s[x] + choose(51 - x, k)); return s; });
  // a < b < c < d
  const lexRank = (a, b, c, d) => START[0][a] + (START[1][b] - START[1][a + 1]) + (START[2][c] - START[2][b + 1]) + (d - c - 1);

  // ---------- grids ----------
  function searchsorted(sorted, value, right) {
    let lo = 0, hi = sorted.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (right ? sorted[mid] <= value : sorted[mid] < value) lo = mid + 1; else hi = mid;
    }
    return lo;
  }

  function pairTables(board) {
    const hi = new Float64Array(52 * 52).fill(-1), lo = new Float64Array(52 * 52).fill(NO_LOW);
    const on = new Uint8Array(52);
    for (const c of board) on[c] = 1;
    for (let a = 0; a < 52; a++) {
      if (on[a]) continue;
      for (let b = a + 1; b < 52; b++) {
        if (on[b]) continue;
        let bestHi = -1, bestLo = NO_LOW;
        for (let x = 0; x < 5; x++) for (let y = x + 1; y < 5; y++) for (let z = y + 1; z < 5; z++) {
          const v = high5(a, b, board[x], board[y], board[z]);
          if (v > bestHi) bestHi = v;
          const w = low5(a, b, board[x], board[y], board[z]);
          if (w < bestLo) bestLo = w;
        }
        hi[a * 52 + b] = hi[b * 52 + a] = bestHi;
        lo[a * 52 + b] = lo[b * 52 + a] = bestLo;
      }
    }
    return { hi, lo, on };
  }

  function handValue(h0, h1, h2, h3, pt) {
    const cards = [h0, h1, h2, h3];
    let bestHi = -1, bestLo = NO_LOW;
    for (let i = 0; i < 4; i++) for (let j = i + 1; j < 4; j++) {
      const k = cards[i] * 52 + cards[j];
      if (pt.hi[k] > bestHi) bestHi = pt.hi[k];
      if (pt.lo[k] < bestLo) bestLo = pt.lo[k];
    }
    return [bestHi, bestLo];
  }

  function opponentGrids(board, pt) {
    const live = [];
    for (let c = 0; c < 52; c++) if (!pt.on[c]) live.push(c);
    const oppHi = new Float64Array(OPPONENTS), oppLo = new Float64Array(OPPONENTS);
    const oppCards = new Uint8Array(OPPONENTS * 4), oppWeight = new Float64Array(OPPONENTS);
    let k = 0;
    for (let a = 0; a < 47; a++) for (let b = a + 1; b < 47; b++) for (let c = b + 1; c < 47; c++) for (let d = c + 1; d < 47; d++) {
      const A = live[a], B = live[b], C = live[c], D = live[d];
      const [h, l] = handValue(A, B, C, D, pt);
      oppHi[k] = h; oppLo[k] = l;
      oppCards[4 * k] = A; oppCards[4 * k + 1] = B; oppCards[4 * k + 2] = C; oppCards[4 * k + 3] = D;
      oppWeight[k] = grid.weights[classOfLex[lexRank(A, B, C, D)]];
      k++;
    }
    const highs = Float64Array.from(new Set(oppHi)).sort(), lows = Float64Array.from(new Set(oppLo)).sort();
    const nh = highs.length, nl = lows.length, W = nl + 1, plane = (nh + 1) * W;
    const counts = new Float64Array(53 * plane), strong = new Float64Array(53 * plane);
    for (let k2 = 0; k2 < OPPONENTS; k2++) {
      const i = searchsorted(highs, oppHi[k2], false) + 1, j = searchsorted(lows, oppLo[k2], false) + 1;
      const w = oppWeight[k2], cell = i * W + j;
      for (const g of [52, oppCards[4 * k2], oppCards[4 * k2 + 1], oppCards[4 * k2 + 2], oppCards[4 * k2 + 3]]) {
        counts[g * plane + cell] += 1;
        strong[g * plane + cell] += w;
      }
    }
    for (let g = 0; g < 53; g++) {
      const o = g * plane;
      for (let i = 1; i <= nh; i++) for (let j = 1; j <= nl; j++) {
        const at = o + i * W + j;
        counts[at] += counts[at - W] + counts[at - 1] - counts[at - W - 1];
        strong[at] += strong[at - W] + strong[at - 1] - strong[at - W - 1];
      }
    }
    return { highs, lows, counts, strong, W, plane };
  }

  function rect(arr, gr, g, i0, i1, j0, j1) {
    if (i1 <= i0 || j1 <= j0) return 0;
    const o = g * gr.plane, W = gr.W;
    return arr[o + i1 * W + j1] - arr[o + i0 * W + j1] - arr[o + i1 * W + j0] + arr[o + i0 * W + j0];
  }

  // exact._sums: (N, SH, SL, SQ, W, WH, WL) of grid g against a hero with (myHi, myLo), added into out
  function sums(g, myHi, myLo, gr, out) {
    const nh = gr.highs.length, nl = gr.lows.length;
    const hLess = searchsorted(gr.highs, myHi, false), hMore = searchsorted(gr.highs, myHi, true);
    const hasNone = nl > 0 && gr.lows[nl - 1] === NO_LOW;
    const real = hasNone ? nl - 1 : nl;
    const spans = [[0, hLess, 4], [hLess, hMore, 2], [hMore, nh, 0]];
    let groups;
    if (myLo === NO_LOW) groups = [[real, nl, 1, 0], [0, real, 2, 0]];
    else {
      const lLess = searchsorted(gr.lows, myLo, false), lMore = searchsorted(gr.lows, myLo, true);
      groups = [[0, lLess, 2, 0], [lLess, lMore, 2, 1], [lMore, real, 2, 2], [real, nl, 2, 2]];
    }
    for (const [i0, i1, win] of spans) {
      if (i1 <= i0) continue;
      for (const [j0, j1, div, lq] of groups) {
        const hq = Math.floor(win / div);
        const n = rect(gr.counts, gr, g, i0, i1, j0, j1), w = rect(gr.strong, gr, g, i0, i1, j0, j1);
        out[0] += n; out[1] += n * hq; out[2] += n * lq; out[3] += n * (hq + lq) * (hq + lq);
        out[4] += w; out[5] += w * hq; out[6] += w * lq;
      }
    }
  }

  function cellOf(f) {
    let cell = 0;
    for (let d = 0; d < 5; d++) {
      const b = searchsorted(grid.edges[d].subarray(0, grid.bins[d] - 1), f[d], true);
      cell = cell * grid.bins[d] + b;
    }
    return cell;
  }

  function buckets(order, board) {
    if (!grid) throw new Error("O8River.load first");
    if (!classOfLex) {
      classOfLex = new Uint16Array(270725);
      let at = 0;
      order.sizes.forEach((size, cls) => {
        for (let i = 0; i < size; i++, at++) {
          const c = order.cards;
          classOfLex[lexRank(c[4 * at], c[4 * at + 1], c[4 * at + 2], c[4 * at + 3])] = cls;
        }
      });
    }
    const pt = pairTables(board), gr = opponentGrids(board, pt);
    const cards = order.cards, n = cards.length / 4;
    const myHi = new Float64Array(n).fill(-1), myLo = new Float64Array(n);
    const keyOf = new Map(), which = new Int32Array(n).fill(-1), values = [];
    for (let k = 0; k < n; k++) {
      const h0 = cards[4 * k], h1 = cards[4 * k + 1], h2 = cards[4 * k + 2], h3 = cards[4 * k + 3];
      if (pt.on[h0] || pt.on[h1] || pt.on[h2] || pt.on[h3]) continue;
      const [h, l] = handValue(h0, h1, h2, h3, pt);
      myHi[k] = h; myLo[k] = l;
      const key = h * (NO_LOW + 1) + l;
      let d = keyOf.get(key);
      if (d === undefined) { d = values.length; keyOf.set(key, d); values.push([h, l]); }
      which[k] = d;
    }
    const table = new Float64Array(53 * values.length * 7);
    values.forEach(([h, l], d) => {
      for (let g = 0; g < 53; g++) if (g === 52 || !pt.on[g]) sums(g, h, l, gr, table.subarray((g * values.length + d) * 7, (g * values.length + d) * 7 + 7));
    });
    const out = new Uint16Array(n).fill(NO_BUCKET), s = new Float64Array(7), f = new Float64Array(5);
    const D = values.length;
    for (let k = 0; k < n; k++) {
      const d = which[k];
      if (d < 0) continue;
      for (let m = 0; m < 7; m++) {
        s[m] = table[(52 * D + d) * 7 + m] - table[(cards[4 * k] * D + d) * 7 + m] - table[(cards[4 * k + 1] * D + d) * 7 + m]
          - table[(cards[4 * k + 2] * D + d) * 7 + m] - table[(cards[4 * k + 3] * D + d) * 7 + m];
      }
      if (s[0] <= 0) continue;
      const hi = s[1] / (4.0 * s[0]), lo = s[2] / (4.0 * s[0]), sq = s[3] / (16.0 * s[0]);
      const total = hi + lo;
      f[0] = hi; f[1] = lo; f[2] = Math.sqrt(Math.max(sq - total * total, 0.0));
      f[3] = s[5] / (4.0 * s[4]); f[4] = s[6] / (4.0 * s[4]);
      out[k] = grid.table[cellOf(f)];
    }
    return out;
  }

  async function load(gridUrl, tableUrl) {
    if (grid) return;
    const [meta, response] = await Promise.all([fetch(gridUrl).then(r => {
      if (!r.ok) throw new Error(`${gridUrl}: ${r.status}`);
      return r.json();
    }), fetch(tableUrl)]);
    if (!response.ok) throw new Error(`${tableUrl}: ${response.status}`);
    const stream = response.body.pipeThrough(new DecompressionStream("gzip"));
    grid = { bins: meta.bins, edges: meta.edges.map(e => Float64Array.from(e)), weights: Float64Array.from(meta.weights),
             table: new Uint16Array(await new Response(stream).arrayBuffer()) };
  }

  // Node tests set the grid directly.
  function setGrid(value) { grid = value; classOfLex = null; }

  const api = { load, buckets, setGrid, high5, low5, lexRank };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.O8River = api;
})(typeof window !== "undefined" ? window : globalThis);
