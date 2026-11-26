"""The Library: all domain logic for scrolls, wings, links, marginalia and review.

Both the CLI and the web server go through this class, so behaviour stays the
same whichever door you enter by.
"""

from __future__ import annotations

import random
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from . import db
from .catalogue import GRADES, KINDS, MARGINALIA_KINDS, STATUSES, call_number

WIKILINK = re.compile(r"\[\[([^\[\]|#]+?)(?:#[^\[\]|]*)?(?:\|[^\[\]]*)?\]\]")
SCROLL_FIELDS = ("title", "kind", "status", "source_url", "author", "summary",
                 "content", "rating", "wing_id")
FILTER_TOKEN = re.compile(r'(\w+):("[^"]*"|\S+)')


class LibraryError(ValueError):
    """A request the library cannot honour (bad input, missing scroll...)."""


class NotFound(LibraryError):
    pass


def now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def normalise_tags(tags: Iterable[str] | str | None) -> list[str]:
    if tags is None:
        return []
    if isinstance(tags, str):
        tags = tags.split(",") if "," in tags else tags.split()
    seen: dict[str, str] = {}
    for tag in tags:
        tag = str(tag).strip().lstrip("#").strip().lower()
        tag = re.sub(r"\s+", "-", tag)
        if tag and tag not in seen:
            seen[tag] = tag
    return list(seen.values())


def wikilink_targets(text: str) -> list[str]:
    return list(dict.fromkeys(m.group(1).strip() for m in WIKILINK.finditer(text or "")))


def plain(text: str) -> str:
    """Flatten Markdown into readable one-line text for excerpts."""
    text = re.sub(r"\[\[([^\[\]|]+?)\|([^\[\]]+)\]\]", r"\2", text or "")
    text = re.sub(r"\[\[([^\[\]|#]+?)(?:#[^\[\]]*)?\]\]", r"\1", text)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"(?m)^\s{0,3}(#{1,6}\s+|>\s?|[-*+]\s+(\[[ xX]\]\s+)?|\d+[.)]\s+)", "", text)
    text = re.sub(r"(^|\s)#{1,6}\s", r"\1", text)
    text = re.sub(r"(\*\*|__|~~|==|`)", "", text)
    text = re.sub(r"(?<![\w*])[*_](?=\S)([^*_\n]+?)(?<=\S)[*_](?![\w*])", r"\1", text)
    return " ".join(text.split())


def word_count(text: str) -> int:
    return len(re.findall(r"\w+", text or ""))


