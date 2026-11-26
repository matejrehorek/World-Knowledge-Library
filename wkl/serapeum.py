"""The Serapeum: copies of the library kept outside it.

When the great Library ran out of room, a "daughter library" was founded in the
temple of Serapis. Here the Serapeum is everything that carries knowledge in or
out of the library in open formats:

* a complete JSON archive (lossless, re-importable),
* a folder of Markdown files with front matter (readable anywhere, Obsidian-friendly),
* importing such folders back, so existing notes can be brought in.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .catalogue import KINDS, STATUSES
from .library import Library, LibraryError, iso, now

FORMAT = "world-knowledge-library"
FORMAT_VERSION = 1
FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.S)


# ----------------------------------------------------------------- JSON
def export_json(lib: Library, *, include_history: bool = True) -> dict:
    wings = [{k: w[k] for k in ("name", "description", "emblem", "created_at")}
             for w in lib.list_wings()]
    scrolls = []
    for row in lib._q("SELECT id FROM scrolls ORDER BY id"):
        s = lib.get_scroll(row["id"])
        item = {k: s[k] for k in ("id", "title", "kind", "status", "source_url", "author",
                                  "summary", "content", "rating", "created_at", "updated_at",
                                  "finished_at", "tags")}
        item["wing"] = s["wing"]["name"] if s["wing"] else None
        item["marginalia"] = [{k: m[k] for k in ("kind", "quote", "body", "created_at")}
                              for m in s["marginalia"]]
        item["pharos"] = ({k: v for k, v in s["pharos"].items() if k != "scroll_id"}
                          if s["pharos"] else None)
        if include_history:
            item["palimpsest"] = [{k: r[k] for k in ("title", "summary", "content", "created_at")}
                                  for r in lib.revisions(s["id"])]
        scrolls.append(item)
    return {"format": FORMAT, "version": FORMAT_VERSION, "exported_at": iso(now()),
            "wings": wings, "scrolls": scrolls}


def import_json(lib: Library, data: dict | str) -> dict:
    """Merge an archive into the library. Scrolls already present are skipped."""
    if isinstance(data, str):
        data = json.loads(data)
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise LibraryError("That file is not a World Knowledge Library archive")
    if int(data.get("version", 0)) > FORMAT_VERSION:
        raise LibraryError("That archive was made by a newer version of the library")
    added = skipped = 0
    for w in data.get("wings", []):
        try:
            lib.wing_id_for(w["name"], create=False)
        except LibraryError:
            lib.create_wing(w["name"], w.get("description", ""), w.get("emblem", ""))
    for item in data.get("scrolls", []):
        if _exists(lib, item.get("title", ""), item.get("source_url", "")):
            skipped += 1
            continue
        s = lib.add_scroll(
            item["title"], kind=item.get("kind", "note"), status=item.get("status", "inbox"),
            source_url=item.get("source_url", ""), author=item.get("author", ""),
            summary=item.get("summary", ""), content=item.get("content", ""),
            rating=item.get("rating"), tags=item.get("tags", []), wing=item.get("wing"),
            created_at=item.get("created_at"))
        with lib.tx() as c:
            c.execute("UPDATE scrolls SET updated_at = ?, finished_at = ? WHERE id = ?",
                      (item.get("updated_at") or s["updated_at"], item.get("finished_at"), s["id"]))
            for m in item.get("marginalia", []):
                c.execute("INSERT INTO marginalia (scroll_id, kind, quote, body, created_at)"
                          " VALUES (?,?,?,?,?)",
                          (s["id"], m.get("kind", "note"), m.get("quote", ""), m.get("body", ""),
                           m.get("created_at") or iso(now())))
            for r in reversed(item.get("palimpsest", [])):
                c.execute("INSERT INTO palimpsest (scroll_id, title, summary, content, created_at)"
                          " VALUES (?,?,?,?,?)",
                          (s["id"], r["title"], r.get("summary", ""), r.get("content", ""),
                           r["created_at"]))
            p = item.get("pharos")
            if p:
                c.execute("""INSERT OR REPLACE INTO pharos (scroll_id, due_at, interval_days, ease,
                             repetitions, lapses, last_reviewed) VALUES (?,?,?,?,?,?,?)""",
                          (s["id"], p["due_at"], p.get("interval_days", 0), p.get("ease", 2.5),
                           p.get("repetitions", 0), p.get("lapses", 0), p.get("last_reviewed")))
        added += 1
    lib.rebuild_index()
    return {"added": added, "skipped": skipped}


def _exists(lib: Library, title: str, source_url: str) -> bool:
    title = " ".join(title.split())
    return lib._one("SELECT 1 FROM scrolls WHERE title = ? COLLATE NOCASE AND source_url = ?",
                    (title, source_url or "")) is not None


# ------------------------------------------------------------- Markdown
def slugify(text: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^\w\s-]", "", text, flags=re.U).strip().lower()
    slug = re.sub(r"[\s_-]+", "-", slug)
    return slug[:max_len].strip("-") or "untitled"


def _yaml_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "[" + ", ".join(_yaml_value(v) for v in value) + "]"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text == "" or re.search(r"[:#\[\]{},\"'&*!|>%@`]|^\s|\s$", text):
        return json.dumps(text, ensure_ascii=False)
    return text


def scroll_to_markdown(s: dict) -> str:
    meta = {
        "title": s["title"], "call_number": s["call_number"], "kind": s["kind"],
        "status": s["status"], "author": s["author"] or None, "source": s["source_url"] or None,
        "wing": s["wing"]["name"] if s["wing"] else None, "tags": s["tags"] or None,
        "rating": s["rating"], "created": s["created_at"], "updated": s["updated_at"],
        "finished": s["finished_at"],
    }
    lines = ["---"] + [f"{k}: {_yaml_value(v)}" for k, v in meta.items() if v not in (None, "")]
    lines += ["---", "", f"# {s['title']}", ""]
    if s["summary"]:
        lines += ["> " + line for line in s["summary"].splitlines()] + [""]
    if s["content"]:
        lines += [s["content"].rstrip(), ""]
    if s.get("marginalia"):
        lines += ["## Marginalia", ""]
        for m in s["marginalia"]:
            if m["quote"]:
                lines.append(f"- **{m['kind']}**: “{m['quote']}”" + (f" — {m['body']}" if m["body"] else ""))
            else:
                lines.append(f"- **{m['kind']}**: {m['body']}")
        lines.append("")
    return "\n".join(lines)


def export_markdown(lib: Library, directory: str | Path) -> int:
    out = Path(directory).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    count = 0
    for row in lib._q("SELECT id FROM scrolls ORDER BY id"):
        s = lib.get_scroll(row["id"])
        folder = out / slugify(s["wing"]["name"]) if s["wing"] else out
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{s['call_number']} {slugify(s['title'])}.md").write_text(
            scroll_to_markdown(s), encoding="utf-8")
        count += 1
    return count


def parse_front_matter(text: str) -> tuple[dict, str]:
    m = FRONT_MATTER.match(text)
    if not m:
        return {}, text
    meta: dict[str, Any] = {}
    current_list: str | None = None
    for raw in m.group(1).splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        item = re.match(r"^\s*-\s+(.*)$", line)
        if item and current_list:
            meta[current_list].append(_scalar(item.group(1)))
            continue
        kv = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if not kv:
            continue
        key, value = kv.group(1).lower(), kv.group(2).strip()
        if value == "":
            meta[key] = []
            current_list = key
            continue
        current_list = None
        if value.startswith("[") and value.endswith("]"):
            meta[key] = [_scalar(v) for v in _split_list(value[1:-1])]
        else:
            meta[key] = _scalar(value)
    return meta, text[m.end():]


def _split_list(body: str) -> list[str]:
    parts, buf, quote = [], "", ""
    for ch in body:
        if quote:
            buf += ch
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            buf += ch
        elif ch == ",":
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    parts.append(buf)
    return [p.strip() for p in parts if p.strip()]


def _scalar(value: str) -> Any:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        if value[0] == '"':
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                pass
        return value[1:-1]
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return value


def markdown_to_fields(text: str, fallback_title: str) -> dict:
    meta, body = parse_front_matter(text)
    body = body.lstrip("\n")
    title = meta.get("title")
    heading = re.match(r"^#\s+(.+?)\s*\n", body)
    if heading and (not title or heading.group(1).strip() == str(title).strip()):
        title = title or heading.group(1).strip()
        body = body[heading.end():].lstrip("\n")
    summary = meta.get("summary", "")
    quote = re.match(r"^((?:>.*(?:\n|$))+)", body)
    if not summary and quote and meta.get("call_number"):
        # Our own exports put the summary in a leading blockquote.
        summary = "\n".join(line[1:].lstrip() for line in quote.group(1).splitlines())
        body = body[quote.end():].lstrip("\n")
    body = re.split(r"\n## Marginalia\n", body)[0] if meta.get("call_number") else body
    tags = meta.get("tags", [])
    if isinstance(tags, str):
        tags = re.split(r"[,\s]+", tags)
    rating = meta.get("rating")
    return {
        "title": str(title or fallback_title),
        "kind": str(meta.get("kind", "note")),
        "status": str(meta.get("status", "done" if meta.get("finished") else "inbox")),
        "author": str(meta.get("author", "")),
        "source_url": str(meta.get("source") or meta.get("url") or meta.get("source_url") or ""),
        "summary": str(summary),
        "content": body.rstrip() + "\n" if body.strip() else "",
        "tags": [str(t) for t in tags],
        "wing": meta.get("wing") or None,
        "rating": rating if isinstance(rating, int) and 1 <= rating <= 5 else None,
        "created_at": meta.get("created") if _is_iso(meta.get("created")) else None,
    }


def _is_iso(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value) is not None


def import_markdown(lib: Library, path: str | Path, *, wing: str | None = None) -> dict:
    """Import a Markdown file or a folder of them (e.g. an Obsidian vault)."""
    root = Path(path).expanduser()
    if not root.exists():
        raise LibraryError(f"{root} does not exist")
    files = [root] if root.is_file() else sorted(
        p for p in root.rglob("*.md") if not any(part.startswith(".") for part in p.parts))
    added = skipped = 0
    for file in files:
        fields = markdown_to_fields(file.read_text(encoding="utf-8", errors="replace"), file.stem)
        if wing and not fields["wing"]:
            fields["wing"] = wing
        elif not fields["wing"] and root.is_dir() and file.parent != root:
            fields["wing"] = file.parent.relative_to(root).parts[0].replace("-", " ").title()
        if fields["kind"] not in KINDS:
            fields["kind"] = "note"
        if fields["status"] not in STATUSES:
            fields["status"] = "inbox"
        if _exists(lib, fields["title"], fields["source_url"]):
            skipped += 1
            continue
        title = fields.pop("title")
        lib.add_scroll(title, **fields)
        added += 1
    # Links to scrolls imported later in the same batch need resolving now.
    lib.rebuild_index()
    return {"added": added, "skipped": skipped, "files": len(files)}


__all__ = ["export_json", "import_json", "export_markdown", "import_markdown",
           "scroll_to_markdown", "markdown_to_fields", "parse_front_matter"]
