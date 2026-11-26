/* World Knowledge Library — the reading room.
   Plain JavaScript, no build step. Every value placed into HTML goes through
   the `html` tagged template, which escapes it unless it is explicitly raw(). */
"use strict";

// ------------------------------------------------------------------ helpers
class Raw { constructor(s) { this.s = s; } toString() { return this.s; } }
const raw = (s) => new Raw(s);
const unesc = (s) => s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&");
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const renderVal = (v) => v == null || v === false ? "" : v instanceof Raw ? v.s : Array.isArray(v) ? v.map(renderVal).join("") : esc(v);
function html(strings, ...vals) {
  let out = "";
  strings.forEach((s, i) => { out += s; if (i < vals.length) out += renderVal(vals[i]); });
  return raw(out);
}
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const view = $("#view");
const debounce = (fn, ms = 220) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
const plural = (n, one, many = one + "s") => `${n.toLocaleString()} ${n === 1 ? one : many}`;
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};

/* Navigation. The app routes on the URL hash. A standalone demo
   (window.WKL_DEMO, set by demo-backend.js) built for a host that frames the
   page and keeps the address bar to itself uses routing "memory" instead.
   A demo hosted as its own site (GitHub Pages) uses the hash like the app. */
const DEMO = !!window.WKL_DEMO;
const MEMORY_NAV = DEMO && window.WKL_DEMO.routing === "memory";
const nav = {
  memory: "#/",
  get hash() { return MEMORY_NAV ? this.memory : location.hash; },
  /** Change the address without visiting it (keeps a view's state shareable). */
  set(h) { if (MEMORY_NAV) this.memory = h; else history.replaceState(null, "", h); },
  /** Visit a route. */
  go(h, { replace = false } = {}) {
    if (MEMORY_NAV) { this.memory = h; router(); }
    else if (replace) location.replace(h);
    else location.hash = h;
  },
};
const state = { meta: null, stats: null, wings: [], dirty: false, lastHash: nav.hash };

async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch { /* empty */ }
  if (!res.ok) throw new Error((data && data.error) || `The library answered ${res.status}`);
  return data;
}

function toast(message, { error = false, action, actionLabel } = {}) {
  const el = document.createElement("div");
  el.className = "toast" + (error ? " error" : "");
  el.textContent = message;
  if (action) {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = actionLabel;
    b.addEventListener("click", () => { action(); el.remove(); });
    el.append(b);
  }
  $("#toasts").append(el);
  setTimeout(() => el.remove(), error ? 6000 : 4200);
}
const fail = (e) => toast(e.message || String(e), { error: true });

function confirmAction(title, body, yes, no = "Keep it") {
  const dlg = $("#confirm");
  $("#confirm-title").textContent = title;
  $("#confirm-body").textContent = body;
  $("#confirm-yes").textContent = yes;
  $("#confirm-no").textContent = no;
  return new Promise((resolve) => {
    dlg.addEventListener("close", () => resolve(dlg.returnValue === "yes"), { once: true });
    dlg.returnValue = "";
    dlg.showModal();
  });
}

function kindOf(id) { return (state.meta?.kinds || []).find((k) => k.id === id) || { id, label: id, glyph: "❖", mark: "MS" }; }
function statusOf(id) { return (state.meta?.statuses || []).find((s) => s.id === id) || { id, label: id }; }
const sillybos = (s) => html`<span class="sillybos" data-kind="${s.kind}" title="${kindOf(s.kind).label}">${s.call_number}</span>`;
const statusPill = (id) => html`<span class="status" data-status="${id}">${statusOf(id).label}</span>`;
const stars = (n) => n ? html`<span class="stars" aria-label="${n} of 5">${"★".repeat(n)}</span>` : "";
const tagLinks = (tags) => tags.map((t) => html`<a class="tag" href="#/pinakes?tag=${encodeURIComponent(t)}">${t}</a>`);

