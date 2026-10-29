// Midterm flashcards, web version. Same Leitner scheduling as quiz.py; progress lives in
// this browser's localStorage, one key per deck, so it never leaves the device.

const BASE = [8, 4, 2, 1, 0.5, 0.25];   // pull of each box
const GAP = [4, 10, 25, 60, 150, 400];  // cards shown before a box is "ready" again
const FIRST_TRY_BOX = 3, MASTERED = 4, COOLDOWN = 10;
const LETTERS = "abcd";

const app = document.getElementById("app");
let decks = [], deck = null, cards = [], prog = null, session = null, current = null, settings = null;

// ---------------------------------------------------------------- storage

const store = {
  get(key, fallback) {
    try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch { return fallback; }
  },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode: play without saving */ } },
  remove(key) { try { localStorage.removeItem(key); } catch { /* ignore */ } },
};
const progKey = k => `mq:${(decks.find(d => d.key === k) || {}).store || k}:progress`;
const setKey = k => `mq:${k}:settings`;
const emptyProg = () => ({ version: 1, turn: 0, recent: [], cards: {} });

// ---------------------------------------------------------------- cards

function unitOf(c) {            // "2", "2b", "10" …
  const [head, tail] = c.id.split("-");
  return head.slice(2) + (tail.startsWith("b") ? "b" : "");
}
function chnum(c) { return parseInt(c.id.split("-")[0].slice(2), 10); }
function courseOrder(a, b) {
  const ka = [chnum(a), a.id.split("-")[1].startsWith("b") ? 1 : 0, parseInt(a.id.split("-")[1].replace("b", ""), 10)];
  const kb = [chnum(b), b.id.split("-")[1].startsWith("b") ? 1 : 0, parseInt(b.id.split("-")[1].replace("b", ""), 10)];
  for (let i = 0; i < 3; i++) if (ka[i] !== kb[i]) return ka[i] - kb[i];
  return 0;
}
function units() {
  const seen = new Map();
  for (const c of [...cards].sort(courseOrder)) if (!seen.has(unitOf(c))) seen.set(unitOf(c), c.chapter);
  return [...seen.entries()];
}

// ---------------------------------------------------------------- scheduling (ported from quiz.py)

function topicWeights(pool) {
  const tally = {};
  for (const c of pool) {
    const st = prog.cards[c.id];
    if (!st) continue;
    const t = tally[c.topic] ||= [0, 0];
    t[0] += st.right; t[1] += st.right + st.wrong;
  }
  const w = {};
  for (const [topic, [r, n]] of Object.entries(tally)) if (n) w[topic] = 2 - r / n;
  return w;
}

function chapterWeights(pool) {
  if (!deck.share) return {};
  const groupOf = {};
  deck.share.forEach(([chs], i) => chs.forEach(ch => (groupOf[ch] = i)));
  const sizes = {};
  for (const c of pool) { const g = groupOf[chnum(c)]; if (g !== undefined) sizes[g] = (sizes[g] || 0) + 1; }
  const raw = {};
  deck.share.forEach(([chs, share], i) => { if (sizes[i]) chs.forEach(ch => (raw[ch] = share / sizes[i])); });
  const mean = pool.reduce((s, c) => s + (raw[chnum(c)] ?? 1), 0) / pool.length;
  const out = {};
  for (const [ch, w] of Object.entries(raw)) out[ch] = w / mean;
  return out;
}

function weightedChoice(items, weights) {
  const total = weights.reduce((a, b) => a + b, 0);
  if (total <= 0) return items[Math.floor(Math.random() * items.length)];
  let r = Math.random() * total;
  for (let i = 0; i < items.length; i++) { r -= weights[i]; if (r <= 0) return items[i]; }
  return items[items.length - 1];
}

