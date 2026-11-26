"""Build the standalone, interactive demo of the World Knowledge Library.

The result is a single HTML file that runs the real reading room (wkl/static)
in any browser with no server: wkl/static/demo-backend.js stands in for the
Python API, and the example collection is generated here by the real Python
library so both always agree.

    python scripts/build_demo.py                 # writes dist/demo.html
    python scripts/build_demo.py -o site.html    # choose the output file
    python scripts/build_demo.py --fragment      # body-only markup for hosts that add their own <html>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wkl import __version__  # noqa: E402
from wkl.catalogue import meta  # noqa: E402
from wkl.founding import found  # noqa: E402
from wkl.library import Library  # noqa: E402
from wkl.serapeum import export_json  # noqa: E402

STATIC = ROOT / "wkl" / "static"

# A few more works beyond the founding collection, so every room has something in it.
EXTRA = [
    dict(title="Eratosthenes", kind="note", status="done", wing="Antiquity",
         tags=["people", "geography", "alexandria"], rating=4,
         summary="Chief librarian (c. 276–194 BC) who estimated the Earth's circumference "
                 "from the angle of the Sun's shadow at Syene and Alexandria.",
         content="He worked at [[The Library of Alexandria]] and was a scholar of the "
                 "[[Mouseion]]. His method needed only two cities, one angle and the "
                 "distance between them.\n\n- Shadow angle at Alexandria: about 7°\n"
                 "- 7° is roughly 1/50 of a full circle\n- So the Earth is about 50 times "
                 "the Syene–Alexandria distance around"),
    dict(title="The Library: A Fragile History", kind="book", status="active",
         wing="Antiquity", tags=["libraries", "history"],
         author="Andrew Pettegree & Arthur der Weduwen",
         summary="A history of libraries from antiquity to the present, and of how often "
                 "they have been lost.",
         content="Opens with [[The Library of Alexandria]] and returns again and again to "
                 "one theme: collections survive only while someone tends them. See "
                 "[[Knowledge that is not tended is lost]]."),
    dict(title="Learning How to Learn", kind="course", status="active",
         wing="Craft of Knowing", tags=["learning", "memory"],
         author="Barbara Oakley & Terrence Sejnowski",
         source_url="https://www.coursera.org/learn/learning-how-to-learn",
         summary="Focused and diffuse modes of thinking, chunking, and practical study habits.",
         content="Week 3 pairs well with [[Spaced repetition]]: practice retrieval, space "
                 "it out, interleave topics."),
    dict(title="Pleiades gazetteer of ancient places", kind="dataset", status="inbox",
         tags=["geography", "antiquity"], source_url="https://pleiades.stoa.org/",
         summary="An open, linked gazetteer of places in the ancient world."),
    dict(title="Perseus Digital Library", kind="website", status="queued",
         tags=["texts", "antiquity"], source_url="https://www.perseus.tufts.edu/",
         summary="Greek and Latin texts with translations and reading tools."),
    dict(title="The Hellenistic Age Podcast", kind="podcast", status="inbox",
         tags=["history", "antiquity"], author="Ryan Stitt",
         summary="A narrative history of the world after Alexander."),
    dict(title="Libraries as memory machines", kind="idea", status="active",
         wing="Craft of Knowing", tags=["memory", "libraries", "linking"],
         summary="A personal library is an external memory; links are its associations.",
         content="Three habits keep it alive:\n\n1. **Capture** everything in the Harbor first.\n"
                 "2. **Link** each new scroll to at least one old one, as in a [[Zettelkasten]].\n"
                 "3. **Revisit** what matters with [[Spaced repetition]].\n\n"
                 "The [[Pinakes]] made Alexandria usable; links make a personal library usable."),
]

# Days before "now" at which each scroll arrived, by title. Unlisted ones arrive recently.
ARRIVALS = {
    "The Library of Alexandria": 300, "Mouseion": 296, "Callimachus": 270, "Pinakes": 268,
    "The Decline of the Library": 240, "Serapeum": 236, "Spaced repetition": 200,
    "The forgetting curve": 170, "Zettelkasten": 150, "How to Read a Book": 120,
    "Knowledge that is not tended is lost": 95, "Eratosthenes": 80,
    "The Library: A Fragile History": 60, "Learning How to Learn": 41,
    "Perseus Digital Library": 25, "Libraries as memory machines": 12,
    "The Hellenistic Age Podcast": 4, "Pleiades gazetteer of ancient places": 1,
}


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_seed() -> dict:
    lib = Library(":memory:")
    found(lib)
    for spec in EXTRA:
        spec = dict(spec)
        lib.add_scroll(spec.pop("title"), **spec)
    # A rewrite, so the palimpsest has something to show.
    z = lib.find_by_title("Zettelkasten")
    first = lib.get_scroll(z["id"])["content"]
    lib.update_scroll(z["id"], content=first.replace(
        "Links matter more than folders.",
        "Links matter more than folders: a note's value grows with its connections."))
    lib.add_marginalia(lib.find_by_title("Eratosthenes")["id"],
                       "Remarkably close to the modern figure, depending on the stadion used.",
                       quote="the Earth is about 50 times the Syene–Alexandria distance around",
                       kind="highlight")
    lib.remember(lib.find_by_title("Eratosthenes")["id"])
    archive = export_json(lib)
    lib.close()

    # Spread the collection over the past months so the charts look lived in.
    now = datetime.now(timezone.utc).replace(microsecond=0)
    archive["exported_at"] = iso(now)
    for i, s in enumerate(archive["scrolls"]):
        created = now - timedelta(days=ARRIVALS.get(s["title"], 2), hours=(i * 5) % 11)
        tended = min(now - timedelta(hours=3), created + timedelta(days=3 + (i * 7) % 20))
        s["created_at"], s["updated_at"] = iso(created), iso(tended)
        s["finished_at"] = iso(tended) if s["status"] == "done" else None
        for j, m in enumerate(s["marginalia"]):
            m["created_at"] = iso(min(now, created + timedelta(days=1 + j)))
        for j, r in enumerate(s.get("palimpsest", [])):
            r["created_at"] = iso(created + timedelta(days=1 + j))
        if s["pharos"]:
            reps = 1 + i % 3
            s["pharos"].update(
                repetitions=reps, interval_days=float(3 * reps), last_reviewed=iso(now - timedelta(days=3 * reps)),
                # About half are due now, so the Pharos has work on first visit.
                due_at=iso(now - timedelta(hours=2)) if i % 2 == 0 else iso(now + timedelta(days=2 + i % 5)))
    for w in archive["wings"]:
        w["created_at"] = iso(now - timedelta(days=305))
    return archive


def script_safe(text: str) -> str:
    """Make text safe to place inside an inline <script> element."""
    return re.sub(r"</(script)", r"<\\/\1", text, flags=re.I)


def build(fragment: bool = False) -> str:
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    backend = (STATIC / "demo-backend.js").read_text(encoding="utf-8")
    seed = {"meta": meta(), "archive": build_seed(), "version": __version__}

    body = re.search(r"<body>(.*)</body>", index, re.S).group(1)
    body = body.replace('<script src="app.js"></script>', "").strip()
    fonts = re.findall(r'<link rel="(?:preconnect|stylesheet)" href="https://fonts\.[^>]*>', index)
    head = "\n".join([
        "<title>World Knowledge Library</title>",
        '<meta name="description" content="A living library for everything you read, watch, '
        'learn and think. Interactive demo.">',
        *fonts,
        f"<style>\n{css}\n</style>",
    ])
    scripts = "\n".join([
        f"<script>window.WKL_SEED = {script_safe(json.dumps(seed, ensure_ascii=False))};</script>",
        f"<script>\n{script_safe(backend)}\n</script>",
        f"<script>\n{script_safe(app)}\n</script>",
    ])
    if fragment:
        return f"{head}\n{body}\n{scripts}\n"
    return (f'<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n{head}\n</head>\n'
            f"<body>\n{body}\n{scripts}\n</body>\n</html>\n")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-o", "--output", default=str(ROOT / "dist" / "demo.html"))
    p.add_argument("--fragment", action="store_true",
                   help="omit <html>/<head>/<body> for hosts that wrap the page themselves")
    a = p.parse_args()
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(fragment=a.fragment), encoding="utf-8")
    print(f"Wrote {out} ({out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