function when(isoStr) {
  if (!isoStr) return "";
  const d = new Date(isoStr), now = new Date();
  const days = Math.round((now - d) / 86400000);
  if (Math.abs(days) < 1) return "today";
  if (days === 1) return "yesterday";
  if (days === -1) return "tomorrow";
  if (days > 1 && days < 30) return `${days} days ago`;
  if (days < -1 && days > -30) return `in ${-days} days`;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

const isUrl = (s) => /^(https?:\/\/|www\.)\S+$/i.test(s.trim());
const highlight = (s) => raw(esc(s || "").replace(/\x02/g, "<mark>").replace(/\x03/g, "</mark>"));

// ---------------------------------------------------------------- markdown
/* A small, safe Markdown renderer: headings, emphasis, lists, task lists,
   quotes, code, tables, links, images and [[wiki links]]. */
function safeUrl(u) {
  u = u.trim().replace(/&amp;/g, "&");
  if (/^(https?:|mailto:|#|\/|\.\/)/i.test(u) || !/^[a-z][\w+.-]*:/i.test(u)) return esc(u);
  return "#";
}
function inline(text, links) {
  return text.split(/(`[^`\n]+`)/).map((part, i) => {
    if (i % 2) return `<code>${esc(part.slice(1, -1))}</code>`;
    const keep = [];
    const hold = (s) => `\u0000${keep.push(s) - 1}\u0000`;
    let s = esc(part);
    s = s.replace(/\[\[([^\[\]|#]+?)(#[^\[\]|]*)?(?:\|([^\[\]]+))?\]\]/g, (_, target, _a, alias) => {
      const t = target.trim(), label = (alias || t).trim();
      const hit = links[unesc(t).toLowerCase()];
      if (hit) return hold(`<a class="wikilink" href="#/scroll/${hit.id}" title="${hit.call_number}">${label}</a>`);
      return hold(`<a class="unwritten" href="#/new?title=${encodeURIComponent(unesc(t))}" title="Not written yet — write it">${label}</a>`);
    });
    s = s.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (_, alt, url) => hold(`<img alt="${alt}" src="${safeUrl(url)}" loading="lazy">`));
    s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, label, url) => hold(`<a href="${safeUrl(url)}" target="_blank" rel="noopener noreferrer">${label}</a>`));
    s = s.replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, (_, pre, url) => pre + hold(`<a href="${safeUrl(url)}" target="_blank" rel="noopener noreferrer">${url}</a>`));
    s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/__([^_]+)__/g, "<strong>$1</strong>");
    s = s.replace(/(^|[^*\w])\*([^*\s][^*]*?)\*(?!\*)/g, "$1<em>$2</em>").replace(/(^|[^_\w])_([^_\s][^_]*?)_(?![_\w])/g, "$1<em>$2</em>");
    s = s.replace(/~~([^~]+)~~/g, "<del>$1</del>").replace(/==([^=]+)==/g, "<mark>$1</mark>");
    return s.replace(/\u0000(\d+)\u0000/g, (_, n) => keep[+n]);
  }).join("");
}
const BLOCK_START = /^(#{1,6}\s|>|```|\s*([-*+]|\d+[.)])\s+|(\*{3,}|-{3,}|_{3,})\s*$)/;
function md(src, links = {}) {
  const lines = (src || "").replace(/\r\n?/g, "\n").split("\n");
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    let m;
    if (/^\s*$/.test(line)) { i++; continue; }
    if (/^```/.test(line)) {
      const body = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) body.push(lines[i++]);
      i++;
      out.push(`<pre><code>${esc(body.join("\n"))}</code></pre>`);
      continue;
    }
    if ((m = line.match(/^(#{1,6})\s+(.*?)\s*#*\s*$/))) { const l = Math.min(m[1].length + 1, 6); out.push(`<h${l}>${inline(m[2], links)}</h${l}>`); i++; continue; }
    if (/^(\*{3,}|-{3,}|_{3,})\s*$/.test(line)) { out.push("<hr>"); i++; continue; }
    if (/^>/.test(line)) {
      const body = [];
      while (i < lines.length && /^>/.test(lines[i])) body.push(lines[i++].replace(/^>\s?/, ""));
      out.push(`<blockquote>${md(body.join("\n"), links)}</blockquote>`);
      continue;
    }
    if ((m = line.match(/^(\s*)([-*+]|\d+[.)])\s+/))) {
      const ordered = /\d/.test(m[2]);
      const base = m[1].length;
      const items = [];
      while (i < lines.length) {
        const l = lines[i];
        const im = l.match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/);
        if (im && im[1].length <= base) { items.push([im[3]]); i++; continue; }
        if (items.length && (/^\s{2,}\S/.test(l) || (im && im[1].length > base))) { items[items.length - 1].push(l.slice(Math.min(base + 2, l.search(/\S/)))); i++; continue; }
        break;
      }
      const lis = items.map(([first, ...rest]) => {
        let head = first, box = "";
        const task = head.match(/^\[([ xX])\]\s+(.*)$/);
        if (task) { box = `<input type="checkbox" disabled${task[1] !== " " ? " checked" : ""}>`; head = task[2]; }
        const sub = rest.length ? md(rest.join("\n"), links) : "";
        return `<li>${box}${inline(head, links)}${sub}</li>`;
      }).join("");
      out.push(ordered ? `<ol>${lis}</ol>` : `<ul>${lis}</ul>`);
      continue;
    }
    if (line.includes("|") && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(lines[i + 1])) {
      const cells = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => inline(c.trim(), links));
      const head = cells(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) rows.push(cells(lines[i++]));
      out.push(`<table><thead><tr>${head.map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table>`);
      continue;
    }
    const para = [];
    while (i < lines.length && lines[i].trim() && (para.length === 0 || !BLOCK_START.test(lines[i]))) para.push(lines[i++]);
    out.push(`<p>${para.map((l) => inline(l.replace(/\s{2,}$/, ""), links) + (/\s{2,}$/.test(l) ? "<br>" : "")).join(" ")}</p>`);
  }
  return out.join("\n");
}

// ---------------------------------------------------------------- word diff
function wordDiff(a, b) {
  const A = (a || "").split(/(\s+)/), B = (b || "").split(/(\s+)/);
  if (A.length * B.length > 4e6) return html`<del>${a}</del><ins>${b}</ins>`;
  const n = A.length, m = B.length;
  const dp = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
    dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  let out = "", i = 0, j = 0;
  while (i < n && j < m) {
    if (A[i] === B[j]) { out += esc(A[i]); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) out += `<del>${esc(A[i++])}</del>`;
    else out += `<ins>${esc(B[j++])}</ins>`;
  }
  while (i < n) out += `<del>${esc(A[i++])}</del>`;
  while (j < m) out += `<ins>${esc(B[j++])}</ins>`;
  return raw(out.replace(/<\/del><del>/g, "").replace(/<\/ins><ins>/g, ""));
}

// ---------------------------------------------------------------- shell
async function refreshStats() {
  try {
    state.stats = await api("GET", "/api/stats");
    const s = state.stats;
    const inbox = s.by_status.inbox || 0;
    $('[data-count="inbox"]').textContent = inbox || "";
    $('[data-count="scrolls"]').textContent = s.scrolls || "";
    const due = $('[data-count="due"]');
    due.textContent = s.due || "";
    due.className = s.due ? "count-due" : "";
    due.title = s.due ? `${plural(s.due, "scroll")} due for review` : "";
  } catch (e) { /* the view will report */ }
}
async function refreshWings() { state.wings = await api("GET", "/api/wings"); }

function setTheme(theme) {
  if (theme) document.documentElement.dataset.theme = theme; else delete document.documentElement.dataset.theme;
  const dark = theme ? theme === "dark" : !matchMedia("(prefers-color-scheme: light)").matches;
  $("#theme-toggle").textContent = dark ? "Switch to light reading" : "Switch to night reading";
  $("#theme-toggle").dataset.next = dark ? "light" : "dark";
}

function setNav(name) {
  $$("#nav a").forEach((a) => { if (a.dataset.nav === name) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
  $("#rail").classList.remove("open");
  $("#menu-btn").setAttribute("aria-expanded", "false");
}

function mount(content, { narrow = false } = {}) {
  view.className = "view" + (narrow ? " view-narrow" : "");
  view.innerHTML = renderVal(content);
}

// ------------------------------------------------------------------ router
const routes = [
  [/^$/, viewAtrium, "atrium"],
  [/^harbor$/, viewHarbor, "harbor"],
  [/^pinakes$/, viewPinakes, "pinakes"],
  [/^scroll\/(\d+)$/, viewScroll, "pinakes"],
  [/^scroll\/(\d+)\/edit$/, (id) => viewEditor(+id), "pinakes"],
  [/^new$/, (params) => viewEditor(null, params), ""],
  [/^title\/(.+)$/, viewByTitle, "pinakes"],
  [/^pharos$/, viewPharos, "pharos"],
  [/^constellation$/, viewConstellation, "constellation"],
  [/^wings$/, viewWings, "wings"],
  [/^serapeum$/, viewSerapeum, "serapeum"],
];
let teardown = null;
function parseHash() {
  const h = nav.hash.replace(/^#\/?/, "");
  const [path, qs = ""] = h.split("?");
  return { path: decodeURIComponent(path), params: new URLSearchParams(qs) };
}
async function router() {
  if (state.dirty && nav.hash !== state.lastHash) {
    const target = nav.hash;
    nav.set(state.lastHash || "#/");
    const leave = await confirmAction("Leave without saving?", "Your changes to this scroll will be lost.",
      "Leave without saving", "Keep editing");
    if (!leave) return;
    state.dirty = false;
    nav.set(target);
  }
  state.lastHash = nav.hash;
  if (teardown) { teardown(); teardown = null; }
  const { path, params } = parseHash();
  for (const [re, fn, nav] of routes) {
    const m = path.match(re);
    if (!m) continue;
    setNav(nav);
    try {
      await fn(...m.slice(1), params);
    } catch (e) {
      mount(html`<div class="empty"><h1>This shelf could not be reached</h1><p>${e.message}</p><a class="btn" href="#/">Return to the Atrium</a></div>`);
    }
    if (!params.has("keepfocus")) view.focus({ preventScroll: true });
    window.scrollTo(0, 0);
    return;
  }
  mount(html`<div class="empty"><h1>No such room</h1><p>There is nothing at this address.</p><a class="btn" href="#/">Return to the Atrium</a></div>`);
}

// --------------------------------------------------------------- shared UI
function scrollRow(s, { showExcerpt = true } = {}) {
  return html`<li><a class="scroll-row" href="#/scroll/${s.id}">
    ${sillybos(s)}
    <span><span class="title">${s.title}</span>${s.author ? html` <span class="by">— ${s.author}</span>` : ""}</span>
    <span class="side">${statusPill(s.status)}${stars(s.rating)}</span>
    ${showExcerpt && s.excerpt ? html`<span class="excerpt">${highlight(s.excerpt)}</span>` : ""}
  </a></li>`;
}

async function capture(text) {
  text = text.trim();
  if (!text) return null;
  if (isUrl(text)) {
    const url = /^https?:/i.test(text) ? text : "https://" + text;
    toast("Reading the page…");
    const info = await api("POST", "/api/harbor/fetch", { url });
    return api("POST", "/api/scrolls", {
      title: info.title || url, kind: info.kind, status: "inbox", source_url: info.url,
      author: info.author, summary: info.summary,
    });
  }
  const firstLine = text.split("\n")[0];
  const title = firstLine.length > 90 ? firstLine.slice(0, 87).replace(/\s+\S*$/, "") + "…" : firstLine;
  return api("POST", "/api/scrolls", { title, kind: "idea", status: "inbox", content: text === title ? "" : text });
}

function captureForm(id) {
  return html`<form class="capture" id="${id}">
    <label class="sr-only" for="${id}-input">Paste a link or jot a thought</label>
    <input id="${id}-input" autocomplete="off" placeholder="Paste a link or jot a thought, then press Enter">
    <button class="btn btn-primary" type="submit">Dock in the Harbor</button>
    <span class="hint">Links are read for their title, author and description. Everything lands in the Harbor until you catalogue it.</span>
  </form>`;
}
function wireCapture(id, after) {
  $("#" + id).addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const input = $("#" + id + "-input");
    const btn = ev.target.querySelector("button");
    btn.disabled = true;
    try {
      const s = await capture(input.value);
      if (s) {
        input.value = "";
        toast(`Docked “${s.title}” in the Harbor`, { action: () => nav.go(`#/scroll/${s.id}`), actionLabel: "Open" });
        await refreshStats();
        after && after(s);
      }
    } catch (e) { fail(e); } finally { btn.disabled = false; }
  });
}

function heatmap(activity) {
  const cells = [];
  const today = new Date();
  const start = new Date(today);
  start.setDate(start.getDate() - 364 - start.getDay());
  const max = Math.max(1, ...Object.values(activity));
  for (let d = new Date(start); d <= today; d.setDate(d.getDate() + 1)) {
    const key = d.toISOString().slice(0, 10);
    const n = activity[key] || 0;
    const l = n ? Math.min(4, Math.ceil((n / max) * 4)) : 0;
    cells.push(html`<span data-l="${l}" title="${key}: ${plural(n, "act")} of tending"></span>`);
  }
  return html`<div class="heat" role="img" aria-label="Activity over the past year">${cells}</div>`;
}

// ----------------------------------------------------------------- atrium
async function viewAtrium() {
  const [stats, recent, due, pick] = await Promise.all([
    api("GET", "/api/stats"), api("GET", "/api/scrolls?sort=updated&limit=8"),
    api("GET", "/api/pharos?limit=5"), api("GET", "/api/random?status=done"),
  ]);
  state.stats = stats;
  if (!stats.scrolls) {
    mount(html`
      <div class="atrium-head"><div>
        <h1>The shelves are waiting</h1>
        <p class="lede">Alexandria set out to hold a copy of every book in the known world. This library holds
        what <em>you</em> read, watch, learn and think, and keeps it alive by linking and revisiting it.</p>
      </div></div>
      ${captureForm("cap")}
      <div class="empty" style="padding-top:0">
        <p>Start by pasting a link above, write your first scroll, or shelve the founding collection: a dozen
        linked scrolls about the Library of Alexandria to explore the rooms with.</p>
        <div class="row"><a class="btn btn-primary" href="#/new">Write a scroll</a>
        <button class="btn" id="found" type="button">Shelve the founding collection</button></div>
      </div>`, { narrow: true });
    wireCapture("cap", () => router());
    $("#found").addEventListener("click", async () => {
      try { const r = await api("POST", "/api/founding"); toast(`Shelved ${plural(r.added, "founding scroll")}`); await Promise.all([refreshStats(), refreshWings()]); router(); } catch (e) { fail(e); }
    });
    return;
  }
  const census = html`<b>${stats.scrolls.toLocaleString()}</b> ${stats.scrolls === 1 ? "scroll" : "scrolls"} on the shelves,
    holding <b>${stats.words.toLocaleString()}</b> words and <b>${stats.links.toLocaleString()}</b> links.
    ${stats.by_status.inbox ? html`<a href="#/harbor">${plural(stats.by_status.inbox, "arrival")}</a> wait in the Harbor.` : ""}
    ${stats.due ? html`The Pharos has <a href="#/pharos">${plural(stats.due, "scroll")}</a> for you to revisit.` : ""}`;
  mount(html`
    <div class="atrium-head"><div>
      <h1>The Atrium</h1>
      <p class="census">${census}</p>
    </div></div>
    ${captureForm("cap")}
    <div class="atrium-grid">
      <div>
        <section>
          <div class="section-head"><h2>Recently tended</h2><a href="#/pinakes?sort=updated">The whole catalogue</a></div>
          <ul class="shelf">${recent.results.map((s) => scrollRow(s, { showExcerpt: false }))}</ul>
        </section>
        <section>
          <div class="section-head"><h2>A year of tending</h2><span class="muted">${Object.keys(stats.activity).length} active days</span></div>
          ${heatmap(stats.activity)}
        </section>
      </div>
      <div>
        ${pick ? html`<section class="serendipity">
          <div class="row">${sillybos(pick)}<span class="muted">From the shelves, at random</span></div>
          <a class="title" href="#/scroll/${pick.id}">${pick.title}</a>
          ${pick.summary ? html`<p>${pick.summary}</p>` : ""}
          <button class="btn btn-s" id="another" type="button">Pull another</button>
        </section>` : ""}
        <section>
          <div class="section-head"><h2>At the Pharos</h2>${due.length ? html`<a href="#/pharos">Begin review</a>` : ""}</div>
          ${due.length ? html`<ul class="shelf">${due.map((s) => scrollRow(s, { showExcerpt: false }))}</ul>`
            : html`<p class="soft">Nothing is due. ${stats.remembered ? `${plural(stats.remembered, "scroll")} kept in memory.` : "Ask the Pharos to keep a scroll alive from its page."}</p>`}
        </section>
        ${stats.top_tags.length ? html`<section>
          <div class="section-head"><h2>Most-used tags</h2></div>
          <div class="chips">${stats.top_tags.slice(0, 12).map((t) => html`<a class="chip" href="#/pinakes?tag=${encodeURIComponent(t.name)}">${t.name} <span class="muted">${t.count}</span></a>`)}</div>
        </section>` : ""}
      </div>
    </div>`);
  wireCapture("cap", () => router());
  const heat = $(".heat"); if (heat) heat.scrollLeft = heat.scrollWidth;
  $("#another")?.addEventListener("click", () => router());
}

// ----------------------------------------------------------------- harbor
async function viewHarbor() {
  const res = await api("GET", "/api/scrolls?status=inbox&sort=created&limit=200");
  mount(html`
    <h1>The Harbor</h1>
    <p class="lede">New arrivals dock here. Catalogue each one: queue it for later, start studying it, or shelve it as done.</p>
    <div style="margin-top:22px">${captureForm("hcap")}</div>
    ${res.results.length ? html`<ul class="shelf" id="harbor-list">${res.results.map((s) => html`
      <li data-id="${s.id}"><div class="scroll-row">
        ${sillybos(s)}
        <span><a class="title" href="#/scroll/${s.id}" style="color:inherit;text-decoration:none">${s.title}</a>
          ${s.source_url ? html`<br><a class="muted" href="${safeUrl(s.source_url)}" target="_blank" rel="noopener noreferrer" style="font-size:13px">${s.source_url.replace(/^https?:\/\//, "").slice(0, 70)}</a>` : ""}</span>
        <span class="side">${when(s.created_at)}</span>
        ${s.excerpt ? html`<span class="excerpt">${highlight(s.excerpt)}</span>` : ""}
        <span class="tags row" style="margin-top:6px">
          <button class="btn btn-s" data-move="queued">Queue for later</button>
          <button class="btn btn-s" data-move="active">Start studying</button>
          <button class="btn btn-s" data-move="done">Shelve as done</button>
          <a class="btn btn-s btn-quiet" href="#/scroll/${s.id}/edit">Catalogue in full</a>
        </span>
      </div></li>`)}</ul>`
      : html`<div class="empty">The Harbor is calm — every arrival has been catalogued. Paste a link above when something new comes in.</div>`}`, { narrow: true });
  wireCapture("hcap", () => router());
  $("#harbor-list")?.addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-move]");
    if (!btn) return;
    const li = btn.closest("li");
    try {
      await api("PATCH", `/api/scrolls/${li.dataset.id}`, { status: btn.dataset.move });
      li.remove();
      toast(`Moved to ${statusOf(btn.dataset.move).label}`);
      refreshStats();
      if (!$("#harbor-list li")) router();
    } catch (e) { fail(e); }
  });
}

// ---------------------------------------------------------------- pinakes
async function viewPinakes(params) {
  if (!state.wings.length) await refreshWings();
  const tags = await api("GET", "/api/tags");
  const p = Object.fromEntries(params.entries());
  const q = p.q || "";
  $("#global-search").value = q;
  const opt = (value, label, current) => html`<option value="${value}" ${current === value ? raw("selected") : ""}>${label}</option>`;
  mount(html`
    <h1>The Pinakes</h1>
    <p class="lede">The catalogue of everything on the shelves. Search words or phrases, or narrow with <code>tag:</code>, <code>kind:</code>, <code>status:</code>, <code>wing:</code>, <code>author:</code> and <code>is:orphan</code>.</p>
    <form class="filters" id="filters">
      <label class="sr-only" for="pq">Search</label>
      <input id="pq" type="search" name="q" value="${q}" placeholder="Search the catalogue" autocomplete="off">
      <div class="chips" role="group" aria-label="Kind">
        ${state.meta.kinds.map((k) => html`<button type="button" class="chip" data-kind="${k.id}" aria-pressed="${p.kind === k.id}"><span class="dot"></span>${k.label}</button>`)}
      </div>
      <div class="row">
        <select name="status" aria-label="Status">${opt("", "Any status", p.status || "")}${state.meta.statuses.map((s) => opt(s.id, s.label, p.status))}</select>
        <select name="wing" aria-label="Wing">${opt("", "Every wing", p.wing || "")}${state.wings.map((w) => opt(String(w.id), w.name, p.wing))}</select>
        <select name="tag" aria-label="Tag">${opt("", "Any tag", p.tag || "")}${tags.map((t) => opt(t.name, `#${t.name} (${t.count})`, p.tag))}</select>
        <select name="sort" aria-label="Order">${[["", q ? "Best match" : "Recently tended"], ["created", "Newest arrivals"], ["oldest", "Oldest arrivals"], ["title", "Title A–Z"], ["rating", "Highest rated"]].map(([v, l]) => opt(v, l, p.sort || ""))}</select>
      </div>
    </form>
    <p class="result-count" id="count" aria-live="polite"></p>
    <ul class="shelf" id="results"></ul>
    <div class="row" style="margin-top:16px"><button class="btn" id="more" type="button" hidden>Show more</button></div>`);
  const form = $("#filters");
  let kind = p.kind || "";
  let offset = 0;
  const current = () => {
    const fd = new FormData(form);
    const out = new URLSearchParams();
    for (const [k, v] of fd) if (v) out.set(k, v);
    if (kind) out.set("kind", kind);
    return out;
  };
  const load = async (append = false) => {
    const qs = current();
    if (!append) { offset = 0; nav.set(`#/pinakes${qs.toString() ? "?" + qs : ""}`); state.lastHash = nav.hash; }
    qs.set("limit", "40"); qs.set("offset", String(offset));
    try {
      const res = await api("GET", `/api/scrolls?${qs}`);
      const list = $("#results");
      if (!list) return;
      const rows = res.results.map((s) => scrollRow(s)).map(renderVal).join("");
      if (append) list.insertAdjacentHTML("beforeend", rows); else list.innerHTML = rows;
      offset += res.results.length;
      $("#count").textContent = res.total ? `${plural(res.total, "scroll")}${res.total > offset ? `, showing ${offset}` : ""}` : "";
      if (!res.total) list.innerHTML = renderVal(html`<li class="empty">Nothing on the shelves matches. ${current().get("q") ? html`<a href="#/new?title=${encodeURIComponent(current().get("q"))}">Write a scroll called “${current().get("q")}”</a>` : ""}</li>`);
      $("#more").hidden = offset >= res.total;
    } catch (e) { $("#count").textContent = e.message; }
  };
  form.addEventListener("input", debounce(() => load()));
  form.addEventListener("change", () => load());
  form.addEventListener("submit", (e) => { e.preventDefault(); load(); });
  $$(".chip[data-kind]", form).forEach((b) => b.addEventListener("click", () => {
    kind = kind === b.dataset.kind ? "" : b.dataset.kind;
    $$(".chip[data-kind]", form).forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.kind === kind)));
    load();
  }));
  $("#more").addEventListener("click", () => load(true));
  await load();
  if (params.has("focus")) $("#pq").focus();
}

// ----------------------------------------------------------------- scroll
async function viewByTitle(title) {
  const res = await api("GET", `/api/titles?q=${encodeURIComponent(title)}&limit=1`);
  if (res.length && res[0].title.toLowerCase() === title.toLowerCase()) nav.go(`#/scroll/${res[0].id}`, { replace: true });
  else nav.go(`#/new?title=${encodeURIComponent(title)}`, { replace: true });
}

async function viewScroll(id) {
  const s = await api("GET", `/api/scrolls/${id}`);
  document.title = `${s.title} — World Knowledge Library`;
  const links = Object.fromEntries(s.outlinks.map((l) => [l.title.toLowerCase(), l]));
  const kind = kindOf(s.kind);
  const linkList = (items) => html`<ul class="linklist">${items.map((l) => html`<li><a href="#/scroll/${l.id}" data-kind="${l.kind}">${l.title}</a></li>`)}</ul>`;
  const p = s.pharos;
  mount(html`
    <div class="scroll-layout">
      <article>
        <header class="scroll-head">
          <div class="row">${sillybos(s)}<span class="muted">${kind.glyph} ${kind.label}${s.wing ? html` in the <a href="#/pinakes?wing=${s.wing.id}">${s.wing.name}</a> wing` : ""}</span></div>
          <h1>${s.title}</h1>
          ${s.author ? html`<p class="byline">by ${s.author}</p>` : ""}
          <div class="row" style="margin-top:16px">
            <a class="btn" href="#/scroll/${s.id}/edit">Edit</a>
            ${s.source_url ? html`<a class="btn btn-quiet" href="${safeUrl(s.source_url)}" target="_blank" rel="noopener noreferrer">Open the source</a>` : ""}
            <button class="btn btn-quiet btn-danger" id="burn" type="button">Remove</button>
          </div>
        </header>
        ${s.summary ? html`<p class="epigraph">${s.summary}</p>` : ""}
        <div class="prose">${s.content ? raw(md(s.content, links)) : html`<p class="muted">This scroll has no body yet. <a href="#/scroll/${s.id}/edit">Write it.</a></p>`}</div>

        <section class="marginalia" aria-labelledby="mh">
          <h2 id="mh">Marginalia</h2>
          ${s.marginalia.length ? "" : html`<p class="soft">Notes in the margin: highlights, questions and insights about this scroll.</p>`}
          <ol id="mlist">${s.marginalia.map((m) => html`<li data-kind="${m.kind}">
            <div class="stack" style="gap:6px">
              <span class="m-kind">${m.kind[0].toUpperCase() + m.kind.slice(1)}, ${when(m.created_at)}</span>
              ${m.quote ? html`<blockquote>“${m.quote}”</blockquote>` : ""}
              ${m.body ? html`<div class="m-body">${raw(inline(m.body, links))}</div>` : ""}
            </div>
            <button class="btn btn-quiet btn-s" data-del-m="${m.id}" aria-label="Erase this note">Erase</button>
          </li>`)}</ol>
          <form id="mform">
            <div class="row">
              <label class="sr-only" for="mkind">Kind of note</label>
              <select id="mkind" name="kind" style="width:auto">${state.meta.marginalia_kinds.map((k) => html`<option value="${k}">${k[0].toUpperCase() + k.slice(1)}</option>`)}</select>
            </div>
            <label class="sr-only" for="mquote">Passage</label>
            <input id="mquote" name="quote" placeholder="The passage it refers to (optional)">
            <label class="sr-only" for="mbody">Note</label>
            <textarea id="mbody" name="body" rows="3" placeholder="Write in the margin…"></textarea>
            <div><button class="btn" type="submit">Add to the margin</button></div>
          </form>
        </section>

        <section class="marginalia" aria-labelledby="ph" id="palimpsest" ${s.revisions ? "" : raw("hidden")}>
          <h2 id="ph">Palimpsest</h2>
          <p class="soft">Earlier versions of this scroll, scraped but never lost. Choose one to compare with today's text.</p>
          <ul class="palimpsest-list" id="revlist"></ul>
          <div id="revview"></div>
        </section>
      </article>

      <aside class="aside" aria-label="About this scroll">
        <div class="panel">
          <h3>Catalogue entry</h3>
          <label class="field">Status
            <select id="status">${state.meta.statuses.map((st) => html`<option value="${st.id}" ${st.id === s.status ? raw("selected") : ""}>${st.label}</option>`)}</select>
          </label>
          <div class="field" style="font-size:13px;color:var(--text-soft)">Rating
            <div class="rating-input" id="rating">${[1, 2, 3, 4, 5].map((n) => html`<button type="button" data-n="${n}" aria-pressed="${(s.rating || 0) >= n}" aria-label="${n} of 5">★</button>`)}</div>
          </div>
          <dl class="facts">
            ${s.tags.length ? html`<dt>Tags</dt><dd class="chips" style="gap:4px 10px">${tagLinks(s.tags)}</dd>` : ""}
            <dt>Added</dt><dd>${when(s.created_at)}</dd>
            <dt>Tended</dt><dd>${when(s.updated_at)}</dd>
            ${s.finished_at ? html`<dt>Shelved</dt><dd>${when(s.finished_at)}</dd>` : ""}
            <dt>Length</dt><dd>${plural(s.words, "word")}</dd>
          </dl>
        </div>
        <div class="pharos-box ${p ? "lit" : ""}" id="pharosbox">
          ${p ? html`<strong>Kept alive by the Pharos</strong>
              <span class="soft">${new Date(p.due_at) <= new Date() ? html`Due for review now — <a href="#/pharos">visit the Pharos</a>` : `Next review ${when(p.due_at)}`}${p.repetitions ? `, after ${plural(p.repetitions, "successful recall")}` : ""}.</span>
              <button class="btn btn-s" id="forget" type="button">Stop reviewing</button>`
            : html`<strong>Not kept in memory</strong>
              <span class="soft">The Pharos can bring this scroll back at growing intervals so it stays with you.</span>
              <button class="btn btn-s" id="remember" type="button">Keep it alive</button>`}
        </div>
        ${s.backlinks.length ? html`<div class="panel"><h3>Linked from</h3>${linkList(s.backlinks)}</div>` : ""}
        ${s.outlinks.length ? html`<div class="panel"><h3>Links to</h3>${linkList(s.outlinks)}</div>` : ""}
        ${s.unwritten.length ? html`<div class="panel"><h3>Unwritten scrolls</h3><ul class="linklist">${s.unwritten.map((t) => html`<li><a href="#/new?title=${encodeURIComponent(t)}" style="--spine:var(--line)">${t}</a></li>`)}</ul></div>` : ""}
        ${s.related.length ? html`<div class="panel"><h3>Kin by subject</h3>${linkList(s.related)}</div>` : ""}
      </aside>
    </div>`);

  const patch = async (body, msg) => {
    try { await api("PATCH", `/api/scrolls/${s.id}`, body); toast(msg); refreshStats(); return true; } catch (e) { fail(e); return false; }
  };
  $("#status").addEventListener("change", (e) => patch({ status: e.target.value }, `Marked as ${statusOf(e.target.value).label}`));
  $("#rating").addEventListener("click", async (e) => {
    const b = e.target.closest("button"); if (!b) return;
    const n = +b.dataset.n === s.rating ? 0 : +b.dataset.n;
    if (await patch({ rating: n }, n ? `Rated ${n} of 5` : "Rating cleared")) {
      s.rating = n || null;
      $$("#rating button").forEach((x) => x.setAttribute("aria-pressed", String(n >= +x.dataset.n)));
    }
  });
  $("#remember")?.addEventListener("click", async () => { try { await api("POST", `/api/scrolls/${s.id}/remember`); toast("The Pharos will bring it back tomorrow"); refreshStats(); router(); } catch (e) { fail(e); } });
  $("#forget")?.addEventListener("click", async () => { try { await api("DELETE", `/api/scrolls/${s.id}/remember`); toast("No longer reviewed"); refreshStats(); router(); } catch (e) { fail(e); } });
  $("#burn").addEventListener("click", async () => {
    if (!(await confirmAction(`Remove “${s.title}”?`, "The scroll, its marginalia and its earlier versions will be removed for good. Links to it will show as unwritten.", "Remove for good"))) return;
    try { await api("DELETE", `/api/scrolls/${s.id}`); toast("Removed from the shelves"); refreshStats(); nav.go("#/pinakes"); } catch (e) { fail(e); }
  });
  $("#mform").addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target));
    try { await api("POST", `/api/scrolls/${s.id}/marginalia`, body); toast("Written in the margin"); router(); } catch (err) { fail(err); }
  });
  $("#mlist").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-del-m]");
    if (!b) return;
    try { await api("DELETE", `/api/marginalia/${b.dataset.delM}`); b.closest("li").remove(); toast("Erased"); } catch (err) { fail(err); }
  });

  if (s.revisions) {
    const revs = await api("GET", `/api/scrolls/${s.id}/revisions`);
    $("#revlist").innerHTML = renderVal(revs.map((r) => html`<li><button type="button" data-rev="${r.id}">Version of ${new Date(r.created_at).toLocaleString()}${r.title !== s.title ? html` — titled “${r.title}”` : ""}</button></li>`));
    $("#revlist").addEventListener("click", (e) => {
      const b = e.target.closest("[data-rev]"); if (!b) return;
      const r = revs.find((x) => x.id === +b.dataset.rev);
      $$("#revlist button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      $("#revview").innerHTML = renderVal(html`
        <p class="muted" style="margin:14px 0 8px">Struck text was removed since then; highlighted text was added.</p>
        ${r.summary !== s.summary ? html`<div class="diff" style="margin-bottom:10px">${wordDiff(r.summary, s.summary)}</div>` : ""}
        <div class="diff">${wordDiff(r.content, s.content)}</div>
        <div class="row" style="margin-top:12px"><button class="btn" id="restore" type="button">Restore this version</button></div>`);
      $("#restore").addEventListener("click", async () => {
        try { await api("POST", `/api/revisions/${r.id}/restore`); toast("Restored — today's text joined the palimpsest"); router(); } catch (err) { fail(err); }
      });
    });
  }
}

// ----------------------------------------------------------------- editor
async function viewEditor(id, params = new URLSearchParams()) {
  if (!state.wings.length) await refreshWings();
  const tags = await api("GET", "/api/tags");
  const s = id ? await api("GET", `/api/scrolls/${id}`) : {
    title: params.get("title") || "", kind: params.get("kind") || "note", status: params.get("url") ? "inbox" : "queued",
    source_url: params.get("url") || "", author: "", summary: params.get("text") || "", content: "", tags: [],
    wing: null, rating: null,
  };
  document.title = (id ? `Editing ${s.title}` : "New scroll") + " — World Knowledge Library";
  const opt = (v, l, cur) => html`<option value="${v}" ${v === cur ? raw("selected") : ""}>${l}</option>`;
  mount(html`
    <form class="editor" id="editor" autocomplete="off">
      <div class="row" style="justify-content:space-between">
        <h1>${id ? "Edit scroll" : "A new scroll"}</h1>
        ${id ? html`${sillybos(s)}` : ""}
      </div>
      <label class="field">Title
        <input class="title-input" name="title" value="${s.title}" required placeholder="What is it called?">
      </label>
      <div class="grid-3">
        <label class="field">Kind<select name="kind">${state.meta.kinds.map((k) => opt(k.id, `${k.glyph}  ${k.label}`, s.kind))}</select></label>
        <label class="field">Status<select name="status">${state.meta.statuses.map((st) => opt(st.id, st.label, s.status))}</select></label>
        <label class="field">Wing
          <input name="wing" list="wing-names" value="${s.wing ? s.wing.name : ""}" placeholder="None, or name a new one">
          <datalist id="wing-names">${state.wings.map((w) => html`<option value="${w.name}">`)}</datalist>
        </label>
      </div>
      <div class="grid-2">
        <label class="field">Source
          <span class="row" style="flex-wrap:nowrap"><input name="source_url" type="url" value="${s.source_url}" placeholder="https://…">
          <button class="btn" type="button" id="readpage">Read the page</button></span>
        </label>
        <label class="field">Author or creator<input name="author" value="${s.author}"></label>
      </div>
      <label class="field">Tags <span class="hint">separate with commas</span>
        <input name="tags" value="${s.tags.join(", ")}" list="tag-names" placeholder="history, memory">
        <datalist id="tag-names">${tags.map((t) => html`<option value="${t.name}">`)}</datalist>
      </label>
      <label class="field">Summary <span class="hint">the gist in a sentence or two; the Pharos shows it during review</span>
        <textarea name="summary" rows="2">${s.summary}</textarea>
      </label>
      <div class="field">
        <div class="row" style="justify-content:space-between">
          <span>Body <span class="hint">Markdown. Type [[ to link another scroll.</span></span>
          <span class="editor-tabs" role="tablist">
            <button class="chip" type="button" role="tab" id="tab-write" aria-pressed="true" aria-selected="true">Write</button>
            <button class="chip" type="button" role="tab" id="tab-preview" aria-pressed="false" aria-selected="false">Preview</button>
          </span>
        </div>
        <div style="position:relative">
          <label class="sr-only" for="content">Body</label>
          <textarea class="writing" id="content" name="content" placeholder="Your notes, in your own words…">${s.content}</textarea>
          <div class="prose card" id="preview" hidden></div>
        </div>
      </div>
      ${id ? "" : html`<label class="row" style="gap:8px"><input type="checkbox" name="remember"> Ask the Pharos to keep it alive in memory</label>`}
      <div class="row">
        <button class="btn btn-primary" type="submit">${id ? "Save changes" : "Shelve the scroll"}</button>
        <a class="btn btn-quiet" href="${id ? `#/scroll/${id}` : "#/"}" id="cancel">Cancel</a>
        <span class="muted" style="font-size:13px">Ctrl+Enter saves</span>
      </div>
    </form>`, { narrow: true });

  const form = $("#editor");
  const content = $("#content");
  form.addEventListener("input", () => { state.dirty = true; });
  $("#cancel").addEventListener("click", () => { state.dirty = false; });

  $("#readpage").addEventListener("click", async (e) => {
    const url = form.source_url.value.trim();
    if (!url) { form.source_url.focus(); return; }
    e.target.disabled = true; e.target.textContent = "Reading…";
    try {
      const info = await api("POST", "/api/harbor/fetch", { url });
      if (info.error) toast(info.error, { error: true });
      if (!form.title.value.trim() && info.title) form.title.value = info.title;
      if (!form.author.value.trim() && info.author) form.author.value = info.author;
      if (!form.summary.value.trim() && info.summary) form.summary.value = info.summary;
      if (form.kind.value === "note" && info.kind) form.kind.value = info.kind;
      form.source_url.value = info.url;
      state.dirty = true;
    } catch (err) { fail(err); } finally { e.target.disabled = false; e.target.textContent = "Read the page"; }
  });
  if (!id && params.get("url") && !s.title) $("#readpage").click();

  const showPreview = async (on) => {
    $("#tab-write").setAttribute("aria-pressed", String(!on)); $("#tab-write").setAttribute("aria-selected", String(!on));
    $("#tab-preview").setAttribute("aria-pressed", String(on)); $("#tab-preview").setAttribute("aria-selected", String(on));
    content.hidden = on; $("#preview").hidden = !on;
    if (on) {
      const titles = [...new Set([...content.value.matchAll(/\[\[([^\[\]|#]+)/g)].map((m) => m[1].trim()))];
      const found = {};
      await Promise.all(titles.map(async (t) => {
        const r = await api("GET", `/api/titles?q=${encodeURIComponent(t)}&limit=3`);
        const hit = r.find((x) => x.title.toLowerCase() === t.toLowerCase());
        if (hit) found[t.toLowerCase()] = hit;
      }));
      $("#preview").innerHTML = md(content.value, found) || '<p class="muted">Nothing written yet.</p>';
    }
  };
  $("#tab-write").addEventListener("click", () => showPreview(false));
  $("#tab-preview").addEventListener("click", () => showPreview(true));

  wireWikiAutocomplete(content);

  const save = async () => {
    const fd = Object.fromEntries(new FormData(form));
    const body = {
      title: fd.title, kind: fd.kind, status: fd.status, source_url: fd.source_url, author: fd.author,
      summary: fd.summary, content: fd.content, tags: fd.tags, wing: fd.wing.trim() || 0,
    };
    if (!id) body.remember = !!fd.remember;
    try {
      const saved = id ? await api("PATCH", `/api/scrolls/${id}`, body) : await api("POST", "/api/scrolls", body);
      state.dirty = false;
      toast(id ? "Changes saved" : `Shelved as ${saved.call_number}`);
      refreshStats(); refreshWings();
      nav.go(`#/scroll/${saved.id}`);
    } catch (e) { fail(e); }
  };
  form.addEventListener("submit", (e) => { e.preventDefault(); save(); });
  form.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); save(); } });
  (id ? content : form.title).focus();
}

