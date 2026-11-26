"""Storage layer: a single SQLite file holds the whole library.

The schema is versioned through ``PRAGMA user_version`` so that future
releases can migrate an existing library in place instead of starting over.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS wings (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description TEXT NOT NULL DEFAULT '',
    emblem      TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scrolls (
    id          INTEGER PRIMARY KEY,
    title       TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'note',
    status      TEXT NOT NULL DEFAULT 'inbox',
    source_url  TEXT NOT NULL DEFAULT '',
    author      TEXT NOT NULL DEFAULT '',
    summary     TEXT NOT NULL DEFAULT '',
    content     TEXT NOT NULL DEFAULT '',
    rating      INTEGER CHECK (rating IS NULL OR rating BETWEEN 1 AND 5),
    wing_id     INTEGER REFERENCES wings(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_scrolls_status ON scrolls(status);
CREATE INDEX IF NOT EXISTS idx_scrolls_kind ON scrolls(kind);
CREATE INDEX IF NOT EXISTS idx_scrolls_wing ON scrolls(wing_id);
CREATE INDEX IF NOT EXISTS idx_scrolls_title ON scrolls(title COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS tags (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS scroll_tags (
    scroll_id INTEGER NOT NULL REFERENCES scrolls(id) ON DELETE CASCADE,
    tag_id    INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (scroll_id, tag_id)
);

-- Links between scrolls, derived from [[wiki links]] in their content.
CREATE TABLE IF NOT EXISTS links (
    from_id INTEGER NOT NULL REFERENCES scrolls(id) ON DELETE CASCADE,
    to_id   INTEGER NOT NULL REFERENCES scrolls(id) ON DELETE CASCADE,
    PRIMARY KEY (from_id, to_id)
);
CREATE INDEX IF NOT EXISTS idx_links_to ON links(to_id);

-- Marginalia: highlights, notes and questions written beside a scroll.
CREATE TABLE IF NOT EXISTS marginalia (
    id         INTEGER PRIMARY KEY,
    scroll_id  INTEGER NOT NULL REFERENCES scrolls(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL DEFAULT 'note',
    quote      TEXT NOT NULL DEFAULT '',
    body       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_marginalia_scroll ON marginalia(scroll_id);

-- Palimpsest: every earlier version of a scroll, kept when it is rewritten.
CREATE TABLE IF NOT EXISTS palimpsest (
    id         INTEGER PRIMARY KEY,
    scroll_id  INTEGER NOT NULL REFERENCES scrolls(id) ON DELETE CASCADE,
    title      TEXT NOT NULL,
    summary    TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_palimpsest_scroll ON palimpsest(scroll_id);

-- Pharos: spaced-repetition schedule for scrolls worth keeping alive in memory.
CREATE TABLE IF NOT EXISTS pharos (
    scroll_id     INTEGER PRIMARY KEY REFERENCES scrolls(id) ON DELETE CASCADE,
    due_at        TEXT NOT NULL,
    interval_days REAL NOT NULL DEFAULT 0,
    ease          REAL NOT NULL DEFAULT 2.5,
    repetitions   INTEGER NOT NULL DEFAULT 0,
    lapses        INTEGER NOT NULL DEFAULT 0,
    last_reviewed TEXT
);
CREATE INDEX IF NOT EXISTS idx_pharos_due ON pharos(due_at);

-- Full-text index over the catalogue (kept in sync by the Library class).
CREATE VIRTUAL TABLE IF NOT EXISTS scrolls_fts USING fts5(
    title, author, summary, content, tags, marginalia,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    """Open (and if needed create) a library database."""
    if str(path) != ":memory:":
        Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise RuntimeError(
            f"This library was written by a newer version (schema {version}); "
            f"this build understands up to schema {SCHEMA_VERSION}."
        )
    if version < 1:
        conn.executescript(SCHEMA)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
