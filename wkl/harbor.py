"""The Harbor: where new knowledge arrives.

Ptolemy III is said to have had every ship docking at Alexandria searched for
books, which were copied for the Library. The Harbor does the same for links:
give it a URL and it reads the page's title, author and description so the
scroll arrives already labelled.
"""

from __future__ import annotations

import html
import re
import urllib.error
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urlparse

USER_AGENT = "WorldKnowledgeLibrary/1.0 (+personal knowledge archive)"
MAX_BYTES = 2_000_000

KIND_HINTS: list[tuple[str, str]] = [
    (r"(youtube\.com|youtu\.be|vimeo\.com|ted\.com/talks)", "video"),
    (r"(podcasts\.apple\.com|open\.spotify\.com/(episode|show)|overcast\.fm|pca\.st)", "podcast"),
    (r"(arxiv\.org|doi\.org|semanticscholar\.org|biorxiv\.org|pubmed|ssrn\.com|\.pdf($|\?))", "paper"),
    (r"(goodreads\.com|openlibrary\.org|books\.google\.)", "book"),
    (r"(coursera\.org|edx\.org|udemy\.com|khanacademy\.org)", "course"),
    (r"(kaggle\.com/datasets|data\.gov|huggingface\.co/datasets|zenodo\.org)", "dataset"),
]


class _MetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title = ""
        self._in_title = False
        self._skip = 0
        self.text: list[str] = []
        self._in_body = False

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            if key and a.get("content") and key not in self.meta:
                self.meta[key] = a["content"].strip()
        elif tag in ("script", "style", "noscript", "nav", "header", "footer", "aside"):
            self._skip += 1
        elif tag == "body":
            self._in_body = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag in ("script", "style", "noscript", "nav", "header", "footer", "aside"):
            self._skip = max(0, self._skip - 1)
        elif tag in ("p", "h1", "h2", "h3", "li", "blockquote") and self._in_body:
            self.text.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif self._in_body and not self._skip:
            self.text.append(data)


def guess_kind(url: str, og_type: str = "") -> str:
    for pattern, kind in KIND_HINTS:
        if re.search(pattern, url, re.I):
            return kind
    og_type = og_type.lower()
    if og_type.startswith("video"):
        return "video"
    if og_type in ("book", "books.book"):
        return "book"
    if og_type == "article":
        return "article"
    return "website" if urlparse(url).path in ("", "/") else "article"


def parse_html(url: str, page: str) -> dict:
    p = _MetaParser()
    try:
        p.feed(page)
    except Exception:  # malformed HTML should never stop a capture
        pass
    m = p.meta
    title = (m.get("og:title") or m.get("twitter:title") or p.title or "").strip()
    site = m.get("og:site_name", "")
    if site and title.endswith(site) and title != site:
        title = re.sub(r"\s*[-|–—·:]\s*$", "", title[: -len(site)]).strip() or title
    text = re.sub(r"[ \t\r\f\v]+", " ", "".join(p.text))
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return {
        "url": url,
        "title": html.unescape(" ".join(title.split())),
        "author": html.unescape(m.get("author") or m.get("article:author") or m.get("twitter:creator")
                                or m.get("book:author") or ""),
        "summary": html.unescape(m.get("og:description") or m.get("description")
                                 or m.get("twitter:description") or "").strip(),
        "site": site,
        "published": m.get("article:published_time") or m.get("datepublished") or "",
        "kind": guess_kind(url, m.get("og:type", "")),
        "excerpt": text[:1500],
    }


def fetch_metadata(url: str, timeout: float = 10.0) -> dict:
    """Read what a URL says about itself. Never raises for network trouble."""
    url = (url or "").strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    parsed = urlparse(url)
    fallback = {"url": url, "title": parsed.netloc + parsed.path.rstrip("/"), "author": "",
                "summary": "", "site": parsed.netloc, "published": "", "excerpt": "",
                "kind": guess_kind(url)}
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "text/html,application/xhtml+xml"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ctype = resp.headers.get("Content-Type", "")
            if "pdf" in ctype:
                fallback["kind"] = "paper"
                return fallback | {"error": ""}
            if "html" not in ctype and "xml" not in ctype:
                return fallback | {"error": f"Not a web page ({ctype or 'unknown type'})"}
            raw = resp.read(MAX_BYTES)
            charset = resp.headers.get_content_charset() or "utf-8"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return fallback | {"error": f"Could not reach the page: {getattr(exc, 'reason', exc)}"}
    data = parse_html(url, raw.decode(charset, errors="replace"))
    if not data["title"]:
        data["title"] = fallback["title"]
    return data | {"error": ""}
