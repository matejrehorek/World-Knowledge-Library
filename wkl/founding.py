"""The founding collection: a few interlinked scrolls to explore a new library with.

Fittingly, they are about the Library of Alexandria itself, and about the
habits that keep knowledge alive. Run ``wkl demo`` to shelve them.
"""

from __future__ import annotations

from .library import Library

WINGS = [
    ("Antiquity", "The ancient world and its institutions", "🏛"),
    ("Craft of Knowing", "How to read, remember and think well", "🪶"),
]

SCROLLS = [
    dict(
        title="The Library of Alexandria", kind="note", status="done", wing="Antiquity",
        tags=["history", "libraries", "alexandria"], remember=True, rating=5,
        summary="Founded under the early Ptolemies in the 3rd century BC, it aimed to "
                "collect a copy of every book in the known world.",
        content=(
            "The Library was part of the [[Mouseion]], a research institution in Alexandria "
            "where scholars lived, studied and argued at royal expense.\n\n"
            "## Why it mattered\n\n"
            "- It gathered texts from Greece, Egypt, Persia, India and beyond.\n"
            "- Its scholars produced *critical editions* — comparing copies to recover the best text.\n"
            "- [[Callimachus]] catalogued the collection in the [[Pinakes]].\n\n"
            "Its decline was gradual rather than a single fire; see [[The Decline of the Library]].\n\n"
            "> A library is not a store of books but a habit of attention.\n"
        ),
    ),
    dict(
        title="Mouseion", kind="note", status="done", wing="Antiquity",
        tags=["history", "alexandria", "institutions"],
        summary="The 'shrine of the Muses' — Alexandria's research institute, of which the "
                "Library was a part.",
        content=("Scholars of the Mouseion received stipends, lodging and meals. It is the "
                 "origin of our word *museum*. It housed [[The Library of Alexandria]] and was "
                 "home to figures such as Eratosthenes and Euclid."),
    ),
    dict(
        title="Callimachus", kind="note", status="done", wing="Antiquity",
        tags=["history", "people", "cataloguing"],
        summary="Poet and scholar of Cyrene (c. 310–240 BC) who compiled the Pinakes.",
        content="Callimachus never held the post of head librarian, yet his [[Pinakes]] "
                "made the collection usable. *A big book is a big evil*, he is said to have quipped.",
    ),
    dict(
        title="Pinakes", kind="note", status="done", wing="Antiquity",
        tags=["cataloguing", "libraries", "alexandria"], remember=True,
        summary="The first known library catalogue: 120 scrolls listing authors by genre, "
                "with biographies and opening lines.",
        content=(
            "The *Pinakes* (\"tables\") sorted works into genres — rhetoric, law, epic, "
            "tragedy, medicine and more — then listed authors alphabetically.\n\n"
            "In this library, the catalogue view is named after it, and every scroll's call "
            "number begins with a genre mark in its honour. Compiled by [[Callimachus]] for "
            "[[The Library of Alexandria]]."
        ),
    ),
    dict(
        title="The Decline of the Library", kind="article", status="queued", wing="Antiquity",
        tags=["history", "alexandria"],
        summary="Budget cuts, purges of scholars and civil wars eroded the Library over centuries.",
        content="Commonly told as one dramatic fire, the loss of [[The Library of Alexandria]] "
                "was slow: Ptolemy VIII expelled intellectuals in 145 BC, Caesar's fire of 48 BC "
                "burned warehouses near the harbour, and the [[Serapeum]] was destroyed in AD 391.\n\n"
                "Lesson: knowledge that is not *tended* is lost.",
    ),
    dict(
        title="Serapeum", kind="note", status="done", wing="Antiquity",
        tags=["history", "alexandria", "libraries"],
        summary="The 'daughter library' in the temple of Serapis, which held overflow copies.",
        content="Here, the Serapeum is the name for exports and backups: copies of your library "
                "kept outside it, in open formats. Destroyed in AD 391 — see "
                "[[The Decline of the Library]].",
    ),
    dict(
        title="Spaced repetition", kind="idea", status="active", wing="Craft of Knowing",
        tags=["memory", "learning"], remember=True,
        summary="Reviewing at growing intervals is a powerful way to keep what you learn.",
        content=("Each successful recall pushes the next review further out; each lapse brings "
                 "it back. The Pharos in this library schedules reviews this way.\n\n"
                 "Related: [[The forgetting curve]], [[Zettelkasten]]."),
    ),
    dict(
        title="The forgetting curve", kind="paper", status="queued", wing="Craft of Knowing",
        tags=["memory", "psychology"], author="Hermann Ebbinghaus",
        source_url="https://en.wikipedia.org/wiki/Forgetting_curve",
        summary="Ebbinghaus (1885) measured how memory decays without review.",
        content="Without rehearsal, much of what we learn fades within days. "
                "[[Spaced repetition]] is the practical answer.",
    ),
    dict(
        title="Zettelkasten", kind="idea", status="active", wing="Craft of Knowing",
        tags=["notes", "learning", "linking"],
        summary="A slip-box of small, linked notes that grows into a thinking partner.",
        content=("Write one idea per note, in your own words, and link it to what it touches. "
                 "Links matter more than folders. Use `[[double brackets]]` here to link scrolls — "
                 "backlinks appear automatically.\n\nSee also [[Spaced repetition]] and "
                 "[[How to Read a Book]]."),
    ),
    dict(
        title="How to Read a Book", kind="book", status="queued", wing="Craft of Knowing",
        tags=["reading", "learning"], author="Mortimer J. Adler & Charles Van Doren",
        summary="A guide to the levels of reading: elementary, inspectional, analytical, syntopical.",
        content="*Syntopical* reading — reading many books on one subject against each other — "
                "is what a library like this one is for.",
    ),
    dict(
        title="Knowledge that is not tended is lost", kind="quote", status="done",
        wing="Craft of Knowing", tags=["memory", "maxims"],
        summary="The motto of this library.",
        content="> Knowledge that is not tended is lost.\n\nDrawn from "
                "[[The Decline of the Library]].",
    ),
]

MARGINALIA = [
    ("The Library of Alexandria", "insight", "",
     "Copying and comparing was its real engine — collection alone isn't knowledge."),
    ("Pinakes", "question", "", "What would a genre system for my own reading look like?"),
    ("Spaced repetition", "highlight", "each lapse brings it back", "Grade honestly in the Pharos."),
]


def found(lib: Library) -> int:
    """Shelve the founding collection. Returns the number of scrolls added."""
    for name, description, emblem in WINGS:
        try:
            lib.wing_id_for(name, create=False)
        except Exception:
            lib.create_wing(name, description, emblem)
    added = 0
    for spec in SCROLLS:
        spec = dict(spec)
        if lib.find_by_title(spec["title"]):
            continue
        lib.add_scroll(spec.pop("title"), **spec)
        added += 1
    for title, kind, quote, body in MARGINALIA:
        s = lib.find_by_title(title)
        if s and not lib.get_scroll(s["id"])["marginalia"]:
            lib.add_marginalia(s["id"], body, quote=quote, kind=kind)
    return added
