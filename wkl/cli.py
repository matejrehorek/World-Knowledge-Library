"""``wkl`` — the command-line door into the World Knowledge Library."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from . import __version__, serapeum
from .catalogue import GRADES, KINDS, MARGINALIA_KINDS, STATUSES
from .founding import found
from .harbor import fetch_metadata
from .library import Library, LibraryError

DEFAULT_HOME = Path.home() / ".world-knowledge-library"


def default_path() -> Path:
    env = os.environ.get("WKL_LIBRARY")
    return Path(env).expanduser() if env else DEFAULT_HOME / "library.db"


# ------------------------------------------------------------------ output
def _tty() -> bool:
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _tty() else text


def gold(t: str) -> str: return c(t, "33")
def dim(t: str) -> str: return c(t, "2")
def bold(t: str) -> str: return c(t, "1")
def lapis(t: str) -> str: return c(t, "34")


def line(s: dict) -> str:
    glyph = KINDS.get(s["kind"], KINDS["other"])[2]
    status = STATUSES[s["status"]][0]
    tags = " ".join(f"#{t}" for t in s.get("tags", []))
    stars = "★" * (s.get("rating") or 0)
    parts = [gold(s["call_number"].ljust(8)), glyph, bold(s["title"])]
    if s.get("author"):
        parts.append(dim(f"— {s['author']}"))
    tail = "  ".join(p for p in (dim(status), lapis(tags), gold(stars)) if p.strip())
    return " ".join(parts) + ("  " + tail if tail else "")


def show(s: dict) -> None:
    width = min(shutil.get_terminal_size((88, 20)).columns, 100)
    print()
    print(gold(f"  {s['call_number']}") + "  " + bold(s["title"]))
    meta = [KINDS[s["kind"]][1], STATUSES[s["status"]][0]]
    if s["author"]:
        meta.append(s["author"])
    if s["wing"]:
        meta.append(f"Wing: {s['wing']['name']}")
    if s["rating"]:
        meta.append("★" * s["rating"])
    print(dim("  " + " · ".join(meta)))
    if s["source_url"]:
        print(lapis(f"  {s['source_url']}"))
    if s["tags"]:
        print(lapis("  " + " ".join(f"#{t}" for t in s["tags"])))
    if s["summary"]:
        print()
        for ln in textwrap.wrap(s["summary"], width - 4):
            print(c("  │ ", "33") + ln)
    if s["content"]:
        print()
        for para in s["content"].splitlines():
            print(textwrap.fill(para, width - 2, initial_indent="  ", subsequent_indent="  ")
                  if para.strip() else "")
    for label, key in (("Links to", "outlinks"), ("Linked from", "backlinks"),
                       ("Kin by subject", "related")):
        if s.get(key):
            print()
            print(dim(f"  {label}: ") + ", ".join(f"{x['title']} ({x['call_number']})" for x in s[key]))
    if s.get("unwritten"):
        print(dim("  Unwritten scrolls: ") + ", ".join(s["unwritten"]))
    if s.get("marginalia"):
        print()
        print(dim("  Marginalia"))
        for m in s["marginalia"]:
            quote = f"“{m['quote']}” " if m["quote"] else ""
            print(f"   {dim('#' + str(m['id']))} {gold(m['kind'])}: {quote}{m['body']}")
    footer = [f"added {s['created_at'][:10]}", f"updated {s['updated_at'][:10]}"]
    if s.get("revisions"):
        footer.append(f"{s['revisions']} earlier version(s)")
    if s.get("pharos"):
        footer.append(f"next Pharos review {s['pharos']['due_at'][:10]}")
    print()
    print(dim("  " + " · ".join(footer)))
    print()


def read_text(value: str | None) -> str | None:
    if value is None:
        return None
    if value == "-":
        return sys.stdin.read()
    if value.startswith("@"):
        return Path(value[1:]).expanduser().read_text(encoding="utf-8")
    return value


def edit_in_editor(text: str) -> str:
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
    with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False, encoding="utf-8") as fh:
        fh.write(text)
        name = fh.name
    try:
        subprocess.run([*editor.split(), name], check=True)
        return Path(name).read_text(encoding="utf-8")
    finally:
        os.unlink(name)


# ---------------------------------------------------------------- commands
def cmd_serve(lib: Library, a) -> int:
    from .server import serve
    serve(lib, a.host, a.port, quiet=a.quiet, open_browser=a.open)
    return 0


def _fields(a) -> dict:
    out = {}
    for attr, key in (("kind", "kind"), ("status", "status"), ("url", "source_url"),
                      ("author", "author"), ("summary", "summary"), ("rating", "rating")):
        v = getattr(a, attr, None)
        if v is not None:
            out[key] = v
    content = read_text(getattr(a, "content", None))
    if content is not None:
        out["content"] = content
    return out


def cmd_add(lib: Library, a) -> int:
    fields = _fields(a)
    s = lib.add_scroll(a.title, tags=a.tags, wing=a.wing, remember=a.remember, **fields)
    print(f"Shelved {line(s)}")
    return 0


def cmd_capture(lib: Library, a) -> int:
    info = fetch_metadata(a.url)
    if info.get("error"):
        print(dim(f"  ({info['error']} — keeping the bare link)"), file=sys.stderr)
    s = lib.add_scroll(a.title or info["title"], kind=a.kind or info["kind"], status="inbox",
                       source_url=info["url"], author=info["author"], summary=info["summary"],
                       tags=a.tags, wing=a.wing)
    print(f"Docked in the Harbor: {line(s)}")
    return 0


def cmd_search(lib: Library, a) -> int:
    res = lib.search(" ".join(a.query), kind=a.kind, status=a.status, tag=a.tag, wing=a.wing,
                     sort=a.sort or "", limit=a.limit)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    if not res["results"]:
        print(dim("No scrolls match. The shelves are patient."))
        return 0
    for s in res["results"]:
        print(line(s))
        if a.query and s.get("excerpt"):
            excerpt = s["excerpt"].replace("\x02", "\033[1;33m" if _tty() else "") \
                                  .replace("\x03", "\033[0m" if _tty() else "")
            print("         " + dim(" ".join(excerpt.split())[:160]))
    shown = len(res["results"])
    if res["total"] > shown:
        print(dim(f"… {res['total'] - shown} more (use --limit)"))
    return 0


def _resolve(lib: Library, ref: str) -> int:
    ref = ref.strip()
    if ref.isdigit():
        return int(ref)
    if "-" in ref and ref.split("-", 1)[1].isdigit():  # a call number like BK-0004
        return int(ref.split("-", 1)[1])
    found_ = lib.find_by_title(ref)
    if not found_:
        raise LibraryError(f"No scroll called {ref!r}")
    return found_["id"]


def cmd_show(lib: Library, a) -> int:
    s = lib.get_scroll(_resolve(lib, a.ref))
    if a.json:
        print(json.dumps(s, ensure_ascii=False, indent=2))
    elif a.markdown:
        print(serapeum.scroll_to_markdown(s))
    else:
        show(s)
    return 0


def cmd_set(lib: Library, a) -> int:
    sid = _resolve(lib, a.ref)
    fields = _fields(a)
    if a.title:
        fields["title"] = a.title
    s = lib.update_scroll(sid, tags=a.tags, wing=a.wing, **fields)
    print(f"Updated {line(s)}")
    return 0


def cmd_edit(lib: Library, a) -> int:
    sid = _resolve(lib, a.ref)
    s = lib.get_scroll(sid)
    new = edit_in_editor(s["content"])
    if new == s["content"]:
        print(dim("No changes."))
        return 0
    lib.update_scroll(sid, content=new)
    print(f"Rewritten — the earlier text is kept in the palimpsest ({s['call_number']}).")
    return 0


def cmd_note(lib: Library, a) -> int:
    sid = _resolve(lib, a.ref)
    m = lib.add_marginalia(sid, " ".join(a.text), quote=a.quote or "", kind=a.kind)
    print(f"Marginalia #{m['id']} written beside scroll {sid}.")
    return 0


def cmd_rm(lib: Library, a) -> int:
    sid = _resolve(lib, a.ref)
    s = lib.get_scroll(sid, full=False)
    if not a.yes:
        if not sys.stdin.isatty():
            print("Refusing to burn a scroll without --yes.", file=sys.stderr)
            return 1
        if input(f"Burn {s['call_number']} “{s['title']}”? This cannot be undone [y/N] ") \
                .strip().lower() not in ("y", "yes"):
            return 1
    lib.delete_scroll(sid)
    print(f"{s['call_number']} has been removed from the shelves.")
    return 0


def cmd_remember(lib: Library, a) -> int:
    sid = _resolve(lib, a.ref)
    s = lib.remember(sid, not a.forget)
    msg = "no longer kept by the Pharos" if a.forget else \
        f"kept by the Pharos — first review {s['pharos']['due_at'][:10]}"
    print(f"{s['call_number']} {s['title']}: {msg}.")
    return 0


def cmd_review(lib: Library, a) -> int:
    due = lib.due(limit=a.limit)
    if not due:
        print(gold("The Pharos is dark tonight — nothing is due for review."))
        return 0
    print(gold(f"\n  The Pharos is lit: {len(due)} scroll(s) to revisit.\n"))
    for i, s in enumerate(due, 1):
        print(dim(f"  [{i}/{len(due)}] {s['call_number']}") + "  " + bold(s["title"]))
        print(dim("  Recall what you know about it, then press Enter to unroll."))
        try:
            input()
        except EOFError:
            return 0
        if s["summary"]:
            print("  " + s["summary"])
        snippet = " ".join(s["content"].split())[:400]
        if snippet:
            print(dim("  " + snippet + ("…" if len(s["content"]) > 400 else "")))
        for m in s["marginalia"]:
            print(gold(f"  ✎ {m['body'] or m['quote']}"))
        choices = "  ".join(f"[{k}] {v}" for k, v in GRADES.items())
        while True:
            try:
                ans = input(f"\n  How well did you remember?  {choices}  (s = skip, q = quit) ")
            except EOFError:
                return 0
            ans = ans.strip().lower()
            if ans == "q":
                return 0
            if ans == "s":
                break
            if ans.isdigit() and int(ans) in GRADES:
                p = lib.review(s["id"], int(ans))
                print(dim(f"  Next visit in {p['interval_days']:.0f} day(s), {p['due_at'][:10]}.\n"))
                break
    print(gold("  The lamp is trimmed. Well done.\n"))
    return 0


def cmd_wings(lib: Library, a) -> int:
    if a.add:
        w = lib.create_wing(a.add, a.description or "", a.emblem or "")
        print(f"Opened the {w['name']} wing.")
        return 0
    wings = lib.list_wings()
    if not wings:
        print(dim("No wings yet. Open one with: wkl wings --add 'Philosophy'"))
    for w in wings:
        print(f"{w['emblem'] or '▪'} {bold(w['name'])} {dim(str(w['scroll_count']) + ' scrolls')}"
              + (f" — {w['description']}" if w["description"] else ""))
    return 0


def cmd_tags(lib: Library, a) -> int:
    if a.rename:
        lib.rename_tag(*a.rename)
        print(f"#{a.rename[0]} is now #{a.rename[1]}.")
        return 0
    for t in lib.list_tags():
        print(f"{lapis('#' + t['name'])} {dim(str(t['count']))}")
    return 0


def cmd_stats(lib: Library, a) -> int:
    st = lib.stats()
    if a.json:
        print(json.dumps(st, ensure_ascii=False, indent=2))
        return 0
    print(gold("\n  The World Knowledge Library — state of the collection\n"))
    print(f"  {bold(str(st['scrolls']))} scrolls · {st['words']:,} words · {st['wings']} wings · "
          f"{st['tags']} tags · {st['links']} links · {st['marginalia']} marginalia")
    print(f"  {st['remembered']} kept by the Pharos ({st['due']} due) · "
          f"{st['revisions']} palimpsest layers\n")
    for k, n in sorted(st["by_kind"].items(), key=lambda kv: -kv[1]):
        print(f"  {KINDS[k][2]} {KINDS[k][1]:<11} {gold('▇' * min(n, 40))} {n}")
    print()
    for k in STATUSES:
        print(f"  {STATUSES[k][0]:<14} {st['by_status'].get(k, 0)}")
    print()
    return 0


def cmd_random(lib: Library, a) -> int:
    s = lib.random_scroll(a.status)
    if not s:
        print(dim("The shelves are empty."))
        return 0
    show(lib.get_scroll(s["id"]))
    return 0


def cmd_export(lib: Library, a) -> int:
    if a.markdown:
        n = serapeum.export_markdown(lib, a.markdown)
        print(f"Copied {n} scrolls to the Serapeum at {a.markdown}")
    else:
        data = serapeum.export_json(lib, include_history=not a.no_history)
        text = json.dumps(data, ensure_ascii=False, indent=2)
        if a.output in (None, "-"):
            print(text)
        else:
            Path(a.output).expanduser().write_text(text, encoding="utf-8")
            print(f"Archived {len(data['scrolls'])} scrolls to {a.output}", file=sys.stderr)
    return 0


def cmd_import(lib: Library, a) -> int:
    path = Path(a.path).expanduser()
    if path.is_file() and path.suffix.lower() == ".json":
        res = serapeum.import_json(lib, path.read_text(encoding="utf-8"))
    else:
        res = serapeum.import_markdown(lib, path, wing=a.wing)
    print(f"Brought in {res['added']} scroll(s); {res['skipped']} already on the shelves.")
    return 0


def cmd_demo(lib: Library, a) -> int:
    n = found(lib)
    print(f"Shelved {n} founding scroll(s). Try: wkl search alexandria   or   wkl serve")
    return 0


def cmd_reindex(lib: Library, a) -> int:
    print(f"Re-read {lib.rebuild_index()} scrolls and rebuilt the index and links.")
    return 0


# ------------------------------------------------------------------ parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wkl",
        description="World Knowledge Library — a living library for what you read, "
                    "watch, learn and think.",
        epilog="Your library lives at $WKL_LIBRARY or ~/.world-knowledge-library/library.db")
    p.add_argument("--library", "-L", help="path to a library file (default: %(default)s)",
                   default=None)
    p.add_argument("--version", action="version", version=f"wkl {__version__}")
    sub = p.add_subparsers(dest="command", metavar="command")

    def cmd(name, fn, help_, aliases=()):
        sp = sub.add_parser(name, help=help_, aliases=list(aliases), description=help_)
        sp.set_defaults(fn=fn)
        return sp

    def scroll_opts(sp, *, editing: bool = False):
        sp.add_argument("--kind", "-k", choices=list(KINDS))
        sp.add_argument("--status", "-s", choices=list(STATUSES))
        sp.add_argument("--url", "-u", help="source URL")
        sp.add_argument("--author", "-a")
        sp.add_argument("--summary", "-S", help="the gist, in a sentence or two")
        sp.add_argument("--content", "-c", help="body text in Markdown; '-' reads stdin, @file reads a file")
        sp.add_argument("--tags", "-t", help="comma- or space-separated tags"
                        + ("; replaces existing tags" if editing else ""))
        sp.add_argument("--wing", "-w", help="wing (collection) name; created if new")
        sp.add_argument("--rating", "-r", type=int, choices=range(0, 6), metavar="0-5")

    sp = cmd("serve", cmd_serve, "open the reading room (web interface)")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", "-p", type=int, default=8331)
    sp.add_argument("--open", action="store_true", help="open a browser window")
    sp.add_argument("--quiet", "-q", action="store_true")

    sp = cmd("add", cmd_add, "shelve a new scroll")
    sp.add_argument("title")
    scroll_opts(sp)
    sp.add_argument("--remember", action="store_true", help="keep it alive with Pharos reviews")

    sp = cmd("capture", cmd_capture, "dock a URL in the Harbor, reading its title and description")
    sp.add_argument("url")
    sp.add_argument("--title")
    sp.add_argument("--kind", "-k", choices=list(KINDS))
    sp.add_argument("--tags", "-t")
    sp.add_argument("--wing", "-w")

    sp = cmd("search", cmd_search, "search the Pinakes (catalogue)", aliases=["ls", "list"])
    sp.add_argument("query", nargs="*",
                    help="words, \"phrases\" and filters like tag:x kind:book status:done wing:y")
    sp.add_argument("--kind", "-k", choices=list(KINDS))
    sp.add_argument("--status", "-s", choices=list(STATUSES))
    sp.add_argument("--tag", "-t")
    sp.add_argument("--wing", "-w")
    sp.add_argument("--sort", choices=["updated", "created", "oldest", "title", "rating"])
    sp.add_argument("--limit", "-n", type=int, default=30)
    sp.add_argument("--json", action="store_true")

    sp = cmd("show", cmd_show, "unroll a scroll (by id, call number or title)")
    sp.add_argument("ref")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--markdown", "--md", action="store_true")

    sp = cmd("set", cmd_set, "change a scroll's details")
    sp.add_argument("ref")
    sp.add_argument("--title")
    scroll_opts(sp, editing=True)

    sp = cmd("edit", cmd_edit, "rewrite a scroll's body in $EDITOR")
    sp.add_argument("ref")

    sp = cmd("note", cmd_note, "write marginalia beside a scroll")
    sp.add_argument("ref")
    sp.add_argument("text", nargs="*")
    sp.add_argument("--quote", "-q", help="the passage this note is about")
    sp.add_argument("--kind", "-k", choices=list(MARGINALIA_KINDS), default="note")

    sp = cmd("rm", cmd_rm, "remove a scroll for good")
    sp.add_argument("ref")
    sp.add_argument("--yes", "-y", action="store_true")

    sp = cmd("remember", cmd_remember, "ask the Pharos to keep a scroll alive in memory")
    sp.add_argument("ref")
    sp.add_argument("--forget", action="store_true", help="stop reviewing it")

    sp = cmd("review", cmd_review, "revisit what the Pharos says is due")
    sp.add_argument("--limit", "-n", type=int, default=20)

    sp = cmd("wings", cmd_wings, "list or open wings (collections)")
    sp.add_argument("--add", metavar="NAME")
    sp.add_argument("--description", "-d")
    sp.add_argument("--emblem", "-e")

    sp = cmd("tags", cmd_tags, "list tags")
    sp.add_argument("--rename", nargs=2, metavar=("OLD", "NEW"))

    sp = cmd("stats", cmd_stats, "the state of the collection")
    sp.add_argument("--json", action="store_true")

    sp = cmd("random", cmd_random, "pull a scroll off a shelf at random (serendipity)")
    sp.add_argument("--status", "-s", choices=list(STATUSES))

    sp = cmd("export", cmd_export, "copy the library to the Serapeum (JSON or Markdown)")
    sp.add_argument("--output", "-o", help="JSON file to write (default: stdout)")
    sp.add_argument("--markdown", "--md", metavar="DIR", help="write a folder of Markdown files")
    sp.add_argument("--no-history", action="store_true", help="leave out the palimpsest")

    sp = cmd("import", cmd_import, "bring in a JSON archive, a Markdown file or a folder of notes")
    sp.add_argument("path")
    sp.add_argument("--wing", "-w", help="put imported notes in this wing")

    cmd("demo", cmd_demo, "shelve the founding collection to explore with")
    cmd("reindex", cmd_reindex, "rebuild the search index and links")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    a = parser.parse_args(argv)
    if not getattr(a, "fn", None):
        parser.print_help()
        return 0
    path = Path(a.library).expanduser() if a.library else default_path()
    try:
        lib = Library(path)
    except Exception as exc:  # e.g. an unreadable or newer library file
        print(f"wkl: cannot open the library at {path}: {exc}", file=sys.stderr)
        return 2
    try:
        return a.fn(lib, a) or 0
    except LibraryError as exc:
        print(f"wkl: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    finally:
        lib.close()


if __name__ == "__main__":
    raise SystemExit(main())
