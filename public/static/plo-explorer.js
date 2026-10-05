/* PLO range explorer, shared by /plo and the local final-table page.
   PloExplorer.mount(container, {games, gamesEl, load, initial, hash, classesUrl, tierLabel, showStack}) draws the
   action line, the two-step hand matrix, filters and hand list into ``container``.
   ``games`` [{id, label, detail}] with ``load(id)`` fetch solved games; games that all carry
   ``seats`` and ``stack`` get a table-size row and a stack row instead of one button each.
   Without games, call the returned ``show(data)`` with a solved game and ``focus({seat, hand})``
   to jump to a spot. ``tierLabel`` names the class-group filter (default "Hwang"); ``showStack: false``
   hides stack sizes, for limit games where the stack does not change the strategy.
   ``postflop: {strategyUrl, flopsUrl, flopUrl(id)}`` continues lines that reach the flop: the page
   picks a flop from the library, averages each hand class over the combos the board leaves, and
   weights every combo by how often the player to act gets there along the line. */
window.PloExplorer = (() => {
  "use strict";
  const MARKUP = `
<section class="sheet" aria-labelledby="line-title">
  <div class="line-head">
    <h2 id="line-title" class="label">Action line</h2>
    <button class="reset" id="reset" type="button">Reset</button>
  </div>
  <div class="line" id="line" aria-live="polite"></div>
</section>

<div class="work">
  <section class="sheet" aria-labelledby="spot-title">
    <h2 id="spot-title" class="spot-title">กำลังโหลด...</h2>
    <p class="spot-meta" id="spot-meta"></p>
    <div class="steps">
      <button class="pick" id="pick1" type="button" data-on="true"><small>สองใบแรก</small><span id="pick1-v">เลือก</span></button>
      <span class="plus" aria-hidden="true">+</span>
      <button class="pick" id="pick2" type="button" disabled><small>อีกสองใบ</small><span id="pick2-v">-</span></button>
      <span class="hint" id="step-hint"></span>
    </div>
    <div class="matrix" id="matrix" role="grid" aria-label="Hand matrix"></div>
    <div class="legend" id="legend"></div>
  </section>

  <section class="sheet" aria-labelledby="sum-title">
    <div class="line-head">
      <h2 id="sum-title" class="label">ตัวกรอง</h2>
      <button class="reset" id="reset-filters" type="button">Reset</button>
    </div>
    <div class="filters" style="margin-top:.5rem">
      <div class="search">
        <input id="search" type="text" inputmode="text" autocomplete="off" spellcheck="false" placeholder="ค้นมือ เช่น AsKsQd9c หรือ KQJT" aria-label="ค้นมือ">
      </div>
      <div class="chips" id="shapes" role="group" aria-label="ทรงดอก"><span class="label">ทรงดอก</span></div>
      <div class="chips" id="tiers" role="group" aria-label="Hwang tier"><span class="label">Hwang</span></div>
    </div>
    <div class="tiles" id="tiles"></div>
    <div class="bigbar" id="sum-bar" aria-hidden="true"></div>
    <div class="list-head">
      <h2 class="label" id="list-title">มือทั้งหมด</h2>
      <span class="hint mono" id="list-count"></span>
    </div>
    <div class="table-wrap">
      <table>
        <thead id="list-head"></thead>
        <tbody id="list"></tbody>
      </table>
      <p class="more" id="more" hidden></p>
    </div>
  </section>
</div>
`;

  function mount(container, options) {
    container.innerHTML = MARKUP;
    if (!document.getElementById("tip")) {
      const tip = document.createElement("div");
      tip.className = "tip";
      tip.id = "tip";
      tip.setAttribute("role", "tooltip");
      document.body.appendChild(tip);
    }
    const RANKS = "AKQJT98765432";
    const SUIT_GLYPH = { s: "♠", h: "♥", d: "♦", c: "♣" };
    const ACTION_COLOR = { pot: "var(--act-raise)", raise: "var(--act-raise)", call: "var(--act-call)", check: "var(--act-call)", fold: "var(--act-fold)" };
    const ACTION_ORDER = { pot: 0, raise: 0, call: 1, check: 1, fold: 2 };
    const TIER_LABEL = options.tierLabel || "Hwang";
    const SHOW_STACK = options.showStack !== false;
    const SHAPES = [["all", "ทั้งหมด"], ["ds", "ds"], ["ss", "ss"], ["rb", "rainbow"], ["3f", "3 ดอก"], ["mono", "4 ดอก"]];
    const LIST_LIMIT = 300;
    // A picked action tile keeps hands that take it at least this often; smaller shares are mostly
    // solver noise (an average strategy is never exactly zero).
    const ACTION_MIN = 0.05;
    const LIST_MIN_WEIGHT = 0.05;  // combos reaching a flop node, below which a hand is left out of the list
    const END_TEXT = { multiway: "คนที่สามเข้า", flop: "ไป flop", turn: "ไป turn", "hand over": "จบมือ" };
    const POST = options.postflop || null;
    const NO_BUCKET = 65535;
    const LETTER = { fold: "f", check: "k", call: "c", raise: "r", pot: "r" };
    const PAIRS = [[0, 1, 2, 3], [0, 2, 1, 3], [0, 3, 1, 2], [1, 2, 0, 3], [1, 3, 0, 2], [2, 3, 0, 1]];

    const $ = id => document.getElementById(id);
    const games = options.games || [];
    const state = { game: options.initial || (games[0] && games[0].id), path: [], first: null, second: null, shape: "all", tier: -1, query: "", action: null, board: null, flop: [], exact: true };
    let flops = null;  // the flop library: [{id, board, texture}]
    const boards = {};  // flop id -> Uint16Array of buckets in class order
    const cache = {};
    let classes = null;
    let data = null;
    let strategy = null;
    let pending = null;
    let wanted = null;

    // ---------- data ----------
    async function getJSON(url) {
      const response = await fetch(url);
      if (!response.ok) throw new Error(`${url}: ${response.status}`);
      return response.json();
    }

    function decode(b64) {
      const text = atob(b64);
      const bytes = new Uint8Array(text.length);
      for (let i = 0; i < text.length; i++) bytes[i] = text.charCodeAt(i);
      return bytes;
    }

    const rankOf = c => RANKS.indexOf(c);

    function halfKey(a, b) {
      const x = rankOf(a[0]), y = rankOf(b[0]);
      if (x === y) return x * 13 + x;
      const hi = Math.min(x, y), lo = Math.max(x, y);
      return a[1] === b[1] ? hi * 13 + lo : lo * 13 + hi;
    }

    function signature(cards) {
      const groups = {};
      for (const card of cards) (groups[card[1]] ||= []).push(rankOf(card[0]));
      return Object.values(groups).map(g => g.sort((p, q) => p - q).map(r => RANKS[r]).join(""))
        .sort((p, q) => q.length - p.length || (p < q ? -1 : p > q ? 1 : 0)).join("|");
    }

    function prepareClasses(raw) {
      return raw.rows.map(([text, shape, combos, bucket, tier]) => {
        const cards = [];
        for (let i = 0; i < 8; i += 2) cards.push(text.slice(i, i + 2));
        cards.sort((p, q) => rankOf(p[0]) - rankOf(q[0]) || (p[1] < q[1] ? -1 : 1));
        const halves = PAIRS.map(([a, b, c, d]) => [halfKey(cards[a], cards[b]), halfKey(cards[c], cards[d])]);
        return {
          cards, shape, combos, bucket, tier, halves,
          firsts: [...new Set(halves.map(h => h[0]))],
          ranks: cards.map(c => c[0]).join(""),
          sig: signature(cards),
        };
      });
    }

    async function loadGame(name) {
      if (!cache[name]) {
        const raw = await options.load(name);
        cache[name] = { raw, bytes: decode(raw.strategy) };
      }
      return cache[name];
    }

    // ---------- tree ----------
    function currentNode() {
      let index = 0;
      for (const slot of state.path) index = data.nodes[index].options[slot].child;
      return index;
    }

    function nodeProbs(index) {
      const node = data.nodes[index];
      const flop = isFlop(index);
      const n = node.options.length, buckets = flop ? data.flop.buckets : data.buckets;
      const bytes = flop ? data.flop.bytes : strategy;
      const out = new Float32Array(buckets * n);
      const base = (flop ? index - data.flopOffset : index) * buckets * 3;
      for (let b = 0; b < buckets; b++) {
        let sum = 0;
        for (let k = 0; k < n; k++) sum += bytes[base + b * 3 + k];
        for (let k = 0; k < n; k++) out[b * n + k] = sum > 0 ? bytes[base + b * 3 + k] / sum : 1 / n;
      }
      return out;
    }

    // ---------- postflop ----------
    const isFlop = index => data.flopOffset !== undefined && index >= data.flopOffset;

    // Append the flop nodes after the preflop ones and point every preflop action that ends the
    // street at the flop root of its line.
    function attachPostflop(raw, post) {
      if (raw.flopOffset !== undefined) return;
      const offset = raw.nodes.length;
      const flopNodes = post.nodes.map(node => ({ ...node, street: 1,
        options: node.options.map(o => ({ ...o, child: o.child >= 0 ? o.child + offset : -1 })) }));
      (function walk(index, history) {
        raw.nodes[index].options.forEach(option => {
          const next = history + LETTER[option.action];
          if (option.child >= 0) walk(option.child, next);
          else if (option.end === "flop" && post.roots[next] !== undefined) option.child = offset + post.roots[next];
        });
      })(0, "");
      raw.nodes = raw.nodes.concat(flopNodes);
      raw.flopOffset = offset;
      raw.flop = { buckets: post.buckets, bytes: decode(post.strategy) };
    }

    async function loadPostflop() {
      const [post, list] = await Promise.all([getJSON(POST.strategyUrl), getJSON(POST.flopsUrl)]);
      flops = list;
      return post;
    }

    async function loadBoard(id) {
      if (boards[id]) return;
      if (typeof DecompressionStream === "undefined") throw new Error("เบราว์เซอร์นี้เปิดข้อมูล flop ไม่ได้ ลองอัปเดตเบราว์เซอร์");
      const response = await fetch(POST.flopUrl(id));
      if (!response.ok) throw new Error(`flop ${id}: ${response.status}`);
      const buffer = await new Response(response.body.pipeThrough(new DecompressionStream("gzip"))).arrayBuffer();
      boards[id] = new Uint16Array(buffer);
    }

    const boardEntry = () => flops && flops.find(f => f.id === state.board);
    // The cards whose data is shown: the picked flop when the library holds it (up to a suit swap,
    // which never changes a class's strategy), otherwise the library flop used in its place.
    const boardCards = () => { const e = boardEntry(); return !e ? [] : state.exact ? state.flop : e.board.match(/../g); };

    const RANK_ORDER = "23456789TJQKA";
    const cardId = card => RANK_ORDER.indexOf(card[0]) * 4 + "cdhs".indexOf(card[1]);
    const ID_PERMS = (function permute(rest) {
      if (rest.length === 0) return [[]];
      return rest.flatMap((x, i) => permute([...rest.slice(0, i), ...rest.slice(i + 1)]).map(tail => [x, ...tail]));
    })([0, 1, 2, 3]);

    // The same key for every flop that is a suit relabelling of another.
    function flopKey(cards) {
      let best = null;
      for (const perm of ID_PERMS) {
        const key = cards.map(card => { const id = cardId(card); return (id >> 2) * 4 + perm[id & 3]; })
          .sort((a, b) => a - b).join(".");
        if (best === null || key < best) best = key;
      }
      return best;
    }

    function flopTexture(cards) {
      const suits = new Set(cards.map(c => c[1])).size, ranks = cards.map(c => c[0]);
      const top = Math.max(...ranks.map(r => RANK_ORDER.indexOf(r)));
      return [{ 3: "rainbow", 2: "two-tone", 1: "monotone" }[suits], { 3: "unpaired", 2: "paired", 1: "trips" }[new Set(ranks).size],
        new Set(ranks.filter(r => "A2345678".includes(r))).size, top === 12 ? "A" : top >= 10 ? "K-Q" : top >= 7 ? "J-9" : "8-2"];
    }

    // Library flop for the picked cards: the same flop if held, else the nearest flop of the same texture.
    function resolveFlop(cards) {
      for (const f of flops) f.key ||= flopKey(f.board.match(/../g));
      const key = flopKey(cards);
      const same = flops.find(f => f.key === key);
      if (same) return { id: same.id, exact: true };
      const texture = flopTexture(cards).join("|");
      const ranks = list => list.map(c => RANK_ORDER.indexOf(c[0])).sort((a, b) => b - a);
      const mine = ranks(cards);
      const distance = f => ranks(f.board.match(/../g)).reduce((sum, r, i) => sum + Math.abs(r - mine[i]), 0)
        + (f.texture.join("|") === texture ? 0 : 100);
      const nearest = flops.reduce((best, f) => (distance(f) < distance(best) ? f : best));
      return { id: nearest.id, exact: false };
    }

    function pickFlopCard(card) {
      const at = state.flop.indexOf(card);
      if (at >= 0) state.flop = state.flop.filter(c => c !== card);
      else if (state.flop.length < 3) state.flop = [...state.flop, card];
      setFlop();
    }

    function setFlop() {
      if (state.flop.length === 3 && flops) {
        const found = resolveFlop(state.flop);
        state.board = found.id;
        state.exact = found.exact;
      } else {
        state.board = null;
      }
      render();
      if (state.board) loadBoard(state.board).then(render).catch(fail);
    }

    // Decisions on the way to the current node: [{index, slot}].
    function pathPairs() {
      const pairs = [];
      let index = 0;
      for (const slot of state.path) { pairs.push({ index, slot }); index = data.nodes[index].options[slot].child; }
      return pairs;
    }

    // Per class: w = combos weighted by how often the player to act reaches this node, p = average strategy.
    function preflopView(index) {
      const n = data.nodes[index].options.length, probs = nodeProbs(index);
      const w = new Float64Array(classes.length), p = new Float32Array(classes.length * n);
      classes.forEach((c, i) => { w[i] = c.combos; p.set(probs.subarray(c.bucket * n, c.bucket * n + n), i * n); });
      return { w, p };
    }

    function flopView(index) {
      const node = data.nodes[index], n = node.options.length, current = nodeProbs(index);
      const mine = pathPairs().filter(({ index: i }) => data.nodes[i].actor === node.actor)
        .map(({ index: i, slot }) => ({ flop: isFlop(i), probs: nodeProbs(i), slot, m: data.nodes[i].options.length }));
      const pre = mine.filter(x => !x.flop), post = mine.filter(x => x.flop);
      const buckets = boards[state.board];
      const w = new Float64Array(classes.length), p = new Float32Array(classes.length * n);
      const acc = new Float64Array(n);
      let offset = 0;
      classes.forEach((c, i) => {
        let reach = 1;
        for (const x of pre) reach *= x.probs[c.bucket * x.m + x.slot];
        acc.fill(0);
        let total = 0;
        for (let k = 0; reach > 0 && k < c.combos; k++) {
          const b = buckets[offset + k];
          if (b === NO_BUCKET) continue;
          let r = reach;
          for (const x of post) r *= x.probs[b * x.m + x.slot];
          if (r <= 0) continue;
          total += r;
          for (let j = 0; j < n; j++) acc[j] += r * current[b * n + j];
        }
        offset += c.combos;
        w[i] = total;
        for (let j = 0; j < n; j++) p[i * n + j] = total > 0 ? acc[j] / total : 0;
      });
      return { w, p };
    }

    // A combo of the class that does not use a board card (suits relabelled), for the hand list.
    function offBoard(cards) {
      const board = new Set(boardCards());
      if (!cards.some(card => board.has(card))) return cards;
      for (const perm of SUIT_PERMS) {
        const moved = cards.map(card => card[0] + perm["shdc".indexOf(card[1])]);
        if (!moved.some(card => board.has(card))) return moved;
      }
      return cards;
    }
    const SUIT_PERMS = (function permute(rest) {
      if (rest.length === 0) return [[]];
      return rest.flatMap((x, i) => permute([...rest.slice(0, i), ...rest.slice(i + 1)]).map(tail => [x, ...tail]));
    })(["s", "h", "d", "c"]);

    function optionLabel(node, option) {
      if (option.action === "fold") return { name: "Fold", amount: "" };
      if (option.action === "check") return { name: "Check", amount: "" };
      const amount = fmt(option.total);
      if (option.action === "raise" && node.street === 1 && node.to_call === 0) return { name: "Bet", amount };
      if (option.action === "call") {
        const limp = !node.street && Math.abs(option.total - 1) < 1e-9;  // calling the big blind itself: nobody has raised
        return { name: option.all_in ? "Call all-in" : limp ? "Limp" : "Call", amount };
      }
      return { name: option.all_in ? "All-in" : "Raise", amount };
    }

    const pct = share => share > 0 && share < 0.001 ? "<0.1%" : `${(share * 100).toFixed(1)}%`;
    const fmt = x => (Math.round(x * 1000) / 1000).toString();
    const fmtCombos = x => Math.round(x).toLocaleString("en-US");

    function lineWords() {
      const words = [];
      let index = 0;
      for (const slot of state.path) {
        const node = data.nodes[index], option = node.options[slot];
        if (option.action !== "fold") {
          const label = optionLabel(node, option);
          words.push(`${data.seats[node.actor]} ${label.name.toLowerCase()}${label.amount ? " " + label.amount : ""}`);
        }
        index = option.child;
      }
      return words;
    }

    // ---------- aggregation ----------
    function passes(c) {
      if (state.shape !== "all" && c.shape !== state.shape) return false;
      if (state.tier >= 0 && c.tier !== state.tier) return false;
      return true;
    }

    function parseQuery(text) {
      const raw = text.replace(/[\s,]/g, "").replace(/10/g, "T");
      if (!raw) return null;
      const exact = raw.match(/^([2-9TJQKA][cdhs]){4}$/i);
      if (exact) {
        const cards = raw.match(/../g).map(c => c[0].toUpperCase() + c[1].toLowerCase());
        if (new Set(cards).size !== 4) return { bad: true };
        cards.sort((a, b) => rankOf(a[0]) - rankOf(b[0]));
        return { sig: signature(cards), cards };
      }
      const ranks = raw.toUpperCase();
      if (/^[2-9TJQKA]{1,4}$/.test(ranks)) return { ranks: [...ranks].sort((p, q) => rankOf(p) - rankOf(q)) };
      return { bad: true };
    }

    function queryMatch(c, q) {
      if (!q) return true;
      if (q.bad) return false;
      if (q.sig) return c.sig === q.sig;
      const pool = [...c.ranks];
      for (const r of q.ranks) {
        const at = pool.indexOf(r);
        if (at < 0) return false;
        pool.splice(at, 1);
      }
      return true;
    }

    // The action tile picked at this decision ({node, slot}), or null.
    function pickedAction() {
      return state.action && state.action.node === currentNode() ? state.action.slot : null;
    }

    function aggregate(view, n) {
      const picked = pickedAction();
      const cells = Array.from({ length: 169 }, () => ({ combos: 0, freq: new Float64Array(n) }));
      const total = { combos: 0, freq: new Float64Array(n), range: 0 };
      const rows = [];
      const query = parseQuery(state.query);
      const onFlop = Boolean(state.board) && isFlop(currentNode());
      for (let i = 0; i < classes.length; i++) {
        const c = classes[i], weight = view.w[i];
        if (!(weight > 0)) continue;
        total.range += weight;
        if (!passes(c) || !queryMatch(c, query)) continue;
        const p = view.p.subarray(i * n, i * n + n);
        let keys;
        if (state.first === null) {
          keys = c.firsts;
        } else {
          keys = [...new Set(c.halves.filter(h => h[0] === state.first).map(h => h[1]))];
          if (!keys.length) continue;
        }
        for (const key of keys) {  // the matrix keeps every choice visible; the pick narrows the summary
          const cell = cells[key];
          cell.combos += weight;
          for (let k = 0; k < n; k++) cell.freq[k] += weight * p[k];
        }
        if (state.second !== null && !keys.includes(state.second)) continue;
        total.combos += weight;
        for (let k = 0; k < n; k++) total.freq[k] += weight * p[k];
        const cards = query && query.sig ? query.cards : onFlop ? offBoard(c.cards) : c.cards;
        // After the flop, hands the line almost never brings here stay in the totals but not the list.
        if ((picked === null || p[picked] >= ACTION_MIN) && (!onFlop || weight >= LIST_MIN_WEIGHT)) rows.push({ c, p, w: weight, cards });  // searched hands keep their own suits
      }
      return { cells, total, rows };
    }

    // ---------- render ----------
    function cellName(key) {
      const row = Math.floor(key / 13), col = key % 13;
      if (row === col) return RANKS[row] + RANKS[row];
      return row < col ? RANKS[row] + RANKS[col] + "s" : RANKS[col] + RANKS[row] + "o";
    }

    function orderedSlots(node) {
      return node.options.map((o, k) => k).sort((p, q) => ACTION_ORDER[node.options[p].action] - ACTION_ORDER[node.options[q].action]);
    }

    // ``only``: draw just that action's share and leave the rest of the bar empty.
    function barHTML(freq, node, weight, only = null) {
      return orderedSlots(node).filter(k => only === null || k === only).map(k => {
        const share = weight > 0 ? freq[k] / weight : 0;
        return share > 0.0005 ? `<i style="width:${(share * 100).toFixed(2)}%;background:${ACTION_COLOR[node.options[k].action]}"></i>` : "";
      }).join("");
    }

    function renderGames() {
      if (!options.gamesEl) return;
      const grid = games.length && games.every(game => game.seats && game.stack);
      options.gamesEl.innerHTML = grid ? gameAxes() : games.map(game =>
        `<button class="game" type="button" data-game="${game.id}" aria-pressed="${state.game === game.id}"><b>${game.label}</b><span>${game.detail}</span></button>`).join("");
    }

    // Two rows (players, stack): each button points at the game that keeps the other row's choice.
    function gameAxes() {
      const current = games.find(game => game.id === state.game) || games[0];
      const pick = (seats, stack) => games.find(game => game.seats === seats && game.stack === stack);
      const values = key => [...new Set(games.map(game => game[key]))].sort((a, b) => b - a);
      const row = (title, key, text) => `<div class="game-axis" role="group" aria-label="${title}"><span class="game-axis-name">${title}</span>`
        + values(key).map(value => {
          const target = key === "seats" ? pick(value, current.stack) : pick(current.seats, value);
          const on = current[key] === value;
          return target
            ? `<button class="game" type="button" data-game="${target.id}" aria-pressed="${on}"><b>${text(value)}</b></button>`
            : `<button class="game" type="button" disabled><b>${text(value)}</b></button>`;
        }).join("") + "</div>";
      return row("ผู้เล่น", "seats", n => `${n}-max`) + row("Stack", "stack", bb => `${bb}bb`)
        + `<p class="game-detail">${current.detail}</p>`;
    }

    function seatName(node) {
      const seat = data.seats[node.actor];
      const alias = seat === "UTG" && data.seats.length === 6;  // LJ is the first seat at 6-max
      return `${seat}${alias ? ' <span class="mono">/ LJ</span>' : ""}`;
    }

    // Past seats (click to go back to that decision), the seat to act, and the seats still to
    // come if everyone folds to them (click to jump there).
    function renderLine() {
      const steps = [];
      let index = 0;
      [...state.path, null].forEach((slot, depth) => {
        const node = data.nodes[index];
        if (isFlop(index) && node.street === 1 && depth > 0 && !isFlop(pathPairs()[depth - 1].index)) steps.push(boardStep());
        const opts = orderedSlots(node).map(k => {
          const option = node.options[k];
          const label = optionLabel(node, option);
          const end = option.child < 0 ? `<span class="end">${END_TEXT[option.end] || ""}</span>` : "";
          return `<button class="opt" type="button" data-depth="${depth}" data-slot="${k}" aria-pressed="${slot === k}" ${option.child < 0 ? "disabled" : ""}>`
            + `<span class="sw" style="background:${ACTION_COLOR[option.action]}"></span>${label.name}${end}`
            + `<span class="amt">${label.amount}</span></button>`;
        }).join("");
        const head = `<span>${seatName(node)}</span>` + (SHOW_STACK ? `<span class="mono">${fmt(node.behind[node.actor])}bb</span>` : "");
        steps.push(slot === null
          ? `<div class="step now"><div class="step-seat">${head}</div><div class="step-opts">${opts}</div></div>`
          : `<div class="step"><button class="step-seat" type="button" data-back="${depth}" title="กลับไปที่ decision นี้">${head}</button><div class="step-opts">${opts}</div></div>`);
        if (slot !== null) index = node.options[slot].child;
      });
      for (let folds = 1; folds < data.seats.length; folds++) {
        const fold = data.nodes[index].options.findIndex(o => o.action === "fold");
        if (fold < 0 || data.nodes[index].options[fold].child < 0) break;
        index = data.nodes[index].options[fold].child;
        const node = data.nodes[index];
        steps.push(`<button class="step ahead" type="button" data-ahead="${folds}" title="ทุกคนก่อนหน้า fold แล้วไปที่ ${data.seats[node.actor]}">`
          + `<span class="step-seat"><span>${seatName(node)}</span>${SHOW_STACK ? `<span class="mono">${fmt(node.behind[node.actor])}bb</span>` : ""}</span></button>`);
      }
      const line = $("line");
      line.innerHTML = steps.join("");
      const now = line.querySelector(".now");
      line.scrollLeft = Math.max(0, now.offsetLeft - line.offsetLeft - line.clientWidth + now.offsetWidth + 8);
    }

    function boardStep() {
      const slots = [0, 1, 2].map(i => state.flop[i]
        ? `<span class="flop-card">${cardsHTML([state.flop[i]])}</span>` : '<span class="flop-card empty">?</span>').join("");
      const change = state.flop.length ? '<button class="flop-clear" type="button" data-clear-flop>เปลี่ยน</button>' : "";
      return `<div class="step board"><div class="step-seat"><span>Flop</span></div>`
        + `<div class="step-opts"><span class="board-cards">${slots}</span>${change}</div></div>`;
    }

    // Fold the seat to act and everyone up to the ``count``th seat ahead.
    function foldAhead(count) {
      const path = [...state.path];
      let index = currentNode();
      for (let i = 0; i < count; i++) {
        const fold = data.nodes[index].options.findIndex(o => o.action === "fold");
        path.push(fold);
        index = data.nodes[index].options[fold].child;
      }
      return path;
    }

    function renderSpot(node) {
      const seat = data.seats[node.actor];
      const words = lineWords();
      $("spot-title").textContent = words.length ? `${seat} · หลัง ${words.join(", ")}` : `${seat} · ได้เป็นคนแรก (first in)`;
      const toCall = node.to_call > 0 ? ` · ต้องจ่าย ${fmt(node.to_call)}bb` : "";
      const stack = SHOW_STACK ? ` · stack ${fmt(node.behind[node.actor])}bb` : "";
      const used = boardCards().join("");
      const board = node.street !== 1 || !boardEntry() ? ""
        : state.exact ? ` · flop ${used}` : ` · แสดง flop ${used} แทน ${state.flop.join("")} ที่ยังไม่มีในคลัง`;
      $("spot-meta").textContent = `${data.label}${board} · pot ${fmt(node.pot)}bb${toCall}${stack}`;
    }

    function renderMatrix(cells, node) {
      const html = [];
      for (let key = 0; key < 169; key++) {
        const cell = cells[key];
        const row = Math.floor(key / 13), col = key % 13;
        const empty = cell.combos === 0;
        const selected = state.second === key;
        html.push(`<button class="cell${row === col ? " pair" : ""}${empty ? " empty" : ""}${selected ? " sel" : ""}" type="button" role="gridcell" data-key="${key}" ${empty ? 'aria-disabled="true"' : ""} aria-label="${cellName(key)}">`
          + `<span class="name">${cellName(key)}</span><span class="bars">${empty ? "" : barHTML(cell.freq, node, cell.combos, pickedAction())}</span></button>`);
      }
      $("matrix").innerHTML = html.join("");
      $("pick1-v").textContent = state.first === null ? "เลือก" : cellName(state.first);
      $("pick2-v").textContent = state.second === null ? (state.first === null ? "-" : "เลือก") : cellName(state.second);
      $("pick1").dataset.on = String(state.first === null);
      $("pick2").dataset.on = String(state.first !== null);
      $("pick2").disabled = state.first === null;
      $("step-hint").textContent = state.first === null ? "แตะช่องเพื่อเลือกไพ่สองใบแรก"
        : state.second === null ? "เลือกอีกสองใบ หรือแตะ สองใบแรก เพื่อเปลี่ยน" : "แตะช่องเดิมเพื่อยกเลิก";
    }

    function renderLegend(node) {
      $("legend").innerHTML = orderedSlots(node).map(k => {
        const option = node.options[k], label = optionLabel(node, option);
        return `<span><i style="background:${ACTION_COLOR[option.action]}"></i>${label.name}${label.amount ? ` <span class="mono">${label.amount}</span>` : ""}</span>`;
      }).join("");
    }

    function renderSummary(total, node) {
      const picked = pickedAction();
      const tiles = orderedSlots(node).map(k => {
        const option = node.options[k], label = optionLabel(node, option);
        const share = total.combos ? total.freq[k] / total.combos : 0;
        const name = `${label.name}${label.amount ? " " + label.amount : ""}`;
        return `<button class="tile tile-action" type="button" data-action="${k}" aria-pressed="${picked === k}" `
          + `title="${picked === k ? "กดอีกครั้งเพื่อดูทุกมือ" : `ดูเฉพาะมือที่มี ${name}`}" style="--c:${ACTION_COLOR[option.action]}"><span>${name}</span>`
          + `<b>${pct(share)}</b><small>${fmtCombos(total.freq[k])} combos</small></button>`;
      });
      tiles.push(`<div class="tile"><span>มือที่ตรงตัวกรอง</span><b>${pct(total.range ? total.combos / total.range : 0)}</b><small>${fmtCombos(total.combos)} / ${fmtCombos(total.range)}</small></div>`);
      $("tiles").innerHTML = tiles.join("");
      $("sum-bar").innerHTML = barHTML(total.freq, node, total.combos);
    }

    function cardsHTML(cards) {
      return cards.map(c => `<span class="s-${c[1]}">${c[0]}${SUIT_GLYPH[c[1]]}</span>`).join("");
    }

    function renderList(rows, node) {
      const slots = orderedSlots(node);
      $("list-head").innerHTML = `<tr><th>มือ</th><th class="hide-sm">ทรง</th><th class="hide-sm">${TIER_LABEL}</th><th class="num hide-sm">combos</th><th>สัดส่วน</th>`
        + slots.map(k => `<th class="num">${optionLabel(node, node.options[k]).name}</th>`).join("") + "</tr>";
      const picked = pickedAction();
      const aggressive = picked === null ? slots[0] : picked;
      rows.sort((p, q) => q.p[aggressive] - p.p[aggressive] || q.w - p.w);
      const shown = rows.slice(0, LIST_LIMIT);
      $("list").innerHTML = shown.map(({ c, p, w, cards }) => `<tr><td class="cards">${cardsHTML(cards)}</td>`
        + `<td class="shape hide-sm">${c.shape}</td><td class="tier hide-sm">${classes.tiers[c.tier]}</td>`
        + `<td class="num hide-sm">${Number.isInteger(w) ? w : w.toFixed(1)}</td><td><div class="bigbar">${barHTML(p, node, 1)}</div></td>`
        + slots.map(k => `<td class="num">${(p[k] * 100).toFixed(0)}%</td>`).join("") + "</tr>").join("");
      $("list-count").textContent = `${rows.length.toLocaleString("en-US")} แบบ · ดอกเป็นตัวอย่าง สลับดอกได้`;
      $("more").hidden = rows.length <= LIST_LIMIT;
      $("more").textContent = `แสดง ${LIST_LIMIT} แบบแรกตามความถี่ ${optionLabel(node, node.options[aggressive]).name} ใช้ matrix หรือช่องค้นเพื่อกรองให้แคบลง`;
      const base = state.first === null ? "มือทั้งหมด" : `มือที่มี ${cellName(state.first)}${state.second === null ? "" : " + " + cellName(state.second)}`;
      const title = picked === null ? base : `${base} · ที่ ${optionLabel(node, node.options[picked]).name} อย่างน้อย ${ACTION_MIN * 100}%`;
      $("list-title").textContent = title;
    }

    function renderFilters() {
      $("shapes").innerHTML = '<span class="label">ทรงดอก</span>' + SHAPES.map(([key, text]) =>
        `<button class="chip" type="button" data-shape="${key}" aria-pressed="${state.shape === key}">${text}</button>`).join("");
      $("tiers").setAttribute("aria-label", TIER_LABEL);
      $("tiers").innerHTML = `<span class="label">${TIER_LABEL}</span>` + [["-1", "ทั้งหมด"], ...classes.tiers.map((t, i) => [String(i), t])].map(([key, text]) =>
        `<button class="chip" type="button" data-tier="${key}" aria-pressed="${String(state.tier) === key}">${text}</button>`).join("");
    }

    let view = null;

    function renderNoBoard(node) {
      const loading = state.flop.length === 3;
      container.querySelector(".steps").hidden = true;  // the two-card hand picker has nothing to pick yet
      $("spot-title").textContent = loading ? "กำลังโหลด flop..." : `เลือก flop ทีละใบ (${state.flop.length}/3)`;
      $("spot-meta").textContent = `${data.label} · pot ${fmt(node.pot)}bb`;
      for (const id of ["legend", "tiles", "sum-bar", "list", "list-head"]) $(id).innerHTML = "";
      $("matrix").innerHTML = loading ? "" : "shdc".split("").map(suit => [...RANK_ORDER].reverse().map(rank => {
        const card = rank + suit, on = state.flop.includes(card);
        return `<button class="card-pick s-${suit}" type="button" data-card="${card}" aria-pressed="${on}">${rank}${SUIT_GLYPH[suit]}</button>`;
      }).join("")).join("");
      $("list-count").textContent = "";
      $("more").hidden = true;
    }

    function render() {
      const index = currentNode();
      const node = data.nodes[index];
      if (isFlop(index) && !(state.board && boards[state.board])) {
        view = { node, cells: [] };
        renderLine();
        renderNoBoard(node);
        renderFilters();
        saveHash();
        return;
      }
      container.querySelector(".steps").hidden = false;
      const agg = aggregate(isFlop(index) ? flopView(index) : preflopView(index), node.options.length);
      view = { node, cells: agg.cells };
      renderLine();
      renderSpot(node);
      renderMatrix(agg.cells, node);
      renderLegend(node);
      renderSummary(agg.total, node);
      renderList(agg.rows, node);
      renderFilters();
      saveHash();
    }

    // ---------- tooltip ----------
    function showTip(event, key) {
      const tip = $("tip");
      const cell = view.cells[key];
      if (!cell || cell.combos === 0) { tip.style.opacity = 0; return; }
      const node = view.node;
      const title = state.first === null ? cellName(key) : `${cellName(state.first)} + ${cellName(key)}`;
      tip.innerHTML = `<b>${title}</b> <span>${cell.combos.toLocaleString("en-US")} combos</span>`
        + orderedSlots(node).map(k => {
          const option = node.options[k], label = optionLabel(node, option);
          return `<div class="row"><i style="background:${ACTION_COLOR[option.action]}"></i>${label.name} ${(cell.freq[k] / cell.combos * 100).toFixed(1)}%</div>`;
        }).join("");
      const x = Math.min(event.clientX + 14, window.innerWidth - tip.offsetWidth - 8);
      const y = Math.min(event.clientY + 14, window.innerHeight - tip.offsetHeight - 8);
      tip.style.left = `${Math.max(8, x)}px`;
      tip.style.top = `${Math.max(8, y)}px`;
      tip.style.opacity = 1;
    }

    // ---------- state in the URL ----------
    function saveHash() {
      if (!options.hash) return;
      const parts = [`g=${state.game}`];
      if (state.path.length) parts.push(`l=${state.path.join(".")}`);
      if (state.first !== null) parts.push(`h=${state.first}${state.second !== null ? "." + state.second : ""}`);
      if (state.flop.length === 3) parts.push(`b=${state.flop.join("")}`);
      history.replaceState(null, "", "#" + parts.join("&"));
    }

    function readHash() {
      if (!options.hash) return;
      const params = new URLSearchParams(location.hash.slice(1));
      if (games.some(game => game.id === params.get("g"))) state.game = params.get("g");
      state.path = (params.get("l") || "").split(".").filter(Boolean).map(Number);
      const hand = (params.get("h") || "").split(".").filter(Boolean).map(Number);
      state.first = Number.isInteger(hand[0]) && hand[0] >= 0 && hand[0] < 169 ? hand[0] : null;
      state.second = state.first !== null && Number.isInteger(hand[1]) && hand[1] >= 0 && hand[1] < 169 ? hand[1] : null;
      const picked = (params.get("b") || "").match(/[2-9TJQKA][shdc]/g) || [];
      state.flop = picked.length === 3 && new Set(picked).size === 3 ? picked : [];
    }

    function validPath() {
      let index = 0;
      const kept = [];
      for (const slot of state.path) {
        const option = data.nodes[index].options[slot];
        if (!option || option.child < 0) break;
        kept.push(slot);
        index = option.child;
      }
      state.path = kept;
    }

    // ---------- events ----------
    async function selectGame(name) {
      state.game = name;
      $("spot-title").textContent = "กำลังโหลด...";
      renderGames();
      const loaded = await loadGame(name);
      data = loaded.raw;
      strategy = loaded.bytes;
      if (POST) attachPostflop(data, await loadPostflop());
      validPath();
      if (POST) setFlop(); else render();
    }

    if (options.gamesEl) options.gamesEl.addEventListener("click", event => {
      const button = event.target.closest("[data-game]");
      if (button && button.dataset.game !== state.game) {
        state.path = [];
        selectGame(button.dataset.game).catch(fail);
      }
    });

    $("line").addEventListener("click", event => {
      if (event.target.closest("[data-clear-flop]")) { state.flop = []; setFlop(); return; }
      const button = event.target.closest(".opt, [data-back], [data-ahead]");
      if (!button || button.disabled) return;
      if (button.dataset.back !== undefined) state.path = state.path.slice(0, Number(button.dataset.back));
      else if (button.dataset.ahead !== undefined) state.path = foldAhead(Number(button.dataset.ahead));
      else state.path = [...state.path.slice(0, Number(button.dataset.depth)), Number(button.dataset.slot)];
      render();
    });

    // Both Reset buttons (action line and filters) clear the line, the picked cells, the filters and
    // the searched hand; the game stays.
    function resetAll() {
      clearTimeout(typing);
      Object.assign(state, { path: [], first: null, second: null, shape: "all", tier: -1, query: "", action: null, board: null, flop: [], exact: true });
      $("search").value = "";
      render();
    }
    $("reset").addEventListener("click", resetAll);
    $("reset-filters").addEventListener("click", resetAll);

    $("matrix").addEventListener("click", event => {
      const pick = event.target.closest("[data-card]");
      if (pick) { pickFlopCard(pick.dataset.card); return; }
      const button = event.target.closest(".cell");
      if (!button || button.classList.contains("empty")) return;
      const key = Number(button.dataset.key);
      if (state.first === null) state.first = key;
      else if (state.second === key) state.second = null;
      else state.second = key;
      $("tip").style.opacity = 0;
      render();
    });
    $("matrix").addEventListener("pointermove", event => {
      const button = event.target.closest(".cell");
      if (button && event.pointerType === "mouse") showTip(event, Number(button.dataset.key));
      else $("tip").style.opacity = 0;
    });
    $("matrix").addEventListener("pointerleave", () => { $("tip").style.opacity = 0; });

    $("pick1").addEventListener("click", () => { state.first = null; state.second = null; render(); });
    $("pick2").addEventListener("click", () => { state.second = null; render(); });

    $("tiles").addEventListener("click", event => {
      const button = event.target.closest("[data-action]");
      if (!button) return;
      const slot = Number(button.dataset.action);
      state.action = pickedAction() === slot ? null : { node: currentNode(), slot };
      render();
    });

    $("shapes").addEventListener("click", event => {
      const button = event.target.closest("[data-shape]");
      if (button) { state.shape = button.dataset.shape; render(); }
    });
    $("tiers").addEventListener("click", event => {
      const button = event.target.closest("[data-tier]");
      if (button) { state.tier = Number(button.dataset.tier); render(); }
    });
    let typing = null;
    $("search").addEventListener("input", event => {
      clearTimeout(typing);
      typing = setTimeout(() => { state.query = event.target.value; render(); }, 150);
    });

    function fail(error) {
      $("spot-title").textContent = "โหลดข้อมูลไม่สำเร็จ ลองรีเฟรชหน้าอีกครั้ง";
      $("spot-meta").textContent = String(error.message || error);
    }

    // Show a solved game given directly (the final-table page); keeps the line when it still exists.
    function show(raw) {
      if (!classes) { pending = raw; return; }
      data = raw;
      strategy = decode(raw.strategy);
      validPath();
      render();
      if (wanted) { const spot = wanted; wanted = null; focus(spot); }
    }

    // Open the line where everyone folds to ``seat`` and search ``hand``.
    function focus({ seat, hand }) {
      if (!data) { wanted = { seat, hand }; return; }
      state.path = [];
      const target = data.seats.indexOf(seat);
      let index = 0;
      while (target >= 0 && data.nodes[index].actor !== target) {
        const fold = data.nodes[index].options.findIndex(o => o.action === "fold");
        if (fold < 0 || data.nodes[index].options[fold].child < 0) { state.path = []; break; }
        state.path.push(fold);
        index = data.nodes[index].options[fold].child;
      }
      if (hand) { state.query = hand; $("search").value = hand; }
      render();
    }

    readHash();
    renderGames();
    getJSON(options.classesUrl || "/static/plo-classes.json")
      .then(raw => {
        classes = Object.assign(prepareClasses(raw), { tiers: raw.tiers });
        if (pending) { const waiting = pending; pending = null; show(waiting); return null; }
        return games.length ? selectGame(state.game) : null;
      })
      .catch(fail);
    return { show, focus, fail };
  }

  return { mount };
})();
