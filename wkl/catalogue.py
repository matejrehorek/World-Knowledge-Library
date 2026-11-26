"""The vocabulary of the library: kinds of works, reading states, review grades.

Callimachus of Cyrene organised the Pinakes, the catalogue of the Library of
Alexandria, by genre. Every scroll here likewise gets a *call number* made of
a genre mark and its accession number, e.g. ``BK-0042``.
"""

from __future__ import annotations

# kind -> (call-number mark, label, glyph)
KINDS: dict[str, tuple[str, str, str]] = {
    "note":    ("NT", "Note",        "✎"),
    "idea":    ("ID", "Idea",        "✦"),
    "article": ("AR", "Article",     "❡"),
    "book":    ("BK", "Book",        "📜"),
    "paper":   ("PA", "Paper",       "⚗"),
    "video":   ("VI", "Video",       "▶"),
    "podcast": ("PO", "Podcast",     "🎙"),
    "course":  ("CO", "Course",      "🏛"),
    "dataset": ("DS", "Dataset",     "▦"),
    "quote":   ("QU", "Quote",       "❝"),
    "website": ("WS", "Website",     "🌐"),
    "other":   ("MS", "Manuscript",  "❖"),
}

# status -> (label, description)
STATUSES: dict[str, tuple[str, str]] = {
    "inbox":  ("In the Harbor", "Captured, not yet catalogued"),
    "queued": ("Awaiting",      "Intended to read, watch or study"),
    "active": ("Under study",   "Currently being consumed"),
    "done":   ("Shelved",       "Consumed and catalogued"),
}

MARGINALIA_KINDS = ("note", "highlight", "question", "insight")

# Pharos review grades (a gentle variant of SM-2).
GRADES = {0: "Forgotten", 1: "Hazy", 2: "Recalled", 3: "Vivid"}


def call_number(kind: str, scroll_id: int) -> str:
    mark = KINDS.get(kind, KINDS["other"])[0]
    return f"{mark}-{scroll_id:04d}"


def meta() -> dict:
    """Everything a client needs to render the vocabulary."""
    return {
        "kinds": [
            {"id": k, "mark": m, "label": label, "glyph": g}
            for k, (m, label, g) in KINDS.items()
        ],
        "statuses": [
            {"id": k, "label": label, "description": d}
            for k, (label, d) in STATUSES.items()
        ],
        "marginalia_kinds": list(MARGINALIA_KINDS),
        "grades": [{"id": k, "label": v} for k, v in GRADES.items()],
    }
