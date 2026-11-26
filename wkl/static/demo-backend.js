/* World Knowledge Library — in-browser stand-in for the library server.

   Used only by the standalone demo (scripts/build_demo.py). It answers the same
   /api/... requests as wkl/server.py, with the same shapes, by porting the logic
   of wkl/library.py to JavaScript. Each visitor gets a private sandbox kept in
   their browser's storage (or in memory when storage is unavailable).

   Expects window.WKL_SEED = { meta, archive, version } to be defined first. */
(function () {
  "use strict";
  const SEED = window.WKL_SEED;
  const KEY = "wkl-demo-sandbox-v1";
  const KINDS = Object.fromEntries(SEED.meta.kinds.map((k) => [k.id, k]));
  const STATUSES = new Set(SEED.meta.statuses.map((s) => s.id));
  const MARGINALIA_KINDS = new Set(SEED.meta.marginalia_kinds);
  const DAY = 86400000;

  class ApiError extends Error { constructor(status, message) { super(message); this.status = status; } }
  const notFound = (m) => new ApiError(404, m);
  const bad = (m) => new ApiError(400, m);

  // ------------------------------------------------------------ utilities
  const iso = (d = new Date()) => new Date(d).toISOString().replace(/\.\d+Z$/, "Z");
  const later = (days, from = Date.now()) => iso(new Date(+new Date(from) + days * DAY));
  const fold = (s) => (s || "").normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
  const reEsc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const words = (s) => (s || "").match(/[\p{L}\p{N}_]+/gu) || [];
  const byTitle = (a, b) => a.title.localeCompare(b.title, undefined, { sensitivity: "base" });
  const callNumber = (kind, id) => `${(KINDS[kind] || KINDS.other).mark}-${String(id).padStart(4, "0")}`;
  const clean = (v) => (v == null ? "" : String(v));

  function normaliseTags(tags) {
    if (tags == null) return [];
    if (typeof tags === "string") tags = tags.includes(",") ? tags.split(",") : tags.split(/\s+/);
    const out = [];
    for (let t of tags) {
      t = String(t).trim().replace(/^#+/, "").trim().toLowerCase().replace(/\s+/g, "-");
      if (t && !out.includes(t)) out.push(t);
    }
    return out;
  }
  function wikilinkTargets(text) {
    const out = [];
    for (const m of (text || "").matchAll(/\[\[([^\[\]|#]+?)(?:#[^\[\]|]*)?(?:\|[^\[\]]*)?\]\]/g)) {
      const t = m[1].trim();
      if (!out.includes(t)) out.push(t);
    }
    return out;
  }
  function plain(text) {
    return (text || "")
      .replace(/\[\[([^\[\]|]+?)\|([^\[\]]+)\]\]/g, "$2")
      .replace(/\[\[([^\[\]|#]+?)(?:#[^\[\]]*)?\]\]/g, "$1")
      .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
      .replace(/^\s{0,3}(#{1,6}\s+|>\s?|[-*+]\s+(\[[ xX]\]\s+)?|\d+[.)]\s+)/gm, "")
      .replace(/(^|\s)#{1,6}\s/g, "$1")
      .replace(/(\*\*|__|~~|==|`)/g, "")
      .replace(/(^|[^\w*])[*_](?=\S)([^*_\n]+?)(?<=\S)[*_](?![\w*])/g, "$1$2")
      .split(/\s+/).filter(Boolean).join(" ");
  }

  // ------------------------------------------------------------- storage
  let db;
  const empty = () => ({ seq: { scroll: 0, wing: 0, marginalia: 0, revision: 0 }, scrolls: [], wings: [], marginalia: [], palimpsest: [], pharos: {} });
  function save() { try { localStorage.setItem(KEY, JSON.stringify(db)); } catch { /* storage unavailable: keep in memory */ } }
  function load() {
    try {
      const raw = localStorage.getItem(KEY);
      if (raw) { const parsed = JSON.parse(raw); if (parsed && parsed.scrolls) return parsed; }
    } catch { /* fall through to a fresh sandbox */ }
    return null;
  }

  /** Move every timestamp in the seed so its newest moment is "now". */
  function freshen(archive) {
    const a = JSON.parse(JSON.stringify(archive));
    const shift = Date.now() - +new Date(a.exported_at);
    const move = (o, keys) => keys.forEach((k) => { if (o && o[k]) o[k] = iso(+new Date(o[k]) + shift); });
    a.wings.forEach((w) => move(w, ["created_at"]));
    a.scrolls.forEach((s) => {
      move(s, ["created_at", "updated_at", "finished_at"]);
      (s.marginalia || []).forEach((m) => move(m, ["created_at"]));
      (s.palimpsest || []).forEach((r) => move(r, ["created_at"]));
      move(s.pharos, ["due_at", "last_reviewed"]);
    });
    return a;
  }

  // ---------------------------------------------------------------- wings
  const wingById = (id) => db.wings.find((w) => w.id === id);
  function getWing(id) { const w = wingById(+id); if (!w) throw notFound(`No wing with id ${id}`); return { ...w }; }
  function listWings() {
    return db.wings.map((w) => ({ ...w, scroll_count: db.scrolls.filter((s) => s.wing_id === w.id).length }))
      .sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));
  }
  function createWing(name, description = "", emblem = "", created_at) {
    name = clean(name).trim();
    if (!name) throw bad("A wing needs a name");
    if (db.wings.some((w) => w.name.toLowerCase() === name.toLowerCase())) throw bad(`A wing called '${name}' already exists`);
    const w = { id: ++db.seq.wing, name, description: clean(description).trim(), emblem: clean(emblem).trim(), created_at: created_at || iso() };
    db.wings.push(w);
    return { ...w };
  }
  function updateWing(id, body) {
    const w = wingById(+id); if (!w) throw notFound(`No wing with id ${id}`);
    for (const k of ["name", "description", "emblem"]) {
      if (body[k] == null) continue;
      const v = clean(body[k]).trim();
      if (k === "name") {
        if (!v) throw bad("A wing needs a name");
        if (db.wings.some((x) => x !== w && x.name.toLowerCase() === v.toLowerCase())) throw bad(`A wing called '${v}' already exists`);
      }
      w[k] = v;
    }
    return { ...w };
  }
  function deleteWing(id) {
    getWing(id);
    db.wings = db.wings.filter((w) => w.id !== +id);
    db.scrolls.forEach((s) => { if (s.wing_id === +id) s.wing_id = null; });
  }
  function wingIdFor(wing, create = true) {
    if (wing == null || wing === "" || wing === 0 || wing === "0") return null;
    if (typeof wing === "number" || /^\d+$/.test(String(wing))) return getWing(+wing).id;
    const found = db.wings.find((w) => w.name.toLowerCase() === String(wing).trim().toLowerCase());
    if (found) return found.id;
    if (!create) throw notFound(`No wing called '${wing}'`);
    return createWing(wing).id;
  }

  // -------------------------------------------------------------- scrolls
  const scrollById = (id) => db.scrolls.find((s) => s.id === +id);
  function mustScroll(id) { const s = scrollById(id); if (!s) throw notFound(`No scroll with id ${id}`); return s; }
  function findByTitle(title) {
    const t = clean(title).split(/\s+/).filter(Boolean).join(" ").toLowerCase();
    return db.scrolls.filter((s) => s.title.toLowerCase() === t).sort((a, b) => a.id - b.id)[0] || null;
  }
  function outlinks(s) {
    const ids = [];
    for (const t of wikilinkTargets(s.content)) {
      const hit = findByTitle(t);
      if (hit && hit.id !== s.id && !ids.includes(hit.id)) ids.push(hit.id);
    }
    return ids;
  }
  function allLinks() {
    const out = [];
    db.scrolls.forEach((s) => outlinks(s).forEach((t) => out.push({ source: s.id, target: t })));
    return out;
  }
  const brief = (s) => ({ id: s.id, title: s.title, kind: s.kind, status: s.status, call_number: callNumber(s.kind, s.id) });
  function shape(s) {
    const w = s.wing_id ? wingById(s.wing_id) : null;
    const p = db.pharos[s.id];
    return {
      ...s, tags: [...s.tags].sort(), call_number: callNumber(s.kind, s.id),
      wing: w ? { id: w.id, name: w.name } : null, due_at: p ? p.due_at : null, in_pharos: !!p,
    };
  }
  function getScroll(id, full = true) {
    const s = mustScroll(id);
    const out = shape(s);
    if (!full) return out;
    const outs = outlinks(s).map(scrollById);
    out.outlinks = outs.map(brief).sort(byTitle);
    out.backlinks = db.scrolls.filter((x) => outlinks(x).includes(s.id)).map(brief).sort(byTitle);
    const linked = new Set(outs.map((x) => x.title.toLowerCase()));
    out.unwritten = wikilinkTargets(s.content).filter((t) => !linked.has(t.toLowerCase()));
    out.marginalia = db.marginalia.filter((m) => m.scroll_id === s.id).sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id - b.id);
    out.revisions = db.palimpsest.filter((r) => r.scroll_id === s.id).length;
    out.pharos = db.pharos[s.id] ? { scroll_id: s.id, ...db.pharos[s.id] } : null;
    out.words = words(s.content).length;
    out.related = related(s.id, 6);
    return out;
  }
  function validate(fields) {
    const out = {};
    for (const key of ["title", "kind", "status", "source_url", "author", "summary", "content", "rating", "wing_id"]) {
      if (!(key in fields)) continue;
      let v = fields[key];
      if (key === "kind") { v = clean(v || "note").toLowerCase(); if (!KINDS[v]) throw bad(`Unknown kind '${v}'`); }
      else if (key === "status") { v = clean(v || "inbox").toLowerCase(); if (!STATUSES.has(v)) throw bad(`Unknown status '${v}'`); }
      else if (key === "rating") {
        if (v == null || v === "" || +v === 0) v = null;
        else { v = Number(v); if (!Number.isInteger(v)) throw bad("Rating must be a whole number from 1 to 5"); if (v < 1 || v > 5) throw bad("Rating must be between 1 and 5"); }
      } else if (key === "wing_id") v = wingIdFor(v);
      else { v = clean(v); if (key === "title") v = v.split(/\s+/).filter(Boolean).join(" "); }
      out[key] = v;
    }
    return out;
  }
  function enrol(id) {
    if (!db.pharos[id]) db.pharos[id] = { due_at: later(1), interval_days: 0, ease: 2.5, repetitions: 0, lapses: 0, last_reviewed: null };
  }
  function addScroll(title, { tags, wing, remember = false, created_at, ...fields } = {}) {
    fields.title = title;
    if (wing !== undefined) fields.wing_id = wing;
    const data = validate(fields);
    if (!data.title) throw bad("A scroll needs a title");
    const stamp = created_at || iso();
    const s = {
      id: ++db.seq.scroll, title: data.title, kind: data.kind || "note", status: data.status || "inbox",
      source_url: data.source_url || "", author: data.author || "", summary: data.summary || "", content: data.content || "",
      rating: data.rating ?? null, wing_id: data.wing_id ?? null, created_at: stamp, updated_at: stamp,
      finished_at: (data.status || "inbox") === "done" ? stamp : null, tags: normaliseTags(tags),
    };
    db.scrolls.push(s);
    if (remember) enrol(s.id);
    return s;
  }
  function updateScroll(id, { tags, wing, ...fields }) {
    const s = mustScroll(id);
    if (wing !== undefined) fields.wing_id = wing;
    const data = validate(fields);
    if ("title" in data && !data.title) throw bad("A scroll needs a title");
    const changed = Object.fromEntries(Object.entries(data).filter(([k, v]) => s[k] !== v));
    if (Object.keys(changed).length) {
      if (["title", "summary", "content"].some((k) => k in changed)) {
        db.palimpsest.push({ id: ++db.seq.revision, scroll_id: s.id, title: s.title, summary: s.summary, content: s.content, created_at: s.updated_at });
      }
      if (changed.status === "done" && !s.finished_at) changed.finished_at = iso();
      else if ("status" in changed && changed.status !== "done") changed.finished_at = null;
      changed.updated_at = iso();
      Object.assign(s, changed);
    }
    if (tags !== undefined && tags !== null) s.tags = normaliseTags(tags);
    return getScroll(s.id);
  }
  function deleteScroll(id) {
    mustScroll(id);
    id = +id;
    db.scrolls = db.scrolls.filter((s) => s.id !== id);
    db.marginalia = db.marginalia.filter((m) => m.scroll_id !== id);
    db.palimpsest = db.palimpsest.filter((r) => r.scroll_id !== id);
    delete db.pharos[id];
  }

  // --------------------------------------------------------------- search
  const FIELDS = [["title", 10], ["author", 4], ["summary", 3], ["content", 1], ["tags", 5], ["marginalia", 2]];
  function docOf(s) {
    return {
      title: fold(s.title), author: fold(s.author), summary: fold(s.summary), content: fold(s.content), tags: fold(s.tags.join(" ")),
      marginalia: fold(db.marginalia.filter((m) => m.scroll_id === s.id).map((m) => `${m.quote} ${m.body}`).join("\n")),
    };
  }
  function parseQuery(query) {
    const filters = {};
    const text = clean(query).replace(/(\w+):("[^"]*"|\S+)/g, (all, key, value) => {
      key = key.toLowerCase();
      if (!["tag", "kind", "status", "wing", "author", "is"].includes(key)) return all;
      (filters[key] = filters[key] || []).push(value.replace(/^"|"$/g, ""));
      return " ";
    });
    return [text.split(/\s+/).filter(Boolean).join(" "), filters];
  }
  function termsOf(text) {
    const phrases = [...text.matchAll(/"([^"]+)"/g)].map((m) => ({ phrase: true, t: fold(m[1].trim()) })).filter((x) => x.t);
    const rest = text.replace(/"[^"]*"/g, " ");
    return [...phrases, ...words(rest).map((w) => ({ phrase: false, t: fold(w) }))];
  }
  const termRe = (term) => term.phrase
    ? new RegExp(reEsc(term.t), "gu")
    : new RegExp(`(?<![\\p{L}\\p{N}_])${reEsc(term.t)}`, "gu");
  function snippet(content, terms) {
    const tokens = content.split(/(\s+)/);
    const hit = (tok) => terms.some((t) => !t.phrase && fold(tok).replace(/^[^\p{L}\p{N}_]+/u, "").startsWith(t.t));
    const first = tokens.findIndex((tok) => tok.trim() && hit(tok));
    if (first < 0) return "";
    const start = Math.max(0, first - 16), end = Math.min(tokens.length, first + 32);
    const body = tokens.slice(start, end).map((tok) => (tok.trim() && hit(tok) ? `\x02${tok}\x03` : tok)).join("");
    return (start > 0 ? "…" : "") + body + (end < tokens.length ? "…" : "");
  }
  function search(q) {
    const [text, filters] = parseQuery(q.q || "");
    const add = (k, v) => { if (v) (filters[k] = filters[k] || []).push(String(v)); };
    add("kind", q.kind); add("status", q.status); add("wing", q.wing); add("tag", q.tag);
    let list = db.scrolls.slice();
    (filters.kind || []).forEach((v) => { list = list.filter((s) => s.kind === v.toLowerCase()); });
    (filters.status || []).forEach((v) => { list = list.filter((s) => s.status === v.toLowerCase()); });
    (filters.author || []).forEach((v) => { list = list.filter((s) => fold(s.author).includes(fold(v))); });
    (filters.wing || []).forEach((v) => {
      list = /^\d+$/.test(v) ? list.filter((s) => s.wing_id === +v)
        : list.filter((s) => s.wing_id && wingById(s.wing_id).name.toLowerCase() === v.toLowerCase());
    });
    (filters.tag || []).forEach((v) => { const t = normaliseTags([v])[0] || v; list = list.filter((s) => s.tags.includes(t)); });
    (filters.is || []).forEach((v) => {
      v = v.toLowerCase();
      if (v === "remembered" || v === "pharos") list = list.filter((s) => db.pharos[s.id]);
      else if (v === "rated") list = list.filter((s) => s.rating != null);
      else if (v === "orphan") {
        const linked = new Set(allLinks().flatMap((l) => [l.source, l.target]));
        list = list.filter((s) => !linked.has(s.id));
      }
    });
    const terms = termsOf(text);
    const scores = new Map();
    if (terms.length) {
      list = list.filter((s) => {
        const doc = docOf(s);
        let score = 0;
        for (const term of terms) {
          const re = termRe(term);
          let matched = false;
          for (const [f, w] of FIELDS) {
            const n = (doc[f].match(re) || []).length;
            if (n) { matched = true; score += w * Math.min(n, 5); }
          }
          if (!matched) return false;
        }
        scores.set(s.id, score);
        return true;
      });
    }
    const sorts = {
      title: (a, b) => byTitle(a, b),
      created: (a, b) => b.created_at.localeCompare(a.created_at) || b.id - a.id,
      oldest: (a, b) => a.created_at.localeCompare(b.created_at) || a.id - b.id,
      rating: (a, b) => (a.rating == null) - (b.rating == null) || (b.rating || 0) - (a.rating || 0) || b.updated_at.localeCompare(a.updated_at),
      updated: (a, b) => b.updated_at.localeCompare(a.updated_at) || b.id - a.id,
    };
    list.sort(sorts[q.sort] || (terms.length ? (a, b) => scores.get(b.id) - scores.get(a.id) || b.updated_at.localeCompare(a.updated_at) : sorts.updated));
    const limit = Math.max(1, Math.min(+q.limit || 50, 500)), offset = Math.max(0, +q.offset || 0);
    const results = list.slice(offset, offset + limit).map((s) => {
      const out = shape(s);
      const snip = terms.length ? snippet(s.content, terms) : "";
      out.excerpt = plain(snip.includes("\x02") ? snip : (s.summary || snip || s.content)).slice(0, 320);
      delete out.content;
      return out;
    });
    return { total: list.length, results, query: q.q || "", filters };
  }
  function titles(q = "", limit = 12) {
    const f = q.toLowerCase();
    return db.scrolls.filter((s) => s.title.toLowerCase().includes(f))
      .sort((a, b) => (b.title.toLowerCase().startsWith(f) - a.title.toLowerCase().startsWith(f)) || b.updated_at.localeCompare(a.updated_at))
      .slice(0, limit).map(brief);
  }
  function related(id, limit = 6) {
    const s = scrollById(id); if (!s) return [];
    const scores = new Map();
    const bump = (k, v) => scores.set(k, (scores.get(k) || 0) + v);
    db.scrolls.forEach((o) => {
      if (o.id === s.id) return;
      const shared = o.tags.filter((t) => s.tags.includes(t)).length;
      if (shared) bump(o.id, 2 * shared);
      if (s.wing_id && o.wing_id === s.wing_id) bump(o.id, 0.5);
    });
    const vocab = [...new Set(words(`${s.title} ${s.summary}`).filter((w) => w.length >= 5).map(fold))].sort((a, b) => b.length - a.length).slice(0, 8);
    if (vocab.length) {
      db.scrolls.filter((o) => o.id !== s.id)
        .map((o) => { const d = docOf(o); const hay = Object.values(d).join(" "); return [o.id, vocab.filter((w) => new RegExp(`(?<![\\p{L}\\p{N}_])${reEsc(w)}(?![\\p{L}\\p{N}_])`, "u").test(hay)).length]; })
        .filter(([, n]) => n).sort((a, b) => b[1] - a[1]).slice(0, 20)
        .forEach(([oid], rank) => bump(oid, 1.5 / (1 + rank * 0.3)));
    }
    const linked = new Set(allLinks().filter((l) => l.source === s.id || l.target === s.id).flatMap((l) => [l.source, l.target]));
    return [...scores.entries()].sort((a, b) => b[1] - a[1]).map(([k]) => k).filter((k) => !linked.has(k)).slice(0, limit).map((k) => brief(scrollById(k)));
  }

  // ------------------------------------------------------------- tags etc
  function listTags() {
    const counts = new Map();
    db.scrolls.forEach((s) => s.tags.forEach((t) => counts.set(t, (counts.get(t) || 0) + 1)));
    return [...counts.entries()].map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
  }
  function renameTag(from, to) {
    const [a] = normaliseTags([from]), [b] = normaliseTags([to]);
    if (!a || !b) throw bad("Both tag names are required");
    const hits = db.scrolls.filter((s) => s.tags.includes(a));
    if (!hits.length) throw notFound(`No tag '${from}'`);
    hits.forEach((s) => { s.tags = normaliseTags(s.tags.map((t) => (t === a ? b : t))); });
  }
  function addMarginalia(id, { body = "", quote = "", kind = "note" }) {
    const s = mustScroll(id);
    kind = clean(kind || "note").toLowerCase();
    if (!MARGINALIA_KINDS.has(kind)) throw bad(`Unknown marginalia kind '${kind}'`);
    if (!clean(body).trim() && !clean(quote).trim()) throw bad("Marginalia need a quote or a note");
    const m = { id: ++db.seq.marginalia, scroll_id: s.id, kind, quote: clean(quote).trim(), body: clean(body).trim(), created_at: iso() };
    db.marginalia.push(m);
    s.updated_at = iso();
    return { ...m };
  }
  function deleteMarginalia(id) {
    if (!db.marginalia.some((m) => m.id === +id)) throw notFound(`No marginalia with id ${id}`);
    db.marginalia = db.marginalia.filter((m) => m.id !== +id);
  }
  function revisions(id) { mustScroll(id); return db.palimpsest.filter((r) => r.scroll_id === +id).sort((a, b) => b.id - a.id).map((r) => ({ ...r })); }
  function restore(revId) {
    const r = db.palimpsest.find((x) => x.id === +revId);
    if (!r) throw notFound(`No revision with id ${revId}`);
    return updateScroll(r.scroll_id, { title: r.title, summary: r.summary, content: r.content });
  }

  // --------------------------------------------------------------- pharos
  function remember(id, on) { mustScroll(id); if (on) enrol(+id); else delete db.pharos[+id]; return getScroll(id); }
  function due(limit = 20) {
    const now = iso();
    return Object.entries(db.pharos).filter(([, p]) => p.due_at <= now).sort((a, b) => a[1].due_at.localeCompare(b[1].due_at)).slice(0, limit)
      .map(([id]) => {
        const s = shape(scrollById(id));
        s.marginalia = db.marginalia.filter((m) => m.scroll_id === +id).sort((a, b) => a.id - b.id);
        return s;
      });
  }
  function review(id, grade) {
    grade = Number(grade);
    if (![0, 1, 2, 3].includes(grade)) throw bad("Grade must be 0 (forgotten), 1 (hazy), 2 (recalled) or 3 (vivid)");
    const p = db.pharos[+id];
    if (!p) throw notFound("That scroll is not kept by the Pharos");
    let { interval_days: interval, ease, repetitions: reps, lapses } = p;
    if (grade === 0) { reps = 0; lapses += 1; interval = 1; ease = Math.max(1.3, ease - 0.2); }
    else {
      if (grade === 1) { interval = Math.max(1, interval * 1.2); ease = Math.max(1.3, ease - 0.15); }
      else if (reps === 0) interval = grade === 2 ? 1 : 4;
      else if (reps === 1) interval = grade === 2 ? 3 : 6;
      else interval = interval * ease * (grade === 3 ? 1.3 : 1);
      if (grade === 3) ease += 0.15;
      reps += 1;
    }
    interval = Math.min(interval, 3650);
    Object.assign(p, { due_at: later(interval), interval_days: interval, ease, repetitions: reps, lapses, last_reviewed: iso() });
    return { scroll_id: +id, ...p };
  }

  // ---------------------------------------------------------- graph, stats
  function graph() {
    const links = allLinks();
    const degree = new Map();
    links.forEach((l) => { degree.set(l.source, (degree.get(l.source) || 0) + 1); degree.set(l.target, (degree.get(l.target) || 0) + 1); });
    const affinities = [];
    for (let i = 0; i < db.scrolls.length; i++) for (let j = i + 1; j < db.scrolls.length; j++) {
      const a = db.scrolls[i], b = db.scrolls[j];
      const w = a.tags.filter((t) => b.tags.includes(t)).length;
      if (w) affinities.push({ source: Math.min(a.id, b.id), target: Math.max(a.id, b.id), weight: w });
    }
    return {
      nodes: db.scrolls.map((s) => ({ id: s.id, title: s.title, kind: s.kind, status: s.status, wing_id: s.wing_id, degree: degree.get(s.id) || 0, call_number: callNumber(s.kind, s.id) })),
      links, affinities,
    };
  }
  function stats() {
    const count = (f) => db.scrolls.reduce((m, s) => { m[s[f]] = (m[s[f]] || 0) + 1; return m; }, {});
    const now = new Date();
    const months = [];
    for (let i = 11; i >= 0; i--) { const d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - i, 1)); months.push(d.toISOString().slice(0, 7)); }
    const since = iso(Date.now() - 364 * DAY).slice(0, 10);
    const activity = {};
    const tick = (stamp) => { if (stamp && stamp.slice(0, 10) >= since) activity[stamp.slice(0, 10)] = (activity[stamp.slice(0, 10)] || 0) + 1; };
    db.scrolls.forEach((s) => { tick(s.created_at); if (s.updated_at !== s.created_at) tick(s.updated_at); });
    db.marginalia.forEach((m) => tick(m.created_at));
    Object.values(db.pharos).forEach((p) => tick(p.last_reviewed));
    const nowIso = iso();
    const tags = listTags();
    return {
      scrolls: db.scrolls.length, wings: db.wings.length, tags: tags.length, links: allLinks().length,
      marginalia: db.marginalia.length, revisions: db.palimpsest.length, remembered: Object.keys(db.pharos).length,
      due: Object.values(db.pharos).filter((p) => p.due_at <= nowIso).length,
      words: db.scrolls.reduce((n, s) => n + words(s.content).length, 0),
      by_kind: count("kind"), by_status: count("status"), top_tags: tags.slice(0, 15),
      monthly: months.map((m) => ({
        month: m, added: db.scrolls.filter((s) => s.created_at.startsWith(m)).length,
        finished: db.scrolls.filter((s) => (s.finished_at || "").startsWith(m)).length,
      })),
      activity,
    };
  }

  // ------------------------------------------------------- import, export
  function exportArchive() {
    return {
      format: "world-knowledge-library", version: 1, exported_at: iso(),
      wings: db.wings.map(({ name, description, emblem, created_at }) => ({ name, description, emblem, created_at })),
      scrolls: db.scrolls.slice().sort((a, b) => a.id - b.id).map((s) => {
        const full = getScroll(s.id);
        const item = {};
        for (const k of ["id", "title", "kind", "status", "source_url", "author", "summary", "content", "rating", "created_at", "updated_at", "finished_at", "tags"]) item[k] = full[k];
        item.wing = full.wing ? full.wing.name : null;
        item.marginalia = full.marginalia.map(({ kind, quote, body, created_at }) => ({ kind, quote, body, created_at }));
        item.pharos = db.pharos[s.id] ? { ...db.pharos[s.id] } : null;
        item.palimpsest = revisions(s.id).map(({ title, summary, content, created_at }) => ({ title, summary, content, created_at }));
        return item;
      }),
    };
  }
  function importArchive(data) {
    if (!data || data.format !== "world-knowledge-library") throw bad("That file is not a World Knowledge Library archive");
    if (+(data.version || 0) > 1) throw bad("That archive was made by a newer version of the library");
    let added = 0, skipped = 0;
    (data.wings || []).forEach((w) => {
      if (!db.wings.some((x) => x.name.toLowerCase() === clean(w.name).toLowerCase())) createWing(w.name, w.description, w.emblem, w.created_at);
    });
    for (const item of data.scrolls || []) {
      const title = clean(item.title).split(/\s+/).filter(Boolean).join(" ");
      if (db.scrolls.some((s) => s.title.toLowerCase() === title.toLowerCase() && s.source_url === clean(item.source_url))) { skipped++; continue; }
      const s = addScroll(item.title, {
        kind: item.kind || "note", status: item.status || "inbox", source_url: item.source_url || "", author: item.author || "",
        summary: item.summary || "", content: item.content || "", rating: item.rating, tags: item.tags || [], wing: item.wing || null,
        created_at: item.created_at,
      });
      s.updated_at = item.updated_at || s.updated_at;
      s.finished_at = item.finished_at || null;
      (item.marginalia || []).forEach((m) => db.marginalia.push({ id: ++db.seq.marginalia, scroll_id: s.id, kind: m.kind || "note", quote: m.quote || "", body: m.body || "", created_at: m.created_at || iso() }));
      (item.palimpsest || []).slice().reverse().forEach((r) => db.palimpsest.push({ id: ++db.seq.revision, scroll_id: s.id, title: r.title, summary: r.summary || "", content: r.content || "", created_at: r.created_at }));
      if (item.pharos) {
        const p = item.pharos;
        db.pharos[s.id] = { due_at: p.due_at, interval_days: p.interval_days || 0, ease: p.ease || 2.5, repetitions: p.repetitions || 0, lapses: p.lapses || 0, last_reviewed: p.last_reviewed || null };
      }
      added++;
    }
    return { added, skipped };
  }

  function guessKind(url) {
    const hints = [
      [/(youtube\.com|youtu\.be|vimeo\.com|ted\.com\/talks)/i, "video"],
      [/(podcasts\.apple\.com|open\.spotify\.com\/(episode|show)|overcast\.fm|pca\.st)/i, "podcast"],
      [/(arxiv\.org|doi\.org|semanticscholar\.org|biorxiv\.org|pubmed|ssrn\.com|\.pdf($|\?))/i, "paper"],
      [/(goodreads\.com|openlibrary\.org|books\.google\.)/i, "book"],
      [/(coursera\.org|edx\.org|udemy\.com|khanacademy\.org)/i, "course"],
      [/(kaggle\.com\/datasets|data\.gov|huggingface\.co\/datasets|zenodo\.org)/i, "dataset"],
    ];
    for (const [re, k] of hints) if (re.test(url)) return k;
    try { return ["", "/"].includes(new URL(url).pathname) ? "website" : "article"; } catch { return "article"; }
  }
  function harborFetch(url) {
    url = clean(url).trim();
    if (!/^https?:\/\//i.test(url)) url = "https://" + url;
    let title = url;
    try {
      const u = new URL(url);
      const last = decodeURIComponent(u.pathname.split("/").filter(Boolean).pop() || "").replace(/[-_]+/g, " ").replace(/\.\w+$/, "").trim();
      title = last ? last[0].toUpperCase() + last.slice(1) : u.hostname;
    } catch { /* keep the raw link */ }
    return {
      url, title, author: "", summary: "", site: "", published: "", excerpt: "", kind: guessKind(url),
      error: "The demo can't read web pages, so it kept the link and guessed a title. The installed library reads the real title, author and description.",
    };
  }

  // -------------------------------------------------------------- routing
  const routes = [];
  const r = (method, pattern, fn, mutates = method !== "GET") => routes.push([method, new RegExp(`^${pattern}$`), fn, mutates]);
  r("GET", "/api/meta", () => ({ ...SEED.meta, version: SEED.version, path: "demo sandbox (this browser)" }));
  r("GET", "/api/stats", () => stats());
  r("GET", "/api/scrolls", (q) => search(q));
  r("POST", "/api/scrolls", (q, b) => {
    const { title = "", tags, wing, remember: rem, created_at, ...fields } = b;
    return getScroll(addScroll(title, { ...fields, tags, wing, remember: !!rem }).id);
  });
  r("GET", "/api/scrolls/(\\d+)", (q, b, id) => getScroll(id));
  r("PATCH", "/api/scrolls/(\\d+)", (q, b, id) => {
    const { id: _i, created_at, updated_at, finished_at, remember: _r, ...rest } = b;
    return updateScroll(id, rest);
  });
  r("DELETE", "/api/scrolls/(\\d+)", (q, b, id) => (deleteScroll(id), { ok: true }));
  r("GET", "/api/scrolls/(\\d+)/revisions", (q, b, id) => revisions(id));
  r("POST", "/api/revisions/(\\d+)/restore", (q, b, id) => restore(id));
  r("POST", "/api/scrolls/(\\d+)/marginalia", (q, b, id) => addMarginalia(id, b));
  r("DELETE", "/api/marginalia/(\\d+)", (q, b, id) => (deleteMarginalia(id), { ok: true }));
  r("POST", "/api/scrolls/(\\d+)/remember", (q, b, id) => remember(id, true));
  r("DELETE", "/api/scrolls/(\\d+)/remember", (q, b, id) => remember(id, false));
  r("GET", "/api/pharos", (q) => due(+q.limit || 50));
  r("POST", "/api/pharos/(\\d+)", (q, b, id) => review(id, b.grade ?? -1));
  r("GET", "/api/titles", (q) => titles(q.q || "", +q.limit || 12));
  r("GET", "/api/random", (q) => {
    const pool = q.status ? db.scrolls.filter((s) => s.status === q.status) : db.scrolls;
    return pool.length ? getScroll(pool[Math.floor(Math.random() * pool.length)].id, false) : null;
  });
  r("GET", "/api/graph", () => graph());
  r("GET", "/api/tags", () => listTags());
  r("POST", "/api/tags/rename", (q, b) => (renameTag(b.from || "", b.to || ""), { ok: true }));
  r("GET", "/api/wings", () => listWings());
  r("POST", "/api/wings", (q, b) => createWing(b.name, b.description, b.emblem));
  r("PATCH", "/api/wings/(\\d+)", (q, b, id) => updateWing(id, b));
  r("DELETE", "/api/wings/(\\d+)", (q, b, id) => (deleteWing(id), { ok: true }));
  r("POST", "/api/harbor/fetch", (q, b) => harborFetch(b.url), false);
  r("GET", "/api/serapeum/export", () => exportArchive());
  r("POST", "/api/serapeum/import", (q, b) => importArchive(b));
  r("POST", "/api/founding", () => ({ added: importArchive(freshen(SEED.archive)).added }));

  function dispatch(method, path, query, body) {
    let allowed = false;
    for (const [m, re, fn, mutates] of routes) {
      const match = path.match(re);
      if (!match) continue;
      allowed = true;
      if (m !== method) continue;
      const snapshot = mutates ? JSON.stringify(db) : null;
      try {
        const data = fn(query, body, ...match.slice(1).map(Number));
        if (mutates) save();
        return [200, data === undefined ? null : data];
      } catch (e) {
        if (snapshot) db = JSON.parse(snapshot); // keep each request all-or-nothing, like a transaction
        if (e instanceof ApiError) return [e.status, { error: e.message }];
        return [400, { error: e.message || String(e) }];
      }
    }
    return allowed ? [405, { error: "Method not allowed" }] : [404, { error: "Not found" }];
  }

  function reset() { db = empty(); importArchive(freshen(SEED.archive)); save(); }

  db = load();
  if (!db) reset();

  const realFetch = window.fetch ? window.fetch.bind(window) : null;
  window.fetch = async function (input, init = {}) {
    const url = typeof input === "string" ? input : input && input.url;
    if (typeof url !== "string" || !url.startsWith("/api/")) {
      if (!realFetch) throw new TypeError("fetch is unavailable");
      return realFetch(input, init);
    }
    const [path, qs = ""] = url.split("?");
    const query = Object.fromEntries(new URLSearchParams(qs));
    let body = {};
    if (init.body) {
      try { body = JSON.parse(init.body); } catch { return new Response(JSON.stringify({ error: "Malformed JSON" }), { status: 400 }); }
    }
    const [status, data] = dispatch((init.method || "GET").toUpperCase(), path, query, body);
    return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
  };

  window.WKL_DEMO = { reset, routing: SEED.routing === "hash" ? "hash" : "memory" };
})();