function wireWikiAutocomplete(ta) {
  const list = document.createElement("ul");
  list.className = "autocomplete"; list.hidden = true; list.setAttribute("role", "listbox");
  ta.parentElement.append(list);
  let items = [], sel = 0, start = -1;
  const close = () => { list.hidden = true; start = -1; };
  const pick = (i) => {
    const it = items[i]; if (!it) return;
    const before = ta.value.slice(0, start), after = ta.value.slice(ta.selectionStart).replace(/^[^\]\n]*\]\]/, "");
    ta.value = `${before}[[${it.title}]]${after}`;
    const pos = before.length + it.title.length + 4;
    ta.setSelectionRange(pos, pos);
    state.dirty = true;
    close(); ta.focus();
  };
  const paint = () => {
    list.innerHTML = renderVal(items.map((it, i) => html`<li role="option" aria-selected="${i === sel}" data-i="${i}">${it.id ? sillybos(it) : html`<span class="muted">new</span>`}<span>${it.title}</span></li>`));
  };
  const lookup = debounce(async (q) => {
    try {
      const r = await api("GET", `/api/titles?q=${encodeURIComponent(q)}&limit=8`);
      items = r;
      if (q && !r.some((x) => x.title.toLowerCase() === q.toLowerCase())) items = [...r, { title: q }];
      if (!items.length) return close();
      sel = 0; paint();
      // place the list roughly under the caret line
      const lineNo = ta.value.slice(0, ta.selectionStart).split("\n").length;
      const lh = parseFloat(getComputedStyle(ta).lineHeight) || 26;
      list.style.top = Math.min(ta.clientHeight, 14 + lineNo * lh - ta.scrollTop) + "px";
      list.style.left = "16px";
      list.hidden = false;
    } catch { close(); }
  }, 120);
  ta.addEventListener("input", () => {
    const upto = ta.value.slice(0, ta.selectionStart);
    const m = upto.match(/\[\[([^\[\]\n|]*)$/);
    if (!m) return close();
    start = upto.length - m[0].length;
    lookup(m[1]);
  });
  ta.addEventListener("keydown", (e) => {
    if (list.hidden) return;
    if (e.key === "ArrowDown") { e.preventDefault(); sel = (sel + 1) % items.length; paint(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); sel = (sel - 1 + items.length) % items.length; paint(); }
    else if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); pick(sel); }
    else if (e.key === "Escape") { e.preventDefault(); close(); }
  });
  list.addEventListener("mousedown", (e) => { const li = e.target.closest("li"); if (li) { e.preventDefault(); pick(+li.dataset.i); } });
  ta.addEventListener("blur", () => setTimeout(close, 120));
}