function pick(pool) {
  const turn = prog.turn, states = prog.cards;
  const tw = topicWeights(pool), cw = settings.mix ? chapterWeights(pool) : {};
  const due = pool.filter(c => states[c.id] && states[c.id].box === 0 && turn - states[c.id].last >= Math.min(GAP[0], pool.length - 1));
  if (due.length && Math.random() < 0.6) return due.reduce((a, b) => (states[a.id].last <= states[b.id].last ? a : b));

  const recent = pool.length > 3 ? new Set(prog.recent.slice(-Math.min(COOLDOWN, Math.floor(pool.length / 3)))) : new Set();
  let avail = pool.filter(c => !recent.has(c.id));
  if (!avail.length) avail = pool;
  const fresh = avail.filter(c => !states[c.id]);
  const review = avail.filter(c => states[c.id]);

  const learning = pool.filter(c => states[c.id] && states[c.id].box <= 1).length;
  const pNew = learning < 15 ? 0.6 : learning < 30 ? 0.4 : 0.2;
  if (fresh.length && (!review.length || Math.random() < pNew)) {
    if (!settings.mix) return [...fresh].sort(courseOrder)[0];
    return weightedChoice(fresh, fresh.map(c => (cw[chnum(c)] ?? 1) * (tw[c.topic] ?? 1)));
  }
  return weightedChoice(review, review.map(c => {
    const st = states[c.id];
    const ready = Math.min(2, (turn - st.last) / GAP[st.box]);
    return BASE[st.box] * Math.max(ready, 0.02) * (cw[chnum(c)] ?? 1) * (tw[c.topic] ?? 1);
  }));
}

function record(card, right) {
  const st = prog.cards[card.id] ||= { box: 0, right: 0, wrong: 0, last: 0 };
  const first = st.right + st.wrong === 0;
  if (right) { st.right++; st.box = first ? FIRST_TRY_BOX : Math.min(BASE.length - 1, st.box + 1); }
  else { st.wrong++; st.box = 0; }
  st.last = prog.turn;
}

function statusTag(st) {
  if (!st) return `<span class="tag new">NEW</span>`;
  if (st.box === 0) return `<span class="tag missed">MISSED BEFORE</span>`;
  if (st.box >= MASTERED) return `<span class="tag mastered">MASTERED</span>`;
  return `<span class="tag review">REVIEW</span>`;
}

// ---------------------------------------------------------------- views

