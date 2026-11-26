import importlib.util
import json
import re
from pathlib import Path

from wkl.library import Library
from wkl.serapeum import import_json

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_demo.py"
spec = importlib.util.spec_from_file_location("build_demo", SCRIPT)
build_demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_demo)


def test_seed_is_a_valid_archive_with_due_reviews():
    archive = build_demo.build_seed()
    lib = Library(":memory:")
    assert import_json(lib, archive)["added"] == len(archive["scrolls"])
    st = lib.stats()
    assert st["due"] >= 1 and st["by_status"].get("inbox", 0) >= 1 and st["revisions"] >= 1
    assert st["links"] > 10


def test_demo_page_is_self_contained():
    page = build_demo.build()
    assert page.startswith("<!doctype html>")
    assert 'src="app.js"' not in page and "window.WKL_SEED" in page and "window.WKL_DEMO" in page
    seed = re.search(r"window\.WKL_SEED = (\{.*?\});</script>", page, re.S).group(1)
    assert json.loads(seed)["archive"]["format"] == "world-knowledge-library"
    fragment = build_demo.build(fragment=True)
    assert "<html" not in fragment and "<title>World Knowledge Library</title>" in fragment


def _seed_of(page):
    return json.loads(re.search(r"window\.WKL_SEED = (\{.*?\});</script>", page, re.S).group(1))


def test_routing_defaults():
    assert _seed_of(build_demo.build())["routing"] == "hash"
    assert _seed_of(build_demo.build(fragment=True))["routing"] == "memory"
    assert _seed_of(build_demo.build(routing="memory"))["routing"] == "memory"


def test_site_folder(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["build_demo.py", "--site", str(tmp_path / "site")])
    assert build_demo.main() == 0
    site = tmp_path / "site"
    assert {p.name for p in site.iterdir()} == {"index.html", "favicon.svg", ".nojekyll"}
    assert '<link rel="icon" href="favicon.svg"' in (site / "index.html").read_text(encoding="utf-8")