// ----------------------------------------------------------------- pharos
async function viewPharos() {
  const due = await api("GET", "/api/pharos?limit=100");
  const stats = state.stats || await api("GET", "/api/stats");
  if (!due.length) {
    mount(html`<div class="pharos-stage">
      <h1>The Pharos</h1>
      <p class="lede">The great lighthouse guided ships home. This one guides knowledge back to you: scrolls you choose to keep are brought back at growing intervals, so they stay with you instead of fading.</p>
      <div class="empty">${stats.remembered
        ? `Nothing is due. ${plural(stats.remembered, "scroll")} kept in memory; the next will return when it is due.`
        : html`No scrolls are kept yet. Open any scroll and choose <strong>Keep it alive</strong>.`}</div>
    </div>`, { narrow: true });
    return;
  }
  let i = 0, revealed = false, done = 0;
  const grades = [["Forgotten", "back tomorrow"], ["Hazy", "a little sooner"], ["Recalled", "further out"], ["Vivid", "much further out"]];
  const paint = () => {
    if (i >= due.length) {
      mount(html`<div class="pharos-stage"><h1>The lamp is trimmed</h1>
        <p class="lede">You revisited ${plural(done, "scroll")}. Each will return when it is due.</p>
        <div class="row" style="margin-top:20px"><a class="btn btn-primary" href="#/">Return to the Atrium</a></div></div>`, { narrow: true });
      refreshStats();
      return;
    }
    const s = due[i];
    mount(html`<div class="pharos-stage">
      <h1>The Pharos</h1>
      <p class="beacon">Scroll ${i + 1} of ${due.length}. Recall what you know before unrolling it.</p>
      <div class="progress" aria-hidden="true"><span style="width:${Math.round((i / due.length) * 100)}%"></span></div>
      <div class="flashcard">
        <div class="row">${sillybos(s)}<span class="muted">${kindOf(s.kind).label}${s.author ? ` by ${s.author}` : ""}</span></div>
        <h2>${s.title}</h2>
        ${revealed ? html`<div class="reveal">
            ${s.summary ? html`<p class="epigraph">${s.summary}</p>` : ""}
            <div class="prose">${raw(md(s.content.length > 1600 ? s.content.slice(0, 1600) + "…" : s.content))}</div>
            ${s.marginalia.length ? html`<div class="marginalia" style="margin-top:20px"><ol>${s.marginalia.map((m) => html`<li data-kind="${m.kind}"><div>${m.quote ? html`<blockquote>“${m.quote}”</blockquote>` : ""}<div class="m-body">${m.body}</div></div></li>`)}</ol></div>` : ""}
            <p class="muted" style="margin-top:18px">How well did you remember it? Keys 1 to 4.</p>
            <div class="grades">${grades.map(([l, d], g) => html`<button class="btn ${g === 2 ? "btn-primary" : ""}" data-grade="${g}" type="button">${l}<small>${d}</small></button>`)}</div>
            <div class="row" style="margin-top:12px"><a class="btn btn-quiet btn-s" href="#/scroll/${s.id}">Open the full scroll</a></div>
          </div>`
        : html`<p class="prompt">What is it about? What did you take from it? Why did you keep it?</p>
            <button class="btn btn-primary" id="unroll" type="button">Unroll the scroll</button> <span class="muted" style="font-size:13px">or press Space</span>`}
      </div></div>`, { narrow: true });
    $("#unroll")?.addEventListener("click", () => { revealed = true; paint(); });
    $$("[data-grade]").forEach((b) => b.addEventListener("click", () => grade(+b.dataset.grade)));
  };
  const grade = async (g) => {
    try {
      await api("POST", `/api/pharos/${due[i].id}`, { grade: g });
      done++; i++; revealed = false; paint();
    } catch (e) { fail(e); }
  };
  const onKey = (e) => {
    if (e.target.matches("input, textarea, select")) return;
    if (!revealed && (e.key === " " || e.key === "Enter")) { e.preventDefault(); revealed = true; paint(); }
    else if (revealed && /^[1-4]$/.test(e.key)) grade(+e.key - 1);
  };
  document.addEventListener("keydown", onKey);
  teardown = () => document.removeEventListener("keydown", onKey);
  paint();
}