const esc = s => String(s).replace(/[&<>"]/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));
const pct = (a, b) => (b ? Math.round((100 * a) / b) : 0);
const unitLabel = u => `${deck.unit === "Ch." ? "Ch." : deck.unit} ${u}`;

function deckStats(d) {
  const p = store.get(progKey(d.key), emptyProg());
  const states = Object.values(p.cards);
  return { seen: states.length, mastered: states.filter(s => s.box >= MASTERED).length };
}

function home() {
  deck = null; current = null;
  app.innerHTML = `
    <h1>Midterm flashcards</h1>
    <p class="muted">Inha University in Tashkent · Fall 2026. Cards are written from the professors' own study guides.
    Your progress is saved in this browser only.</p>
    ${decks.map(d => {
      const s = deckStats(d);
      return `<button class="card deck" data-deck="${d.key}">
        <div class="top"><h2>${esc(d.title)}</h2><span class="meta">${d.count} cards</span></div>
        <div class="meta">${esc(d.subtitle)}</div>
        <div class="meta">${esc(d.exam)}</div>
        <div class="bar"><span style="width:${pct(s.seen, d.count)}%"></span></div>
        <div class="meta" style="margin-top:6px">${s.seen} seen · ${s.mastered} mastered</div>
      </button>`;
    }).join("")}
    <footer>Not official course material: unofficial study aid made by students, checked against each guide but it can still be wrong.
    Questions and fixes: <a href="https://github.com/kamol1dn/dlcv-midterm-quiz">GitHub</a>.</footer>`;
  app.querySelectorAll("[data-deck]").forEach(b => (b.onclick = () => openDeck(b.dataset.deck)));
  history.replaceState(null, "", location.pathname);
}

async function openDeck(key) {
  deck = decks.find(d => d.key === key);
  if (!deck) return home();
  app.innerHTML = `<p class="muted">Loading ${esc(deck.title)}…</p>`;
  cards = await (await fetch(`decks/${key}.json`)).json();
  prog = store.get(progKey(key), emptyProg());
  settings = { units: [], mix: false, missed: false, starred: true, ...store.get(setKey(key), {}) };  // ★ on by default
  location.hash = key;
  setup();
}

function setup() {
  current = null;
  const all = units();
  const states = prog.cards;
  const rows = all.map(([u, chapter]) => {
    const cs = cards.filter(c => unitOf(c) === u);
    const sts = cs.map(c => states[c.id]).filter(Boolean);
    const r = sts.reduce((a, s) => a + s.right, 0), n = sts.reduce((a, s) => a + s.right + s.wrong, 0);
    return `<tr><td>${esc(chapter)}</td>
      <td class="num">${cs.length}</td><td class="num">${sts.length}</td>
      <td class="num">${sts.filter(s => s.box >= MASTERED).length}</td><td class="num">${n ? pct(r, n) + "%" : "–"}</td></tr>`;
  }).join("");
  const missedCount = cards.filter(c => states[c.id] && states[c.id].box <= 1).length;
  const starCount = cards.filter(c => c.star).length;
  app.innerHTML = `
    <button class="btn link" id="back">← All decks</button>
    <h1>${esc(deck.title)}</h1>
    <p class="muted">${esc(deck.subtitle)} · ${esc(deck.exam)}</p>
    <div class="card">
      <h2>What to drill</h2>
      <p class="meta">Tap ${deck.unit === "Ch." ? "chapters" : deck.unit.toLowerCase() + "s"} to pick some, or leave all off for everything.</p>
      <div class="row">${all.map(([u]) => `<button class="chip" data-unit="${u}" aria-pressed="${settings.units.includes(u)}">${esc(unitLabel(u))}</button>`).join("")}</div>
      <div class="row" style="margin-top:14px">
        <button class="chip" id="order" aria-pressed="${!settings.mix}">In course order</button>
        <button class="chip" id="mix" aria-pressed="${settings.mix}">Random mix</button>
        <button class="chip" id="missed" aria-pressed="${settings.missed}">Only missed (${missedCount})</button>
        ${starCount ? `<button class="chip" id="starred" aria-pressed="${settings.starred}">★ Only prof-stressed (${starCount})</button>` : ""}
      </div>
      <p class="meta" style="margin-top:10px">Course order teaches from the first idea to the last. Random mix spreads cards by
      how much of the exam each part covers: best for the last drill before the exam.</p>
      <button class="btn primary" id="start" style="margin-top:4px">Start</button>
    </div>
    <div class="card">
      <h2>Progress</h2>
      <table><thead><tr><th></th><th class="num">cards</th><th class="num">seen</th><th class="num">mastered</th><th class="num">right</th></tr></thead>
      <tbody>${rows}</tbody></table>
      ${weakTopics()}
      <button class="btn link" id="reset" style="margin-top:8px">Reset progress for this deck</button>
    </div>`;
  app.querySelector("#back").onclick = home;
  app.querySelectorAll("[data-unit]").forEach(b => (b.onclick = () => {
    const u = b.dataset.unit;
    settings.units = settings.units.includes(u) ? settings.units.filter(x => x !== u) : [...settings.units, u];
    b.setAttribute("aria-pressed", settings.units.includes(u)); store.set(setKey(deck.key), settings);
  }));
  app.querySelector("#order").onclick = () => { settings.mix = false; store.set(setKey(deck.key), settings); setup(); };
  app.querySelector("#mix").onclick = () => { settings.mix = true; store.set(setKey(deck.key), settings); setup(); };
  app.querySelector("#missed").onclick = () => { settings.missed = !settings.missed; store.set(setKey(deck.key), settings); setup(); };
  app.querySelector("#starred")?.addEventListener("click", () => { settings.starred = !settings.starred; store.set(setKey(deck.key), settings); setup(); });
  app.querySelector("#start").onclick = start;
  app.querySelector("#reset").onclick = () => {
    if (confirm(`Wipe all progress for ${deck.title}? This can't be undone.`)) { prog = emptyProg(); store.remove(progKey(deck.key)); setup(); }
  };
}

function weakTopics() {
  const tw = topicWeights(cards), weak = [];
  for (const [topic, w] of Object.entries(tw)) {
    const tries = cards.filter(c => c.topic === topic && prog.cards[c.id])
      .reduce((a, c) => a + prog.cards[c.id].right + prog.cards[c.id].wrong, 0);
    if (tries >= 3 && w > 1) weak.push([w, topic]);
  }
  if (!weak.length) return "";
  weak.sort((a, b) => b[0] - a[0]);
  return `<p class="meta" style="margin:12px 0 4px">Weakest topics</p>` +
    weak.slice(0, 8).map(([w, t]) => `<div class="small">${100 - Math.round(100 * (w - 1))}% · ${esc(t)}</div>`).join("");
}

function poolNow() {
  let pool = settings.units.length ? cards.filter(c => settings.units.includes(unitOf(c))) : cards;
  if (settings.missed) pool = pool.filter(c => prog.cards[c.id] && prog.cards[c.id].box <= 1);
  if (settings.starred && cards.some(c => c.star)) pool = pool.filter(c => c.star);
  return pool;
}

function start() {
  if (!poolNow().length) { alert(settings.missed ? "Nothing missed here. Turn off \"Only missed\"." : "No cards for that choice."); return; }
  session = { n: 0, right: 0, masteredBefore: Object.values(prog.cards).filter(s => s.box >= MASTERED).length };
  next();
}

function next() {
  const pool = poolNow();
  if (!pool.length) return summary();
  const card = pick(pool);
  const order = [0, 1, 2, 3].sort(() => Math.random() - 0.5);
  current = { card, order, tag: statusTag(prog.cards[card.id]), done: false, before: prog.cards[card.id] ? { ...prog.cards[card.id] } : null };
  drawCard();
}

function drawCard(chosen = null) {
  const { card, order, tag, done } = current;
  const states = prog.cards;
  const seen = cards.filter(c => states[c.id]).length, mastered = cards.filter(c => states[c.id] && states[c.id].box >= MASTERED).length;
  const correctPos = order.indexOf(0);
  let verdict = "";
  if (done) {
    verdict = chosen === null ? `<div class="verdict show">Answer: ${LETTERS[correctPos]}) ${esc(card.choices[0])}</div>`
      : order[chosen] === 0 ? `<div class="verdict good">Correct</div>` : `<div class="verdict bad">Wrong</div>`;
  }
  app.innerHTML = `
    <div class="top"><button class="btn link" id="quit">← Stop</button><span class="meta">session ${session.n} · ${session.right} right</span></div>
    <div class="card">
      <div class="top"><span class="meta">${esc(card.chapter)} · ${esc(card.topic)}</span><span>${card.star ? `<span class="tag star" title="The professor stressed this in the lecture">★ PROF STRESSED</span> ` : ""}${tag}</span></div>
      <div class="question">${esc(card.q)}</div>
      ${order.map((idx, pos) => {
        let cls = "";
        if (done) cls = idx === 0 ? "right" : pos === chosen ? "wrong" : "dim";
        return `<button class="choice ${cls}" data-pos="${pos}" ${done ? "disabled" : ""}><span class="key">${LETTERS[pos]}</span><span>${esc(card.choices[idx])}</span></button>`;
      }).join("")}
      ${done ? `${verdict}<div class="why">${esc(card.why)}${card.source ? `<div class="meta" style="margin-top:6px">${esc(card.source)}</div>` : ""}${card.star_note ? `<div class="meta star-note">★ ${esc(card.star_note)}</div>` : ""}</div>
        <div class="row" style="margin-top:14px"><button class="btn primary" id="next">Next</button>
        ${chosen !== null && order[chosen] !== 0 ? `<button class="btn" id="typo">Mis-tap, I knew it</button>` : ""}</div>`
        : `<button class="btn" id="show" style="margin-top:6px">Don't know, show me</button>`}
      <div class="keys"><kbd>a</kbd>–<kbd>d</kbd> answer · <kbd>Enter</kbd> ${done ? "next" : "show"} ${done ? "· <kbd>k</kbd> mis-tap" : ""} · <kbd>Esc</kbd> stop</div>
    </div>
    <p class="meta">${seen}/${cards.length} seen · ${mastered} mastered</p>`;
  app.querySelector("#quit").onclick = summary;
  app.querySelectorAll(".choice:not(:disabled)").forEach(b => (b.onclick = () => answer(+b.dataset.pos)));
  app.querySelector("#show")?.addEventListener("click", () => answer(null));
  app.querySelector("#next")?.addEventListener("click", next);
  app.querySelector("#typo")?.addEventListener("click", typo);
  window.scrollTo({ top: 0 });
}

function answer(pos) {
  if (current.done) return;
  const right = pos !== null && current.order[pos] === 0;
  prog.turn++;
  prog.recent = [...prog.recent, current.card.id].slice(-50);
  record(current.card, right);
  store.set(progKey(deck.key), prog);
  session.n++; session.right += right;
  current.done = true; current.chosen = pos;
  drawCard(pos);
}

function typo() {
  const { card, before } = current;
  if (before) prog.cards[card.id] = before; else delete prog.cards[card.id];
  record(card, true);
  store.set(progKey(deck.key), prog);
  session.right++;
  next();
}

function summary() {
  if (!session || !session.n) { session = null; return setup(); }
  const mastered = Object.values(prog.cards).filter(s => s.box >= MASTERED).length;
  app.innerHTML = `
    <h1>Session done</h1>
    <div class="card">
      <p><b>${session.n}</b> cards · <b>${session.right}</b> right (${pct(session.right, session.n)}%)</p>
      <p class="muted">Mastered ${mastered}/${cards.length} (+${mastered - session.masteredBefore}). Saved on this device.</p>
      <div class="row"><button class="btn primary" id="again">Keep going</button><button class="btn" id="menu">Deck menu</button></div>
    </div>`;
  session = null;
  app.querySelector("#again").onclick = start;
  app.querySelector("#menu").onclick = setup;
}

document.addEventListener("keydown", e => {
  if (!current || e.ctrlKey || e.metaKey || e.altKey) return;
  const k = e.key.toLowerCase();
  if (k === "escape") return summary();
  if (!current.done) {
    const i = "abcd".indexOf(k) >= 0 ? "abcd".indexOf(k) : "1234".indexOf(k);
    if (i >= 0) answer(i);
    else if (k === "enter") { e.preventDefault(); answer(null); }
  } else if (k === "enter" || k === " ") { e.preventDefault(); next(); }
  else if (k === "k" && current.chosen !== null && current.order[current.chosen] !== 0) typo();
});

window.addEventListener("hashchange", () => { const k = location.hash.slice(1); if (k && (!deck || deck.key !== k)) openDeck(k); else if (!k) home(); });

(async () => {
  try {
    decks = await (await fetch("decks/index.json")).json();
  } catch {
    app.innerHTML = `<p>Couldn't load the decks. Check your connection and reload.</p>`;
    return;
  }
  const k = location.hash.slice(1);
  if (k && decks.some(d => d.key === k)) openDeck(k); else home();
})();
