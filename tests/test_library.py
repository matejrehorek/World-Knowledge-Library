from datetime import timedelta

import pytest

from wkl.library import Library, LibraryError, NotFound, normalise_tags, now, plain


@pytest.fixture
def lib():
    library = Library(":memory:")
    yield library
    library.close()


def test_add_and_get_scroll(lib):
    s = lib.add_scroll("Meditations", kind="book", author="Marcus Aurelius",
                       tags="Stoicism, philosophy", wing="Philosophy")
    assert s["call_number"] == "BK-0001"
    assert s["tags"] == ["philosophy", "stoicism"]
    assert s["wing"]["name"] == "Philosophy"
    assert s["status"] == "inbox"


def test_validation(lib):
    with pytest.raises(LibraryError):
        lib.add_scroll("   ")
    with pytest.raises(LibraryError):
        lib.add_scroll("x", kind="hologram")
    with pytest.raises(LibraryError):
        lib.add_scroll("x", rating=9)
    with pytest.raises(NotFound):
        lib.get_scroll(404)


def test_tags_normalised():
    assert normalise_tags("Machine Learning, AI,  ai") == ["machine-learning", "ai"]
    assert normalise_tags("#history memory") == ["history", "memory"]


def test_wikilinks_resolve_in_both_directions(lib):
    a = lib.add_scroll("Alexandria", content="Home of [[The Pharos]] and [[Mouseion|the Museum]].")
    assert lib.get_scroll(a["id"])["unwritten"] == ["The Pharos", "Mouseion"]
    pharos = lib.add_scroll("The Pharos")  # created after the link was written
    a = lib.get_scroll(a["id"])
    assert [x["title"] for x in a["outlinks"]] == ["The Pharos"]
    assert a["unwritten"] == ["Mouseion"]
    assert [x["title"] for x in lib.get_scroll(pharos["id"])["backlinks"]] == ["Alexandria"]

    lib.update_scroll(pharos["id"], title="Lighthouse")  # renaming breaks the old link
    assert lib.get_scroll(a["id"])["outlinks"] == []


def test_status_done_sets_finished_at(lib):
    s = lib.add_scroll("Book", kind="book", status="queued")
    assert s["finished_at"] is None
    s = lib.update_scroll(s["id"], status="done")
    assert s["finished_at"]
    s = lib.update_scroll(s["id"], status="active")
    assert s["finished_at"] is None


def test_palimpsest_keeps_and_restores_versions(lib):
    s = lib.add_scroll("Draft", content="first")
    lib.update_scroll(s["id"], content="second")
    lib.update_scroll(s["id"], content="third")
    lib.update_scroll(s["id"], status="queued")  # metadata change: no new layer
    revs = lib.revisions(s["id"])
    assert [r["content"] for r in revs] == ["second", "first"]
    restored = lib.restore_revision(revs[-1]["id"])
    assert restored["content"] == "first"
    assert len(lib.revisions(s["id"])) == 3


def test_search_text_and_filters(lib):
    lib.add_scroll("On the Shortness of Life", kind="book", author="Seneca", tags="stoicism",
                   content="It is not that we have a short time to live, but that we waste a lot of it.")
    lib.add_scroll("Shortcuts", kind="note", tags="productivity", content="keyboard shortcuts")
    lib.add_scroll("Waste less", kind="idea", status="done")
    assert lib.search("waste")["total"] == 2
    assert lib.search("waste kind:book")["results"][0]["author"] == "Seneca"
    assert lib.search("short")["total"] == 2  # prefix match
    assert lib.search('"short time"')["total"] == 1
    assert lib.search("tag:stoicism")["total"] == 1
    assert lib.search("", status="done")["total"] == 1
    hit = lib.search("waste kind:book")["results"][0]
    assert "\x02" in hit["excerpt"]
    assert lib.search('weird "unbalanced')["total"] >= 0  # never a syntax error


def test_search_sees_marginalia(lib):
    s = lib.add_scroll("Plain title")
    lib.add_marginalia(s["id"], "serendipitous remark", kind="insight")
    assert lib.search("serendipitous")["total"] == 1


def test_pharos_schedule(lib):
    s = lib.add_scroll("Fact", remember=True)
    assert lib.due() == []
    later = now() + timedelta(days=2)
    assert [d["id"] for d in lib.due(at=later)] == [s["id"]]
    p1 = lib.review(s["id"], 2, at=later)
    p2 = lib.review(s["id"], 2, at=later)
    p3 = lib.review(s["id"], 3, at=later)
    assert p1["interval_days"] < p2["interval_days"] < p3["interval_days"]
    lapse = lib.review(s["id"], 0, at=later)
    assert lapse["interval_days"] == 1 and lapse["lapses"] == 1 and lapse["ease"] < p3["ease"]
    with pytest.raises(LibraryError):
        lib.review(s["id"], 7)
    lib.remember(s["id"], False)
    with pytest.raises(NotFound):
        lib.review(s["id"], 2)


def test_rename_tag_merges(lib):
    a = lib.add_scroll("A", tags="ml")
    lib.add_scroll("B", tags="machine-learning")
    lib.rename_tag("ml", "machine-learning")
    assert lib.list_tags() == [{"name": "machine-learning", "count": 2}]
    assert lib.search("machine")["results"][0]["id"] in (a["id"], a["id"] + 1)


def test_delete_cleans_up(lib):
    a = lib.add_scroll("A", tags="lonely")
    b = lib.add_scroll("B", content="[[A]]")
    lib.delete_scroll(a["id"])
    assert lib.list_tags() == []
    assert lib.get_scroll(b["id"])["unwritten"] == ["A"]
    assert lib.search("A")["total"] == 1


def test_wings(lib):
    w = lib.create_wing("Science", "Natural philosophy", "⚗")
    with pytest.raises(LibraryError):
        lib.create_wing("science")
    s = lib.add_scroll("Optics", wing=w["id"])
    lib.delete_wing(w["id"])
    assert lib.get_scroll(s["id"])["wing"] is None


def test_related_and_graph(lib):
    a = lib.add_scroll("Astronomy of Hipparchus", tags="astronomy, greece")
    b = lib.add_scroll("Ptolemy's Almagest", tags="astronomy, greece", content="[[Astronomy of Hipparchus]]")
    c = lib.add_scroll("Star catalogues", tags="astronomy")
    related = [r["id"] for r in lib.related(a["id"])]
    assert c["id"] in related and b["id"] not in related  # linked scrolls are not "related"
    g = lib.graph()
    assert {"source": b["id"], "target": a["id"]} in g["links"]
    assert len(g["nodes"]) == 3


def test_stats(lib):
    lib.add_scroll("One", kind="book", status="done", content="three little words")
    st = lib.stats()
    assert st["scrolls"] == 1 and st["words"] == 3
    assert st["by_kind"] == {"book": 1}
    assert st["monthly"][-1]["added"] == 1 and st["monthly"][-1]["finished"] == 1


def test_plain_excerpt():
    assert plain("## Title\n- See [[A|the a]] and **[[B]]** with *style*") == "Title See the a and B with style"