// ----------------------------------------------------------- constellation
async function viewConstellation() {
  const g = await api("GET", "/api/graph");
  if (!state.wings.length) await refreshWings();
  mount(html`
    <div class="row" style="justify-content:space-between;align-items:end;margin-bottom:14px">
      <div><h1>The Constellation</h1>
      <p class="lede">Every scroll is a star; every [[link]] a line between them. Drag to move, scroll to zoom, select a star to open it.</p></div>
      <div class="row">
        <label class="row" style="gap:6px;font-size:14px"><input type="checkbox" id="affin"> Show shared tags</label>
        <select id="gwing" aria-label="Wing" style="width:auto"><option value="">Every wing</option>${state.wings.map((w) => html`<option value="${w.id}">${w.name}</option>`)}</select>
      </div>
    </div>
    ${g.nodes.length ? html`<div class="constellation-wrap"><canvas id="sky" aria-label="Graph of linked scrolls"></canvas><div class="graph-tip" id="tip" hidden></div></div>
      <div class="legend">${state.meta.kinds.filter((k) => g.nodes.some((n) => n.kind === k.id)).map((k) => html`<span data-kind="${k.id}"><i></i>${k.label}</span>`)}</div>`
      : html`<div class="empty">No stars yet. Shelve a few scrolls and link them with [[double brackets]].</div>`}`);
  if (!g.nodes.length) return;
  teardown = startSky(g);
}

