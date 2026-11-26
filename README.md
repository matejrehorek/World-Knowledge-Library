# World Knowledge Library

*A living library for everything you read, watch, learn and think.*

The Great Library of Alexandria set out to hold a copy of every book in the known
world. Ships docking in its harbour were searched for scrolls, which were copied for
the shelves; Callimachus catalogued it all in the *Pinakes*; scholars of the Mouseion
wrote in the margins, compared editions and argued. It was lost slowly, not in a
single fire, because it stopped being tended.

The World Knowledge Library is the personal version of that ambition: one place for
the articles, books, papers, videos, podcasts, courses, datasets, quotes and ideas
you take in, catalogued, linked to each other, and kept alive by revisiting them.

> Knowledge that is not tended is lost.

It runs entirely on your machine, in one SQLite file, using only the Python standard
library. There is nothing to sign up for, and nothing leaves your computer except
when you ask it to read a link.

## Quick start

```bash
pip install -e .            # or just use `python -m wkl` from this folder
wkl demo                    # shelve the founding collection (a few linked scrolls)
wkl serve --open            # open the reading room at http://localhost:8331
```

Port 8331 is a nod to 331 BC, when Alexandria was founded. Your library lives
at `~/.world-knowledge-library/library.db`. To use a different file, set
`WKL_LIBRARY` or pass `--library PATH`.

## The rooms

| Room | What it does |
| --- | --- |
| **Atrium** | Home. A census of the collection, quick capture, recently tended scrolls, a year of activity, a scroll pulled at random, and what the Pharos has due. |
| **Harbor** | The inbox. Paste a link and its title, author, description and likely kind (video, paper, book…) are read for you. New arrivals wait here until you queue, study or shelve them. |
| **Pinakes** | The catalogue: ranked full-text search over titles, authors, summaries, bodies, tags and marginalia, with filters. |
| **Scrolls** | Each item: Markdown body, summary, rating, status, tags, wing, source. Includes backlinks, outgoing links, *unwritten* links (to scrolls that don't exist yet) and *kin by subject* (related by shared tags and vocabulary). |
| **Marginalia** | Notes, highlights, questions and insights written beside a scroll. They are searchable too. |
| **Palimpsest** | Every earlier version of a scroll, kept when you rewrite it, with a word-level comparison and one-click restore. |
| **Pharos** | Spaced review, named after the lighthouse. Scrolls you choose to "keep alive" return at growing intervals. Recall them, unroll them and grade your memory; the schedule adapts. |
| **Constellation** | An interactive graph of your scrolls and the links between them, optionally with shared-tag affinities, coloured by kind. |
| **Wings** | Broad collections (a field, a project, a season of life). Tags cut across them. |
| **Serapeum** | Named after Alexandria's daughter library. Export a full JSON archive, import one, see the shape of the collection, rename or merge tags, and get a bookmarklet that captures any page you are reading. |

### Linking

Write `[[Title]]` (or `[[Title|shown text]]`) anywhere in a body to link to another
scroll. While editing, typing `[[` offers matching titles. Links resolve
automatically when the target is written later or renamed, and every link shows up
as a backlink on the other side.

### Call numbers

Every scroll gets a call number made of a genre mark and its accession number, for
example `BK-0042` for a book or `PA-0007` for a paper, in honour of Callimachus'
genre-ordered catalogue. In the CLI you can refer to a scroll by id, call number or
title.

### Search syntax

```
stoic virtue                   words (prefix-matched), ranked by relevance
"short time"                   an exact phrase
tag:philosophy kind:book       filters: tag, kind, status, wing, author
status:queued wing:Antiquity
is:orphan  is:remembered  is:rated
```

Kinds: `note idea article book paper video podcast course dataset quote website other`.
Statuses: `inbox` (In the Harbor), `queued` (Awaiting), `active` (Under study), `done` (Shelved).

## The command line

```bash
wkl capture https://example.org/essay -t history     # dock a link in the Harbor
wkl add "Meditations" -k book -a "Marcus Aurelius" -t "stoicism, philosophy" -w Philosophy
wkl add "Note to self" -c @notes.md                   # body from a file ('-' reads stdin)
wkl search tag:stoicism                               # alias: wkl ls
wkl show BK-0003                                      # by id, call number or title
wkl set Meditations --status done --rating 5
wkl edit Meditations                                  # rewrite the body in $EDITOR
wkl note Meditations "Begin the morning by saying…" --kind highlight
wkl remember Meditations                              # keep it alive with the Pharos
wkl review                                            # a review session in the terminal
wkl random                                            # serendipity
wkl wings --add Philosophy -e 🦉
wkl tags --rename ml machine-learning
wkl stats
wkl export -o backup.json                             # full archive
wkl export --markdown ./library-md                    # one Markdown file per scroll
wkl import ./my-obsidian-vault                        # Markdown notes with front matter
wkl import backup.json
```

## Your knowledge stays portable

- **JSON archive**: lossless, including marginalia, review schedules and the palimpsest.
  Importing merges and skips scrolls already present.
- **Markdown export**: one file per scroll with YAML front matter, grouped into folders
  by wing. It reads well in any editor and opens as an Obsidian vault.
- **Markdown import**: brings in folders of notes such as an Obsidian vault. Front-matter
  `title`, `tags`, `author`, `kind`, `status`, `source`/`url` and `rating` are
  understood, subfolders become wings, and `[[wiki links]]` are kept.

## Architecture

```
wkl/
  db.py          SQLite schema (FTS5 full-text index), versioned migrations
  catalogue.py   kinds, statuses, call numbers
  library.py     all domain logic: scrolls, links, search, related, Pharos, stats
  harbor.py      reading metadata from URLs
  serapeum.py    JSON and Markdown import/export
  founding.py    the demo collection
  server.py      JSON API + static files (http.server)
  cli.py         the `wkl` command
  static/        the reading room: index.html, styles.css, app.js (no build step)
tests/           pytest suite
```

There are no third-party runtime dependencies. The web UI is plain JavaScript with its
own small, escaping Markdown renderer. The server binds to `127.0.0.1` by default. It
refuses cross-origin writes, non-JSON request bodies and unexpected `Host` headers, so
other websites cannot read or change your library. The Google Fonts stylesheet is the
only external request, and the UI falls back to system fonts when offline.

### API

All endpoints are under `/api` and speak JSON: `scrolls` (GET search, POST create),
`scrolls/{id}` (GET, PATCH, DELETE), `scrolls/{id}/marginalia`, `scrolls/{id}/revisions`,
`revisions/{id}/restore`, `scrolls/{id}/remember`, `pharos`, `pharos/{id}` (grade),
`wings`, `tags`, `tags/rename`, `graph`, `stats`, `random`, `titles`,
`harbor/fetch`, `serapeum/export`, `serapeum/import`, `meta`.

## Development

```bash
pip install -e ".[dev]"
pytest
```
