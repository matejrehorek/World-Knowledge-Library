import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from wkl import serapeum
from wkl.cli import main
from wkl.founding import found
from wkl.harbor import guess_kind, parse_html
from wkl.library import Library
from wkl.server import Api, make_handler


@pytest.fixture
def lib():
    library = Library(":memory:")
    yield library
    library.close()


def test_json_round_trip(lib):
    found(lib)
    s = lib.find_by_title("Pinakes")
    lib.update_scroll(s["id"], content="rewritten")
    archive = serapeum.export_json(lib)
    other = Library(":memory:")
    result = serapeum.import_json(other, json.dumps(archive))
    assert result == {"added": len(archive["scrolls"]), "skipped": 0}
    copy = other.get_scroll(other.find_by_title("Pinakes")["id"])
    assert copy["content"] == "rewritten"
    assert len(other.revisions(copy["id"])) == 1
    assert copy["pharos"] is not None
    assert other.stats()["links"] == lib.stats()["links"]
    assert serapeum.import_json(other, archive)["skipped"] == len(archive["scrolls"])


def test_markdown_round_trip(lib, tmp_path):
    found(lib)
    n = serapeum.export_markdown(lib, tmp_path / "out")
    assert n == lib.stats()["scrolls"]
    files = list((tmp_path / "out").rglob("*.md"))
    assert len(files) == n
    other = Library(":memory:")
    res = serapeum.import_markdown(other, tmp_path / "out")
    assert res["added"] == n
    a = lib.get_scroll(lib.find_by_title("The Library of Alexandria")["id"])
    b = other.get_scroll(other.find_by_title("The Library of Alexandria")["id"])
    for key in ("summary", "kind", "status", "tags", "rating"):
        assert a[key] == b[key], key
    assert a["content"].strip() == b["content"].strip()
    assert b["wing"]["name"] == "Antiquity"
    assert other.stats()["links"] == lib.stats()["links"]


def test_import_obsidian_style_notes(lib, tmp_path):
    vault = tmp_path / "vault"
    (vault / "reading").mkdir(parents=True)
    (vault / ".obsidian").mkdir()
    (vault / ".obsidian" / "junk.md").write_text("ignore me")
    (vault / "reading" / "Dune.md").write_text(
        "---\ntags:\n  - scifi\n  - ecology\nauthor: Frank Herbert\nkind: book\n---\n"
        "Fear is the mind-killer. See [[Ecology]].\n")
    (vault / "Ecology.md").write_text("# Ecology\n\nSystems thinking.\n")
    res = serapeum.import_markdown(lib, vault)
    assert res["added"] == 2
    dune = lib.get_scroll(lib.find_by_title("Dune")["id"])
    assert dune["tags"] == ["ecology", "scifi"] and dune["kind"] == "book"
    assert dune["wing"]["name"] == "Reading"
    assert [x["title"] for x in dune["outlinks"]] == ["Ecology"]


def test_front_matter_parsing():
    meta, body = serapeum.parse_front_matter('---\ntitle: "A: B"\ntags: [x, "y, z"]\nrating: 4\n---\nbody')
    assert meta == {"title": "A: B", "tags": ["x", "y, z"], "rating": 4}
    assert body == "body"


def test_harbor_parsing():
    page = """<html><head><title>Ignored</title>
      <meta property="og:title" content="The Pharos | Wonders">
      <meta property="og:site_name" content="Wonders">
      <meta name="description" content="A lighthouse &amp; a wonder.">
      <meta name="author" content="Strabo"></head>
      <body><nav>menu</nav><p>Built on the island of Pharos.</p><script>x()</script></body></html>"""
    info = parse_html("https://example.org/pharos", page)
    assert info["title"] == "The Pharos"
    assert info["summary"] == "A lighthouse & a wonder."
    assert info["author"] == "Strabo"
    assert "menu" not in info["excerpt"] and "Built on the island" in info["excerpt"]
    assert guess_kind("https://www.youtube.com/watch?v=x") == "video"
    assert guess_kind("https://arxiv.org/abs/1234.5678") == "paper"


@pytest.fixture
def server(lib):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Api(lib), loopback=True, quiet=True))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    httpd.server_close()


def call(base, method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method, headers=headers or {})
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def test_api_crud(server):
    status, s = call(server, "POST", "/api/scrolls", {"title": "Euclid", "tags": "math", "wing": "Antiquity"})
    assert status == 200 and s["wing"]["name"] == "Antiquity"
    status, s = call(server, "PATCH", f"/api/scrolls/{s['id']}", {"status": "done", "rating": 5})
    assert s["status"] == "done" and s["rating"] == 5
    status, m = call(server, "POST", f"/api/scrolls/{s['id']}/marginalia", {"body": "Elements"})
    assert status == 200
    status, res = call(server, "GET", "/api/scrolls?q=euclid")
    assert res["total"] == 1
    assert call(server, "POST", f"/api/scrolls/{s['id']}/remember")[0] == 200
    assert call(server, "GET", "/api/scrolls/999")[0] == 404
    assert call(server, "POST", "/api/scrolls", {"title": ""})[0] == 400
    assert call(server, "PUT", "/api/stats")[0] == 405
    assert call(server, "DELETE", f"/api/scrolls/{s['id']}")[0] == 200
    with urllib.request.urlopen(server + "/") as r:
        assert b"World Knowledge Library" in r.read()


def test_api_refuses_cross_site_writes(server):
    status, _ = call(server, "POST", "/api/scrolls", {"title": "x"}, {"Origin": "https://evil.example"})
    assert status == 403
    status, _ = call(server, "GET", "/api/stats", headers={"Host": "attacker.example"})
    assert status == 403
    req = urllib.request.Request(server + "/api/scrolls", data=b'{"title":"x"}', method="POST",
                                 headers={"Content-Type": "text/plain"})
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 415


def test_static_cannot_escape(server):
    with urllib.request.urlopen(server + "/../../wkl/library.py") as r:
        assert b"<!doctype html>" in r.read()


def test_cli(tmp_path, capsys):
    db = str(tmp_path / "lib.db")
    assert main(["-L", db, "demo"]) == 0
    assert main(["-L", db, "add", "Euclid's Elements", "-k", "book", "-t", "math", "--remember"]) == 0
    assert main(["-L", db, "search", "elements", "--json"]) == 0
    out = capsys.readouterr().out
    assert '"Euclid\'s Elements"' in out
    assert main(["-L", db, "show", "BK-0012"]) == 0
    assert main(["-L", db, "set", "Pinakes", "--status", "active", "--rating", "4"]) == 0
    assert main(["-L", db, "note", "1", "a", "marginal", "note"]) == 0
    assert main(["-L", db, "show", "404"]) == 1
    assert main(["-L", db, "export", "-o", str(tmp_path / "a.json")]) == 0
    assert main(["-L", str(tmp_path / "b.db"), "import", str(tmp_path / "a.json")]) == 0
    assert main(["-L", db, "stats"]) == 0