class Library:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        self.conn = db.connect(path)
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ infra
    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self.conn
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            else:
                self.conn.execute("COMMIT")

    def _q(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(sql, tuple(params)).fetchall()

    def _one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self.conn.execute(sql, tuple(params)).fetchone()

    # ------------------------------------------------------------------ wings
    def list_wings(self) -> list[dict]:
        rows = self._q(
            """SELECT w.*, COUNT(s.id) AS scroll_count
               FROM wings w LEFT JOIN scrolls s ON s.wing_id = w.id
               GROUP BY w.id ORDER BY w.name COLLATE NOCASE"""
        )
        return [dict(r) for r in rows]

    def get_wing(self, wing_id: int) -> dict:
        row = self._one("SELECT * FROM wings WHERE id = ?", (wing_id,))
        if not row:
            raise NotFound(f"No wing with id {wing_id}")
        return dict(row)

    def create_wing(self, name: str, description: str = "", emblem: str = "") -> dict:
        name = (name or "").strip()
        if not name:
            raise LibraryError("A wing needs a name")
        try:
            with self.tx() as c:
                cur = c.execute(
                    "INSERT INTO wings (name, description, emblem, created_at) VALUES (?,?,?,?)",
                    (name, description.strip(), emblem.strip(), iso(now())),
                )
        except sqlite3.IntegrityError:
            raise LibraryError(f"A wing called {name!r} already exists") from None
        return self.get_wing(cur.lastrowid)

    def update_wing(self, wing_id: int, **fields: Any) -> dict:
        self.get_wing(wing_id)
        allowed = {k: str(v).strip() for k, v in fields.items()
                   if k in ("name", "description", "emblem") and v is not None}
        if "name" in allowed and not allowed["name"]:
            raise LibraryError("A wing needs a name")
        if allowed:
            sets = ", ".join(f"{k} = ?" for k in allowed)
            try:
                with self.tx() as c:
                    c.execute(f"UPDATE wings SET {sets} WHERE id = ?", (*allowed.values(), wing_id))
            except sqlite3.IntegrityError:
                raise LibraryError(f"A wing called {allowed['name']!r} already exists") from None
        return self.get_wing(wing_id)

    def delete_wing(self, wing_id: int) -> None:
        self.get_wing(wing_id)
        with self.tx() as c:
            c.execute("DELETE FROM wings WHERE id = ?", (wing_id,))

    def wing_id_for(self, wing: int | str | None, create: bool = True) -> int | None:
        """Resolve a wing given by id or by name (creating it by name if asked)."""
        if wing in (None, "", 0):
            return None
        if isinstance(wing, int) or (isinstance(wing, str) and wing.isdigit()):
            return self.get_wing(int(wing))["id"]
        row = self._one("SELECT id FROM wings WHERE name = ? COLLATE NOCASE", (wing.strip(),))
        if row:
            return row["id"]
        if not create:
            raise NotFound(f"No wing called {wing!r}")
        return self.create_wing(wing)["id"]

    # ---------------------------------------------------------------- scrolls
    def _validate(self, fields: dict) -> dict:
        out: dict[str, Any] = {}
        for key in SCROLL_FIELDS:
            if key not in fields:
                continue
            value = fields[key]
            if key == "kind":
                value = (value or "note").lower()
                if value not in KINDS:
                    raise LibraryError(f"Unknown kind {value!r}; choose from {', '.join(KINDS)}")
            elif key == "status":
                value = (value or "inbox").lower()
                if value not in STATUSES:
                    raise LibraryError(f"Unknown status {value!r}; choose from {', '.join(STATUSES)}")
            elif key == "rating":
                if value in (None, "", 0, "0"):
                    value = None
                else:
                    try:
                        value = int(value)
                    except (TypeError, ValueError):
                        raise LibraryError("Rating must be a whole number from 1 to 5") from None
                    if not 1 <= value <= 5:
                        raise LibraryError("Rating must be between 1 and 5")
            elif key == "wing_id":
                value = self.wing_id_for(value)
            else:
                value = "" if value is None else str(value)
                if key == "title":
                    value = " ".join(value.split())
            out[key] = value
        return out

    def add_scroll(self, title: str, *, tags: Iterable[str] | str | None = None,
                   wing: int | str | None = None, remember: bool = False,
                   created_at: str | None = None, **fields: Any) -> dict:
        fields["title"] = title
        if wing is not None:
            fields["wing_id"] = wing
        data = self._validate(fields)
        if not data.get("title"):
            raise LibraryError("A scroll needs a title")
        data.setdefault("kind", "note")
        data.setdefault("status", "inbox")
        stamp = created_at or iso(now())
        data["created_at"] = data["updated_at"] = stamp
        if data["status"] == "done":
            data["finished_at"] = stamp
        cols = ", ".join(data)
        marks = ", ".join("?" for _ in data)
        with self.tx() as c:
            cur = c.execute(f"INSERT INTO scrolls ({cols}) VALUES ({marks})", tuple(data.values()))
            sid = cur.lastrowid
            self._set_tags(c, sid, normalise_tags(tags))
            self._relink(c, sid)
            self._relink_inbound(c, data["title"])
            if remember:
                self._enrol(c, sid)
            self._reindex(c, sid)
        return self.get_scroll(sid)

    def get_scroll(self, scroll_id: int, *, full: bool = True) -> dict:
        row = self._one(
            """SELECT s.*, w.name AS wing_name, p.due_at AS due_at
               FROM scrolls s
               LEFT JOIN wings w ON w.id = s.wing_id
               LEFT JOIN pharos p ON p.scroll_id = s.id
               WHERE s.id = ?""",
            (scroll_id,),
        )
        if not row:
            raise NotFound(f"No scroll with id {scroll_id}")
        scroll = self._shape(row, self._tags_for([scroll_id]).get(scroll_id, []))
        if not full:
            return scroll
        scroll["outlinks"] = [self._brief(r) for r in self._q(
            """SELECT s.id, s.title, s.kind, s.status FROM links l
               JOIN scrolls s ON s.id = l.to_id WHERE l.from_id = ?
               ORDER BY s.title COLLATE NOCASE""", (scroll_id,))]
        scroll["backlinks"] = [self._brief(r) for r in self._q(
            """SELECT s.id, s.title, s.kind, s.status FROM links l
               JOIN scrolls s ON s.id = l.from_id WHERE l.to_id = ?
               ORDER BY s.title COLLATE NOCASE""", (scroll_id,))]
        linked = {s["title"].lower() for s in scroll["outlinks"]}
        scroll["unwritten"] = [t for t in wikilink_targets(scroll["content"])
                               if t.lower() not in linked]
        scroll["marginalia"] = [dict(r) for r in self._q(
            "SELECT * FROM marginalia WHERE scroll_id = ? ORDER BY created_at, id", (scroll_id,))]
        scroll["revisions"] = self._one(
            "SELECT COUNT(*) FROM palimpsest WHERE scroll_id = ?", (scroll_id,))[0]
        pharos = self._one("SELECT * FROM pharos WHERE scroll_id = ?", (scroll_id,))
        scroll["pharos"] = dict(pharos) if pharos else None
        scroll["words"] = word_count(scroll["content"])
        scroll["related"] = self.related(scroll_id, limit=6)
        return scroll

    def update_scroll(self, scroll_id: int, *, tags: Iterable[str] | str | None = None,
                      wing: int | str | None = None, **fields: Any) -> dict:
        current = self._one("SELECT * FROM scrolls WHERE id = ?", (scroll_id,))
        if not current:
            raise NotFound(f"No scroll with id {scroll_id}")
        if wing is not None:
            fields["wing_id"] = wing
        data = self._validate(fields)
        if "title" in data and not data["title"]:
            raise LibraryError("A scroll needs a title")
        changed = {k: v for k, v in data.items() if current[k] != v}
        with self.tx() as c:
            if changed:
                if any(k in changed for k in ("title", "summary", "content")):
                    c.execute(
                        """INSERT INTO palimpsest (scroll_id, title, summary, content, created_at)
                           VALUES (?,?,?,?,?)""",
                        (scroll_id, current["title"], current["summary"], current["content"],
                         current["updated_at"]),
                    )
                if changed.get("status") == "done" and not current["finished_at"]:
                    changed["finished_at"] = iso(now())
                elif "status" in changed and changed["status"] != "done":
                    changed["finished_at"] = None
                changed["updated_at"] = iso(now())
                sets = ", ".join(f"{k} = ?" for k in changed)
                c.execute(f"UPDATE scrolls SET {sets} WHERE id = ?", (*changed.values(), scroll_id))
            if tags is not None:
                self._set_tags(c, scroll_id, normalise_tags(tags))
            if "content" in changed:
                self._relink(c, scroll_id)
            if "title" in changed:
                self._relink_inbound(c, changed["title"])
                self._relink_inbound(c, current["title"])
            self._reindex(c, scroll_id)
        return self.get_scroll(scroll_id)

    def delete_scroll(self, scroll_id: int) -> None:
        row = self._one("SELECT id FROM scrolls WHERE id = ?", (scroll_id,))
        if not row:
            raise NotFound(f"No scroll with id {scroll_id}")
        with self.tx() as c:
            c.execute("DELETE FROM scrolls WHERE id = ?", (scroll_id,))
            c.execute("DELETE FROM scrolls_fts WHERE rowid = ?", (scroll_id,))
            c.execute("DELETE FROM tags WHERE id NOT IN (SELECT tag_id FROM scroll_tags)")

    def find_by_title(self, title: str) -> dict | None:
        row = self._one("SELECT id FROM scrolls WHERE title = ? COLLATE NOCASE ORDER BY id LIMIT 1",
                        (" ".join(title.split()),))
        return self.get_scroll(row["id"], full=False) if row else None

    # --------------------------------------------------------- shaping helpers
    def _tags_for(self, ids: list[int]) -> dict[int, list[str]]:
        if not ids:
            return {}
        out: dict[int, list[str]] = {i: [] for i in ids}
        marks = ",".join("?" for _ in ids)
        for r in self._q(
            f"""SELECT st.scroll_id, t.name FROM scroll_tags st JOIN tags t ON t.id = st.tag_id
                WHERE st.scroll_id IN ({marks}) ORDER BY t.name""", ids):
            out[r["scroll_id"]].append(r["name"])
        return out

    @staticmethod
    def _shape(row: sqlite3.Row, tags: list[str]) -> dict:
        s = dict(row)
        s["call_number"] = call_number(s["kind"], s["id"])
        s["tags"] = tags
        s["wing"] = {"id": s["wing_id"], "name": s.pop("wing_name")} if s["wing_id"] else None
        s["in_pharos"] = s.get("due_at") is not None
        return s

    @staticmethod
    def _brief(row: sqlite3.Row) -> dict:
        b = dict(row)
        b["call_number"] = call_number(b["kind"], b["id"])
        return b

    # ------------------------------------------------------- tags, links, fts
    def _set_tags(self, c: sqlite3.Connection, sid: int, tags: list[str]) -> None:
        c.execute("DELETE FROM scroll_tags WHERE scroll_id = ?", (sid,))
        for tag in tags:
            c.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag,))
            tid = c.execute("SELECT id FROM tags WHERE name = ?", (tag,)).fetchone()[0]
            c.execute("INSERT OR IGNORE INTO scroll_tags VALUES (?, ?)", (sid, tid))
        c.execute("DELETE FROM tags WHERE id NOT IN (SELECT tag_id FROM scroll_tags)")

    def _relink(self, c: sqlite3.Connection, sid: int) -> None:
        content = c.execute("SELECT content FROM scrolls WHERE id = ?", (sid,)).fetchone()[0]
        c.execute("DELETE FROM links WHERE from_id = ?", (sid,))
        for target in wikilink_targets(content):
            row = c.execute(
                "SELECT id FROM scrolls WHERE title = ? COLLATE NOCASE ORDER BY id LIMIT 1",
                (target,)).fetchone()
            if row and row[0] != sid:
                c.execute("INSERT OR IGNORE INTO links VALUES (?, ?)", (sid, row[0]))

    def _relink_inbound(self, c: sqlite3.Connection, title: str) -> None:
        """Re-resolve links in every scroll that mentions ``[[title]]``."""
        like = "%[[" + title.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        for row in c.execute("SELECT id FROM scrolls WHERE content LIKE ? ESCAPE '\\'",
                             (like,)).fetchall():
            self._relink(c, row[0])

    def _reindex(self, c: sqlite3.Connection, sid: int) -> None:
        s = c.execute("SELECT title, author, summary, content FROM scrolls WHERE id = ?",
                      (sid,)).fetchone()
        tags = " ".join(r[0] for r in c.execute(
            "SELECT t.name FROM scroll_tags st JOIN tags t ON t.id = st.tag_id WHERE st.scroll_id = ?",
            (sid,)))
        notes = "\n".join(f"{r[0]} {r[1]}" for r in c.execute(
            "SELECT quote, body FROM marginalia WHERE scroll_id = ?", (sid,)))
        c.execute("DELETE FROM scrolls_fts WHERE rowid = ?", (sid,))
        c.execute(
            "INSERT INTO scrolls_fts (rowid, title, author, summary, content, tags, marginalia)"
            " VALUES (?,?,?,?,?,?,?)",
            (sid, s["title"], s["author"], s["summary"], s["content"], tags, notes))

    def rebuild_index(self) -> int:
        with self.tx() as c:
            c.execute("DELETE FROM scrolls_fts")
            ids = [r[0] for r in c.execute("SELECT id FROM scrolls")]
            for sid in ids:
                self._relink(c, sid)
                self._reindex(c, sid)
        return len(ids)

    # ----------------------------------------------------------------- search
    @staticmethod
    def parse_query(query: str) -> tuple[str, dict[str, list[str]]]:
        """Split ``"stoic tag:philosophy kind:book"`` into free text and filters."""
        filters: dict[str, list[str]] = {}

        def grab(m: re.Match) -> str:
            key = m.group(1).lower()
            if key not in ("tag", "kind", "status", "wing", "author", "is"):
                return m.group(0)
            filters.setdefault(key, []).append(m.group(2).strip('"'))
            return " "

        text = FILTER_TOKEN.sub(grab, query or "")
        return " ".join(text.split()), filters

    @staticmethod
    def fts_expression(text: str) -> str:
        phrases = re.findall(r'"([^"]+)"', text)
        rest = re.sub(r'"[^"]*"', " ", text)
        terms = [f'"{p.replace(chr(34), "")}"' for p in phrases]
        for word in re.findall(r"\w+", rest):
            terms.append(f'"{word}"*')
        return " AND ".join(terms)

    def search(self, query: str = "", *, kind: str | None = None, status: str | None = None,
               wing: int | str | None = None, tag: str | None = None, sort: str = "",
               limit: int = 50, offset: int = 0) -> dict:
        text, filters = self.parse_query(query)
        where: list[str] = []
        params: list[Any] = []
        for value in filters.get("kind", []) + ([kind] if kind else []):
            where.append("s.kind = ?")
            params.append(value.lower())
        for value in filters.get("status", []) + ([status] if status else []):
            where.append("s.status = ?")
            params.append(value.lower())
        for value in filters.get("author", []):
            where.append("s.author LIKE ?")
            params.append(f"%{value}%")
        for value in filters.get("wing", []) + ([str(wing)] if wing else []):
            if value.isdigit():
                where.append("s.wing_id = ?")
                params.append(int(value))
            else:
                where.append("s.wing_id IN (SELECT id FROM wings WHERE name = ? COLLATE NOCASE)")
                params.append(value)
        for value in filters.get("tag", []) + ([tag] if tag else []):
            where.append("""s.id IN (SELECT st.scroll_id FROM scroll_tags st
                            JOIN tags t ON t.id = st.tag_id WHERE t.name = ?)""")
            params.append(normalise_tags([value])[0] if normalise_tags([value]) else value)
        for value in filters.get("is", []):
            value = value.lower()
            if value in ("remembered", "pharos"):
                where.append("p.scroll_id IS NOT NULL")
            elif value == "orphan":
                where.append("""s.id NOT IN (SELECT from_id FROM links)
                                AND s.id NOT IN (SELECT to_id FROM links)""")
            elif value == "rated":
                where.append("s.rating IS NOT NULL")

        expr = self.fts_expression(text)
        select = """SELECT s.*, w.name AS wing_name, p.due_at AS due_at{extra}
                    FROM scrolls s
                    LEFT JOIN wings w ON w.id = s.wing_id
                    LEFT JOIN pharos p ON p.scroll_id = s.id {join}"""
        if expr:
            select = select.format(
                extra=", snippet(scrolls_fts, 3, char(2), char(3), '…', 24) AS snippet,"
                      " bm25(scrolls_fts, 10.0, 4.0, 3.0, 1.0, 5.0, 2.0) AS score",
                join="JOIN scrolls_fts f ON f.rowid = s.id")
            where.insert(0, "scrolls_fts MATCH ?")
            params.insert(0, expr)
        else:
            select = select.format(extra="", join="")
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        order = {
            "title": "s.title COLLATE NOCASE ASC",
            "created": "s.created_at DESC, s.id DESC",
            "oldest": "s.created_at ASC, s.id ASC",
            "rating": "s.rating IS NULL, s.rating DESC, s.updated_at DESC",
            "updated": "s.updated_at DESC, s.id DESC",
        }.get(sort, "score ASC" if expr else "s.updated_at DESC, s.id DESC")
        limit = max(1, min(int(limit), 500))
        with self._lock:
            try:
                total = self.conn.execute(
                    f"SELECT COUNT(*) FROM ({select}{clause})", params).fetchone()[0]
                rows = self.conn.execute(
                    f"{select}{clause} ORDER BY {order} LIMIT ? OFFSET ?",
                    (*params, limit, max(0, int(offset)))).fetchall()
            except sqlite3.OperationalError as exc:
                raise LibraryError(f"Could not understand that search: {exc}") from None
        tags = self._tags_for([r["id"] for r in rows])
        results = []
        for r in rows:
            s = self._shape(r, tags.get(r["id"], []))
            snip = s.pop("snippet", None) or ""
            s["excerpt"] = plain(snip if "\x02" in snip else (s["summary"] or snip or s["content"]))[:320]
            s.pop("content", None)
            results.append(s)
        return {"total": total, "results": results, "query": query, "filters": filters}

    def titles(self, prefix: str = "", limit: int = 12) -> list[dict]:
        rows = self._q(
            """SELECT id, title, kind, status FROM scrolls WHERE title LIKE ? ESCAPE '\\'
               ORDER BY title LIKE ? ESCAPE '\\' DESC, updated_at DESC LIMIT ?""",
            (f"%{self._like(prefix)}%", f"{self._like(prefix)}%", limit))
        return [self._brief(r) for r in rows]

    @staticmethod
    def _like(value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def related(self, scroll_id: int, limit: int = 6) -> list[dict]:
        """Scrolls that share tags, wing or vocabulary with this one (not already linked)."""
        s = self._one("SELECT title, summary, wing_id FROM scrolls WHERE id = ?", (scroll_id,))
        if not s:
            return []
        scores: dict[int, float] = {}
        for r in self._q(
            """SELECT b.scroll_id, COUNT(*) AS shared FROM scroll_tags a
               JOIN scroll_tags b ON a.tag_id = b.tag_id AND b.scroll_id != a.scroll_id
               WHERE a.scroll_id = ? GROUP BY b.scroll_id""", (scroll_id,)):
            scores[r["scroll_id"]] = scores.get(r["scroll_id"], 0) + 2.0 * r["shared"]
        if s["wing_id"]:
            for r in self._q("SELECT id FROM scrolls WHERE wing_id = ? AND id != ?",
                             (s["wing_id"], scroll_id)):
                scores[r["id"]] = scores.get(r["id"], 0) + 0.5
        words = sorted({w.lower() for w in re.findall(r"\w{5,}", f"{s['title']} {s['summary']}")},
                       key=len, reverse=True)[:8]
        if words:
            expr = " OR ".join(f'"{w}"' for w in words)
            try:
                for rank, r in enumerate(self._q(
                        "SELECT rowid FROM scrolls_fts WHERE scrolls_fts MATCH ? AND rowid != ?"
                        " ORDER BY rank LIMIT 20", (expr, scroll_id))):
                    scores[r["rowid"]] = scores.get(r["rowid"], 0) + 1.5 / (1 + rank * 0.3)
            except sqlite3.OperationalError:
                pass
        linked = {r[0] for r in self._q(
            "SELECT to_id FROM links WHERE from_id = ? UNION SELECT from_id FROM links WHERE to_id = ?",
            (scroll_id, scroll_id))}
        best = [i for i, _ in sorted(scores.items(), key=lambda kv: -kv[1]) if i not in linked][:limit]
        if not best:
            return []
        marks = ",".join("?" for _ in best)
        rows = {r["id"]: r for r in self._q(
            f"SELECT id, title, kind, status FROM scrolls WHERE id IN ({marks})", best)}
        return [self._brief(rows[i]) for i in best if i in rows]

    def random_scroll(self, status: str | None = None) -> dict | None:
        sql = "SELECT id FROM scrolls" + (" WHERE status = ?" if status else "")
        ids = [r[0] for r in self._q(sql, (status,) if status else ())]
        return self.get_scroll(random.choice(ids), full=False) if ids else None

    # ------------------------------------------------------------- tags list
    def list_tags(self) -> list[dict]:
        return [dict(r) for r in self._q(
            """SELECT t.name, COUNT(st.scroll_id) AS count FROM tags t
               JOIN scroll_tags st ON st.tag_id = t.id GROUP BY t.id
               ORDER BY count DESC, t.name""")]

    def rename_tag(self, old: str, new: str) -> None:
        old_n, new_n = normalise_tags([old]), normalise_tags([new])
        if not old_n or not new_n:
            raise LibraryError("Both tag names are required")
        with self.tx() as c:
            src = c.execute("SELECT id FROM tags WHERE name = ?", (old_n[0],)).fetchone()
            if not src:
                raise NotFound(f"No tag {old!r}")
            ids = [r[0] for r in c.execute("SELECT scroll_id FROM scroll_tags WHERE tag_id = ?",
                                           (src[0],))]
            c.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (new_n[0],))
            dst = c.execute("SELECT id FROM tags WHERE name = ?", (new_n[0],)).fetchone()[0]
            for sid in ids:
                c.execute("INSERT OR IGNORE INTO scroll_tags VALUES (?, ?)", (sid, dst))
            if dst != src[0]:
                c.execute("DELETE FROM scroll_tags WHERE tag_id = ?", (src[0],))
                c.execute("DELETE FROM tags WHERE id = ?", (src[0],))
            for sid in ids:
                self._reindex(c, sid)

    # -------------------------------------------------------------- marginalia
    def add_marginalia(self, scroll_id: int, body: str = "", *, quote: str = "",
                       kind: str = "note") -> dict:
        self.get_scroll(scroll_id, full=False)
        kind = (kind or "note").lower()
        if kind not in MARGINALIA_KINDS:
            raise LibraryError(f"Unknown marginalia kind {kind!r}")
        if not (body or "").strip() and not (quote or "").strip():
            raise LibraryError("Marginalia need a quote or a note")
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO marginalia (scroll_id, kind, quote, body, created_at) VALUES (?,?,?,?,?)",
                (scroll_id, kind, (quote or "").strip(), (body or "").strip(), iso(now())))
            c.execute("UPDATE scrolls SET updated_at = ? WHERE id = ?", (iso(now()), scroll_id))
            self._reindex(c, scroll_id)
        return dict(self._one("SELECT * FROM marginalia WHERE id = ?", (cur.lastrowid,)))

    def delete_marginalia(self, marginalia_id: int) -> None:
        row = self._one("SELECT scroll_id FROM marginalia WHERE id = ?", (marginalia_id,))
        if not row:
            raise NotFound(f"No marginalia with id {marginalia_id}")
        with self.tx() as c:
            c.execute("DELETE FROM marginalia WHERE id = ?", (marginalia_id,))
            self._reindex(c, row["scroll_id"])

    # -------------------------------------------------------------- palimpsest
    def revisions(self, scroll_id: int) -> list[dict]:
        self.get_scroll(scroll_id, full=False)
        return [dict(r) for r in self._q(
            "SELECT * FROM palimpsest WHERE scroll_id = ? ORDER BY id DESC", (scroll_id,))]

    def restore_revision(self, revision_id: int) -> dict:
        rev = self._one("SELECT * FROM palimpsest WHERE id = ?", (revision_id,))
        if not rev:
            raise NotFound(f"No revision with id {revision_id}")
        return self.update_scroll(rev["scroll_id"], title=rev["title"], summary=rev["summary"],
                                  content=rev["content"])

    # ------------------------------------------------------------------ pharos
    def _enrol(self, c: sqlite3.Connection, sid: int) -> None:
        c.execute("INSERT OR IGNORE INTO pharos (scroll_id, due_at) VALUES (?, ?)",
                  (sid, iso(now() + timedelta(days=1))))

    def remember(self, scroll_id: int, on: bool = True) -> dict:
        self.get_scroll(scroll_id, full=False)
        with self.tx() as c:
            if on:
                self._enrol(c, scroll_id)
            else:
                c.execute("DELETE FROM pharos WHERE scroll_id = ?", (scroll_id,))
        return self.get_scroll(scroll_id)

    def due(self, limit: int = 20, at: datetime | None = None) -> list[dict]:
        rows = self._q(
            """SELECT s.*, w.name AS wing_name, p.due_at AS due_at FROM pharos p
               JOIN scrolls s ON s.id = p.scroll_id LEFT JOIN wings w ON w.id = s.wing_id
               WHERE p.due_at <= ? ORDER BY p.due_at LIMIT ?""",
            (iso(at or now()), limit))
        tags = self._tags_for([r["id"] for r in rows])
        out = []
        for r in rows:
            s = self._shape(r, tags.get(r["id"], []))
            s["marginalia"] = [dict(m) for m in self._q(
                "SELECT * FROM marginalia WHERE scroll_id = ? ORDER BY id", (r["id"],))]
            out.append(s)
        return out

    def review(self, scroll_id: int, grade: int, at: datetime | None = None) -> dict:
        """Record how well a scroll was remembered and schedule its next visit."""
        if grade not in GRADES:
            raise LibraryError("Grade must be 0 (forgotten), 1 (hazy), 2 (recalled) or 3 (vivid)")
        p = self._one("SELECT * FROM pharos WHERE scroll_id = ?", (scroll_id,))
        if not p:
            raise NotFound("That scroll is not kept by the Pharos")
        interval, ease, reps, lapses = p["interval_days"], p["ease"], p["repetitions"], p["lapses"]
        if grade == 0:
            reps, lapses, interval, ease = 0, lapses + 1, 1.0, max(1.3, ease - 0.2)
        else:
            if grade == 1:
                interval = max(1.0, interval * 1.2)
                ease = max(1.3, ease - 0.15)
            elif reps == 0:
                interval = 1.0 if grade == 2 else 4.0
            elif reps == 1:
                interval = 3.0 if grade == 2 else 6.0
            else:
                interval = interval * ease * (1.3 if grade == 3 else 1.0)
            if grade == 3:
                ease += 0.15
            reps += 1
        interval = min(interval, 3650.0)
        when = at or now()
        due_at = iso(when + timedelta(days=interval))
        with self.tx() as c:
            c.execute(
                """UPDATE pharos SET due_at = ?, interval_days = ?, ease = ?, repetitions = ?,
                   lapses = ?, last_reviewed = ? WHERE scroll_id = ?""",
                (due_at, interval, ease, reps, lapses, iso(when), scroll_id))
        return dict(self._one("SELECT * FROM pharos WHERE scroll_id = ?", (scroll_id,)))

    # ------------------------------------------------------------------- graph
    def graph(self) -> dict:
        nodes = [dict(r) | {"call_number": call_number(r["kind"], r["id"])} for r in self._q(
            """SELECT s.id, s.title, s.kind, s.status, s.wing_id,
                      (SELECT COUNT(*) FROM links WHERE from_id = s.id OR to_id = s.id) AS degree
               FROM scrolls s""")]
        edges = [dict(r) for r in self._q("SELECT from_id AS source, to_id AS target FROM links")]
        tag_edges = [dict(r) for r in self._q(
            """SELECT a.scroll_id AS source, b.scroll_id AS target, COUNT(*) AS weight
               FROM scroll_tags a JOIN scroll_tags b
                 ON a.tag_id = b.tag_id AND a.scroll_id < b.scroll_id
               GROUP BY a.scroll_id, b.scroll_id""")]
        return {"nodes": nodes, "links": edges, "affinities": tag_edges}

    # ------------------------------------------------------------------- stats
    def stats(self) -> dict:
        one = lambda sql, p=(): self._one(sql, p)[0]  # noqa: E731
        by = lambda col: {r[0]: r[1] for r in self._q(  # noqa: E731
            f"SELECT {col}, COUNT(*) FROM scrolls GROUP BY {col}")}
        words = sum(word_count(r[0]) for r in self._q("SELECT content FROM scrolls"))
        months = []
        start = now().replace(day=1, hour=0, minute=0, second=0)
        for i in range(11, -1, -1):
            y, m = start.year, start.month - i
            while m <= 0:
                y, m = y - 1, m + 12
            months.append(f"{y:04d}-{m:02d}")
        added = {r[0]: r[1] for r in self._q(
            "SELECT substr(created_at, 1, 7), COUNT(*) FROM scrolls GROUP BY 1")}
        finished = {r[0]: r[1] for r in self._q(
            "SELECT substr(finished_at, 1, 7), COUNT(*) FROM scrolls"
            " WHERE finished_at IS NOT NULL GROUP BY 1")}
        since = iso(now() - timedelta(days=364))[:10]
        activity = {r[0]: r[1] for r in self._q(
            """SELECT d, COUNT(*) FROM (
                 SELECT substr(created_at, 1, 10) AS d FROM scrolls
                 UNION ALL SELECT substr(updated_at, 1, 10) FROM scrolls WHERE updated_at != created_at
                 UNION ALL SELECT substr(created_at, 1, 10) FROM marginalia
                 UNION ALL SELECT substr(last_reviewed, 1, 10) FROM pharos WHERE last_reviewed IS NOT NULL
               ) WHERE d >= ? GROUP BY d""", (since,))}
        return {
            "scrolls": one("SELECT COUNT(*) FROM scrolls"),
            "wings": one("SELECT COUNT(*) FROM wings"),
            "tags": one("SELECT COUNT(*) FROM tags"),
            "links": one("SELECT COUNT(*) FROM links"),
            "marginalia": one("SELECT COUNT(*) FROM marginalia"),
            "revisions": one("SELECT COUNT(*) FROM palimpsest"),
            "remembered": one("SELECT COUNT(*) FROM pharos"),
            "due": one("SELECT COUNT(*) FROM pharos WHERE due_at <= ?", (iso(now()),)),
            "words": words,
            "by_kind": by("kind"),
            "by_status": by("status"),
            "top_tags": self.list_tags()[:15],
            "monthly": [{"month": m, "added": added.get(m, 0), "finished": finished.get(m, 0)}
                        for m in months],
            "activity": activity,
        }