function startSky(g) {
  const canvas = $("#sky"), tip = $("#tip"), ctx = canvas.getContext("2d");
  const css = getComputedStyle(document.documentElement);
  const color = (k) => css.getPropertyValue(`--k-${k}`).trim() || "#999";
  const lineCol = css.getPropertyValue("--line").trim(), textCol = css.getPropertyValue("--text").trim(), flame = css.getPropertyValue("--flame").trim();
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let W = 0, H = 0, dpr = 1;
  let showAff = false, wingFilter = "";
  const byId = new Map();
  const nodes = g.nodes.map((n, i) => {
    const a = i * 2.39996, r = 12 * Math.sqrt(i + 1);
    const node = { ...n, x: Math.cos(a) * r, y: Math.sin(a) * r, vx: 0, vy: 0, r: 4 + Math.sqrt(n.degree) * 2.4 };
    byId.set(n.id, node);
    return node;
  });
  const links = g.links.map((l) => ({ s: byId.get(l.source), t: byId.get(l.target) })).filter((l) => l.s && l.t);
  const affs = g.affinities.map((l) => ({ s: byId.get(l.source), t: byId.get(l.target), w: l.weight })).filter((l) => l.s && l.t);
  let view_ = { x: 0, y: 0, k: 1 }, alpha = 1, hover = null, drag = null, panning = null, raf = 0, moved = false, touched = false;
  const fewStars = nodes.length <= 60;
  const fit = () => {
    const vis = nodes.filter((n) => !wingFilter || String(n.wing_id) === wingFilter);
    if (!vis.length || !W) return;
    let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    vis.forEach((n) => { x0 = Math.min(x0, n.x); x1 = Math.max(x1, n.x); y0 = Math.min(y0, n.y); y1 = Math.max(y1, n.y); });
    const k = Math.min((W - 160) / Math.max(60, x1 - x0), (H - 80) / Math.max(60, y1 - y0), 2.2);
    view_ = { x: -(x0 + x1) / 2, y: -(y0 + y1) / 2, k: Math.max(0.25, k) };
  };

  const resize = () => {
    const r = canvas.getBoundingClientRect();
    dpr = window.devicePixelRatio || 1; W = r.width; H = r.height;
    canvas.width = W * dpr; canvas.height = H * dpr;
    if (!touched) fit();
    kick();
  };
  const visible = (n) => !wingFilter || String(n.wing_id) === wingFilter;
  const step = () => {
    const N = nodes.length;
    for (let a = 0; a < N; a++) {
      const p = nodes[a];
      for (let b = a + 1; b < N; b++) {
        const q = nodes[b];
        let dx = p.x - q.x, dy = p.y - q.y, d2 = dx * dx + dy * dy || 0.01;
        if (d2 > 90000) continue;
        const f = (900 / d2) * alpha;
        const d = Math.sqrt(d2); dx /= d; dy /= d;
        p.vx += dx * f; p.vy += dy * f; q.vx -= dx * f; q.vy -= dy * f;
      }
    }
    const spring = (l, len, k) => {
      const dx = l.t.x - l.s.x, dy = l.t.y - l.s.y, d = Math.sqrt(dx * dx + dy * dy) || 1;
      const f = (d - len) * k * alpha;
      l.s.vx += (dx / d) * f; l.s.vy += (dy / d) * f; l.t.vx -= (dx / d) * f; l.t.vy -= (dy / d) * f;
    };
    links.forEach((l) => spring(l, 70, 0.06));
    if (showAff) affs.forEach((l) => spring(l, 110, 0.008 * l.w));
    for (const n of nodes) {
      n.vx -= n.x * 0.004 * alpha; n.vy -= n.y * 0.004 * alpha;
      if (n === drag) { n.vx = n.vy = 0; continue; }
      n.vx *= 0.82; n.vy *= 0.82;
      n.x += Math.max(-20, Math.min(20, n.vx)); n.y += Math.max(-20, Math.min(20, n.vy));
    }
    alpha = Math.max(0, alpha * 0.985 - 0.0005);
  };
  const toScreen = (n) => [W / 2 + (n.x + view_.x) * view_.k, H / 2 + (n.y + view_.y) * view_.k];
  const draw = () => {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const lit = new Set();
    if (hover) { lit.add(hover); links.forEach((l) => { if (l.s === hover) lit.add(l.t); if (l.t === hover) lit.add(l.s); }); }
    if (showAff) {
      ctx.setLineDash([2, 4]); ctx.lineWidth = 1; ctx.strokeStyle = lineCol; ctx.globalAlpha = 0.6;
      ctx.beginPath();
      affs.forEach((l) => { if (!visible(l.s) || !visible(l.t)) return; const [a, b] = toScreen(l.s), [c, d] = toScreen(l.t); ctx.moveTo(a, b); ctx.lineTo(c, d); });
      ctx.stroke(); ctx.setLineDash([]); ctx.globalAlpha = 1;
    }
    links.forEach((l) => {
      if (!visible(l.s) || !visible(l.t)) return;
      const on = hover && (l.s === hover || l.t === hover);
      ctx.strokeStyle = on ? flame : lineCol; ctx.lineWidth = on ? 1.8 : 1.1; ctx.globalAlpha = hover && !on ? 0.35 : 0.9;
      const [a, b] = toScreen(l.s), [c, d] = toScreen(l.t);
      ctx.beginPath(); ctx.moveTo(a, b); ctx.lineTo(c, d); ctx.stroke();
    });
    ctx.globalAlpha = 1;
    nodes.forEach((n) => {
      if (!visible(n)) return;
      const [x, y] = toScreen(n), r = n.r * Math.max(0.6, Math.min(view_.k, 2));
      ctx.globalAlpha = hover && !lit.has(n) ? 0.35 : 1;
      if (n === hover) { ctx.fillStyle = flame; ctx.globalAlpha = 0.25; ctx.beginPath(); ctx.arc(x, y, r + 8, 0, 7); ctx.fill(); ctx.globalAlpha = 1; }
      ctx.fillStyle = color(n.kind);
      ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.fill();
      if (fewStars || n.degree >= 3 || lit.has(n) || view_.k > 1.6) {
        ctx.fillStyle = textCol; ctx.font = `${n === hover ? 600 : 400} 12px Commissioner, system-ui, sans-serif`;
        ctx.fillText(n.title.length > 34 ? n.title.slice(0, 32) + "…" : n.title, x + r + 5, y + 4);
      }
    });
    ctx.globalAlpha = 1;
  };
  const tick = () => {
    if (alpha > 0.002) { step(); if (!reduced) step(); }
    if (!touched) fit();
    draw();
    raf = alpha > 0.002 || drag ? requestAnimationFrame(tick) : 0;
  };
  const kick = (a = 0.5) => { alpha = Math.max(alpha, a); if (!raf) raf = requestAnimationFrame(tick); };
  if (reduced) { for (let i = 0; i < 300; i++) step(); }
  canvas.addEventListener("wheel", () => { touched = true; }, { passive: true });

  const at = (ev) => {
    const r = canvas.getBoundingClientRect();
    const mx = ev.clientX - r.left, my = ev.clientY - r.top;
    let best = null, bd = 1e9;
    nodes.forEach((n) => {
      if (!visible(n)) return;
      const [x, y] = toScreen(n), d = Math.hypot(x - mx, y - my);
      if (d < Math.max(10, n.r * view_.k + 4) && d < bd) { best = n; bd = d; }
    });
    return { node: best, mx, my };
  };
  canvas.addEventListener("pointermove", (ev) => {
    const { node, mx, my } = at(ev);
    if (drag) { drag.x = (mx - W / 2) / view_.k - view_.x; drag.y = (my - H / 2) / view_.k - view_.y; moved = true; kick(0.3); return; }
    if (panning) { view_.x += (ev.clientX - panning.x) / view_.k; view_.y += (ev.clientY - panning.y) / view_.k; panning = { x: ev.clientX, y: ev.clientY }; moved = true; draw(); return; }
    if (node !== hover) { hover = node; draw(); }
    if (node) {
      tip.hidden = false;
      tip.innerHTML = renderVal(html`<strong>${node.title}</strong><br><span class="muted">${node.call_number}, ${plural(node.degree, "link")}</span>`);
      tip.style.left = Math.min(mx + 14, W - 240) + "px"; tip.style.top = (my + 14) + "px";
    } else tip.hidden = true;
  });
  canvas.addEventListener("pointerdown", (ev) => {
    canvas.setPointerCapture(ev.pointerId);
    moved = false;
    const { node } = at(ev);
    if (node) drag = node; else { panning = { x: ev.clientX, y: ev.clientY }; touched = true; }
    canvas.classList.add("dragging");
  });
  canvas.addEventListener("pointerup", () => {
    const clicked = drag && !moved ? drag : null;
    drag = null; panning = null; canvas.classList.remove("dragging");
    if (clicked) nav.go(`#/scroll/${clicked.id}`);
  });
  canvas.addEventListener("pointerleave", () => { hover = null; tip.hidden = true; draw(); });
  canvas.addEventListener("wheel", (ev) => {
    ev.preventDefault();
    view_.k = Math.max(0.2, Math.min(4, view_.k * (ev.deltaY < 0 ? 1.12 : 1 / 1.12)));
    draw();
  }, { passive: false });
  $("#affin").addEventListener("change", (e) => { showAff = e.target.checked; kick(0.6); });
  $("#gwing").addEventListener("change", (e) => { wingFilter = e.target.value; touched = false; fit(); draw(); });
  const ro = new ResizeObserver(resize);
  ro.observe(canvas);
  resize();
  return () => { ro.disconnect(); cancelAnimationFrame(raf); };
}

// ------------------------------------------------------------------ wings
async function viewWings() {
  await refreshWings();
  mount(html`
    <h1>The Wings</h1>
    <p class="lede">Wings group scrolls into broad collections: a field, a project, a season of life. A scroll lives in one wing; tags cut across them all.</p>
    <form class="capture" id="wform" style="margin-top:22px;grid-template-columns:120px minmax(0,1fr) minmax(0,1.4fr) auto">
      <label class="sr-only" for="wemb">Emblem</label><input id="wemb" name="emblem" placeholder="Emblem ✦" maxlength="4">
      <label class="sr-only" for="wname">Name</label><input id="wname" name="name" placeholder="Name, e.g. Philosophy" required>
      <label class="sr-only" for="wdesc">Description</label><input id="wdesc" name="description" placeholder="What belongs here">
      <button class="btn btn-primary" type="submit">Open the wing</button>
    </form>
    ${state.wings.length ? html`<ul class="wing-list" id="wings">${state.wings.map((w) => html`
      <li class="wing" data-id="${w.id}">
        <span class="emblem" aria-hidden="true">${w.emblem || "🏛"}</span>
        <a class="name" href="#/pinakes?wing=${w.id}">${w.name}</a>
        <p>${w.description || ""}</p>
        <p class="muted">${plural(w.scroll_count, "scroll")}</p>
        <div class="row"><button class="btn btn-s btn-quiet" data-edit type="button">Rename</button><button class="btn btn-s btn-quiet btn-danger" data-del type="button">Close</button></div>
      </li>`)}</ul>`
      : html`<div class="empty">No wings yet. Open one above, or type a wing name while editing any scroll.</div>`}`);
  $("#wform").addEventListener("submit", async (e) => {
    e.preventDefault();
    try { await api("POST", "/api/wings", Object.fromEntries(new FormData(e.target))); toast("The wing is open"); viewWings(); } catch (err) { fail(err); }
  });
  $("#wings")?.addEventListener("click", async (e) => {
    const li = e.target.closest("li"); if (!li) return;
    const w = state.wings.find((x) => x.id === +li.dataset.id);
    if (e.target.closest("[data-del]")) {
      if (!(await confirmAction(`Close the ${w.name} wing?`, `Its ${plural(w.scroll_count, "scroll")} stay on the shelves, just without a wing.`, "Close the wing"))) return;
      try { await api("DELETE", `/api/wings/${w.id}`); toast("The wing is closed"); viewWings(); } catch (err) { fail(err); }
    } else if (e.target.closest("[data-edit]")) {
      li.innerHTML = renderVal(html`<form class="stack" data-save>
        <input name="emblem" value="${w.emblem}" placeholder="Emblem" maxlength="4" aria-label="Emblem">
        <input name="name" value="${w.name}" required aria-label="Name">
        <input name="description" value="${w.description}" placeholder="Description" aria-label="Description">
        <div class="row"><button class="btn btn-s btn-primary">Save changes</button><button class="btn btn-s btn-quiet" type="button" data-cancel>Cancel</button></div></form>`);
      $("[data-cancel]", li).addEventListener("click", viewWings);
      $("[data-save]", li).addEventListener("submit", async (ev) => {
        ev.preventDefault();
        try { await api("PATCH", `/api/wings/${w.id}`, Object.fromEntries(new FormData(ev.target))); toast("Changes saved"); viewWings(); } catch (err) { fail(err); }
      });
    }
  });
}

// --------------------------------------------------------------- serapeum
async function viewSerapeum() {
  const [stats, tags] = await Promise.all([api("GET", "/api/stats"), api("GET", "/api/tags")]);
  const maxKind = Math.max(1, ...Object.values(stats.by_kind));
  const maxMonth = Math.max(1, ...stats.monthly.map((m) => m.added + m.finished));
  const origin = DEMO ? "" : location.origin;
  const bookmarklet = `javascript:(()=>{window.open('${origin}/#/new?url='+encodeURIComponent(location.href)+'&title='+encodeURIComponent(document.title)+'&text='+encodeURIComponent(String(getSelection()).slice(0,1500)),'_blank')})()`;
  mount(html`
    <h1>The Serapeum</h1>
    <p class="lede">Alexandria's daughter library held copies of its scrolls. Keep copies of yours here, bring in knowledge from elsewhere, and see the shape of the collection.</p>
    <div class="grid-2" style="margin-top:26px">
      <div class="card">
        <h2>Make a copy</h2>
        <p>Download the whole library, with marginalia, review history and every earlier version, as one JSON archive. For a folder of Markdown files run <code>wkl export --markdown DIR</code>.</p>
        ${DEMO ? html`<button class="btn btn-primary" id="copy-archive" type="button">Copy the archive</button>
          <p class="muted" style="margin:10px 0 0;font-size:13px">Paste it into a .json file, then bring it into the installed library with <code>wkl import</code>.</p>
          <textarea id="archive-text" rows="6" readonly hidden aria-label="Archive JSON" style="margin-top:10px;font-size:12px"></textarea>`
          : html`<a class="btn btn-primary" href="/api/serapeum/export" download>Download the archive</a>`}
      </div>
      <div class="card">
        <h2>Bring in an archive</h2>
        <p>Merge a JSON archive from this or another World Knowledge Library. Scrolls already on the shelves are skipped. For Markdown notes or an Obsidian vault run <code>wkl import PATH</code>.</p>
        <label class="btn" for="importfile">Choose an archive…</label>
        <input id="importfile" type="file" accept="application/json,.json" class="sr-only">
      </div>
      ${DEMO ? html`<div class="card">
        <h2>Keep it for real</h2>
        <p>This sandbox lives in one browser. The installed library keeps everything in one file on your computer, reads links for you, and gives you the <code>wkl</code> command and a bookmark button for capturing any page.</p>
        <pre class="install"><code>pip install -e .
wkl demo
wkl serve --open</code></pre>
      </div>` : html`<div class="card">
        <h2>Capture from any page</h2>
        <p>Drag this button to your bookmarks bar. On any web page, select a passage if you like, then press it to open a new scroll with the link, title and passage filled in.</p>
        <a class="bookmarklet" id="bm" href="#">Dock in the Library</a>
      </div>`}
      <div class="card">
        <h2>Shape of the collection</h2>
        <p>${plural(stats.scrolls, "scroll")}, ${plural(stats.marginalia, "note")} in the margins and ${plural(stats.revisions, "earlier version")} in the palimpsest.</p>
        <div class="bars">${Object.entries(stats.by_kind).sort((a, b) => b[1] - a[1]).map(([k, n]) => html`
          <div class="bar" data-kind="${k}"><span>${kindOf(k).label}</span><span class="track"><span class="fill" style="width:${(n / maxKind) * 100}%"></span></span><span class="n">${n}</span></div>`)}</div>
      </div>
    </div>
    <section style="margin-top:34px">
      <div class="section-head"><h2>Arrivals and shelvings, by month</h2><span class="muted"><span style="color:var(--faience)">■</span> added <span style="color:var(--flame)">■</span> shelved</span></div>
      <div class="months">${stats.monthly.map((m) => html`<div title="${m.month}: ${m.added} added, ${m.finished} shelved">
        <div class="mbars"><span class="a" style="height:${(m.added / maxMonth) * 100}%"></span><span class="f" style="height:${(m.finished / maxMonth) * 100}%"></span></div>
        <small>${new Date(m.month + "-01T00:00:00").toLocaleDateString(undefined, { month: "short" })}</small></div>`)}</div>
    </section>
    <section style="margin-top:34px">
      <div class="section-head"><h2>Tags</h2><span class="muted">Select a tag to rename or merge it</span></div>
      ${tags.length ? html`<div class="chips" id="tagchips">${tags.map((t) => html`<button class="chip" type="button" data-tag="${t.name}">${t.name} <span class="muted">${t.count}</span></button>`)}</div>` : html`<p class="soft">No tags yet.</p>`}
      <form class="row" id="tagform" hidden style="margin-top:14px;max-width:560px">
        <span>Rename <strong id="tagfrom"></strong> to</span>
        <input name="to" style="flex:1;width:auto" required aria-label="New tag name">
        <button class="btn btn-primary">Rename</button>
      </form>
    </section>
    <p class="muted" style="margin-top:40px;font-size:13px">${DEMO ? "This sandbox lives only in this browser." : html`This library lives in <code>${state.meta.path}</code>.`} Version ${state.meta.version}.</p>`);
  if (DEMO) {
    $("#copy-archive").addEventListener("click", async () => {
      const text = JSON.stringify(await api("GET", "/api/serapeum/export"), null, 2);
      try { await navigator.clipboard.writeText(text); toast("Archive copied"); }
      catch { const ta = $("#archive-text"); ta.hidden = false; ta.value = text; ta.focus(); ta.select(); toast("Select all and copy the archive below"); }
    });
  } else {
    $("#bm").setAttribute("href", bookmarklet);
    $("#bm").addEventListener("click", (e) => { e.preventDefault(); toast("Drag the button to your bookmarks bar instead of clicking it."); });
  }
  $("#importfile").addEventListener("change", async (e) => {
    const file = e.target.files[0]; if (!file) return;
    try {
      const data = JSON.parse(await file.text());
      const r = await api("POST", "/api/serapeum/import", data);
      toast(`Brought in ${plural(r.added, "scroll")}; ${r.skipped} already on the shelves`);
      refreshStats(); refreshWings(); viewSerapeum();
    } catch (err) { fail(err instanceof SyntaxError ? new Error("That file is not valid JSON") : err); }
  });
  let from = "";
  $("#tagchips")?.addEventListener("click", (e) => {
    const b = e.target.closest("[data-tag]"); if (!b) return;
    from = b.dataset.tag;
    $$("#tagchips .chip").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    $("#tagfrom").textContent = "#" + from;
    $("#tagform").hidden = false;
    $("#tagform").to.value = from; $("#tagform").to.select();
  });
  $("#tagform").addEventListener("submit", async (e) => {
    e.preventDefault();
    try { await api("POST", "/api/tags/rename", { from, to: e.target.to.value }); toast("Tag renamed"); viewSerapeum(); } catch (err) { fail(err); }
  });
}

// ------------------------------------------------------------------- boot
async function boot() {
  setTheme(store.get("wkl-theme"));
  $("#theme-toggle").addEventListener("click", (e) => { const t = e.target.dataset.next; store.set("wkl-theme", t); setTheme(t); });
  $("#menu-btn").addEventListener("click", () => {
    const open = $("#rail").classList.toggle("open");
    $("#menu-btn").setAttribute("aria-expanded", String(open));
  });
  $("#search-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const q = $("#global-search").value.trim();
    nav.go(`#/pinakes${q ? "?q=" + encodeURIComponent(q) : ""}`);
  });
  $("#global-search").addEventListener("input", debounce(() => {
    const pq = $("#pq");
    if (pq) { pq.value = $("#global-search").value; pq.dispatchEvent(new Event("input", { bubbles: true })); }
  }, 150));
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && !e.target.matches("input, textarea, select, [contenteditable]")) { e.preventDefault(); $("#global-search").focus(); }
  });
  window.addEventListener("beforeunload", (e) => { if (state.dirty) { e.preventDefault(); e.returnValue = ""; } });
  if (MEMORY_NAV) {
    // In-page links ("#/…") are handled here instead of by the address bar.
    document.addEventListener("click", (e) => {
      const a = e.target.closest('a[href^="#/"]');
      if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey) return;
      e.preventDefault();
      nav.go(a.getAttribute("href"));
    });
  } else {
    window.addEventListener("hashchange", () => { document.title = "World Knowledge Library"; router(); });
  }
  if (DEMO) {
    const foot = $(".rail-foot");
    foot.insertAdjacentHTML("afterbegin", renderVal(html`<p class="demo-note">This is a demo sandbox: it runs in your browser and keeps your changes on this device only.</p>
      <button class="btn btn-quiet btn-s" id="demo-reset" type="button">Reset the demo</button>`));
    $("#demo-reset").addEventListener("click", async () => {
      if (!(await confirmAction("Reset the demo?", "Everything you added or changed in this sandbox is replaced by the example collection.", "Reset the demo", "Keep my changes"))) return;
      window.WKL_DEMO.reset();
      state.dirty = false;
      await Promise.all([refreshStats(), refreshWings()]);
      nav.go("#/");
      toast("The demo is back to its example collection");
    });
  }
  try {
    state.meta = await api("GET", "/api/meta");
    $("#library-path").textContent = `v${state.meta.version}`;
    $("#library-path").title = state.meta.path;
  } catch (e) {
    mount(html`<div class="empty"><h1>The library is closed</h1><p>The reading room could not reach the library server. Start it with <code>wkl serve</code> and reload this page.</p></div>`);
    return;
  }
  await Promise.all([refreshStats(), refreshWings()]);
  router();
}
boot();
