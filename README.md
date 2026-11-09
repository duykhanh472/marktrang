# mark2web

A Python CLI tool that converts a directory of Markdown chapter files into a fully self-contained static website for reading books online — inspired by the visual design of [burgeonbook.org](https://burgeonbook.org/).

## Features

- Static HTML output — host on GitHub Pages, Netlify, Cloudflare Pages, or open `index.html` directly.
- Progressive Enhancement — 100% readable without JavaScript (old browsers, e-readers, Lynx/w3m).
- 6 Themes — Warm Dark, Cool Dark, Light, Light Grid, Retro, OLED Black.
- 6 Fonts — Open Sans, PT Serif, PT Sans, Monnaco, Georgia, Open Dyslexic.
- Text alignment — Left, Center, Right (remembered in `localStorage`).
- Chapter progress — "Mark Done" button with progress dots in the side navigation.
- Mobile responsive — side-nav collapses to a drawer on small screens.
- Legacy browser CSS fallbacks — static color and font fallbacks before every `var(--...)`.
- Safe `localStorage` — `try/catch` around all storage calls (Private Mode safe).

## Dependencies

```bash
pip install markdown PyYAML Jinja2 beautifulsoup4
```

Python ≥ 3.8 required.

## Input structure

```
my-book/
├── book.yml       # Required: book metadata and chapter list
├── README.md      # Optional: rendered as about.html
└── src/
    ├── 01.md      # Chapter files (numbered for natural sort)
    ├── 02.md
    ├── 03.md
    └── images/    # Optional: images referenced in chapters
```

## book.yml format

```yaml
title: "My Book Title"
author: Jane Austen
description: A short description of the book.
language: en
version: "1.0"
cover: images/cover.jpg   # Optional

downloads:
  - label: "Download EPUB"
    url: "https://example.com/book.epub"
  - label: "Download PDF"
    url: "https://example.com/book.pdf"

# Style A — key:value per chapter item (recommended):
chapters:
  - 'Chapter 1': 01.md
  - 'Chapter 2': 02.md
  - 'Chapter 3': 03.md

# Omit `chapters` entirely to auto-scan src/*.md in natural order.
```

## Usage

```bash
# Build website into <book_dir>/dist/
python mark2web.py ./my-book

# Build into a specific output directory
python mark2web.py ./my-book -o ./public

# Build and start a local preview server (default port 8080)
python mark2web.py ./my-book --serve

# Custom port
python mark2web.py ./my-book --serve 3000

# Build then push to GitHub Pages (branch: gh-pages)
python mark2web.py ./my-book --push-gh-pages

# Push even if output hasn't changed
python mark2web.py ./my-book --push-gh-pages --force-update

# When book_dir is a subdirectory of the repo root, specify the repo explicitly
python mark2web.py ./my-book --push-gh-pages --repo-dir .

# Push to a non-default remote
python mark2web.py ./my-book --push-gh-pages --remote upstream
```

### `--push-gh-pages` requirements

| Requirement | Detail |
|:--|:--|
| Current branch | Must be `main` |
| Working tree | Must be clean (no uncommitted changes) |
| Remote | Must be configured (`origin` by default) |
| `git` | Must be available on `PATH` |

The deploy flow:

1. Builds the website into the output directory (same as a normal build).
2. Stashes the build output in a temp directory.
3. Switches to the `gh-pages` branch (creates it as an orphan if it doesn't exist).
4. Wipes all old content and replaces it with the new build.
5. Commits with message `Deploy from main @ <sha> (<timestamp>)`.
6. Force-pushes to `gh-pages`.
7. Returns to `main`.

A `.last_build_commit` sentinel file is written to the `gh-pages` branch after each deploy. If the same commit is detected on a subsequent run, the push is skipped automatically (override with `--force-update`).

## Output structure

```
dist/
├── index.html         # Home page with TOC and download links
├── about.html         # About page from README.md
├── favicon.png
├── chapter/
│   ├── 1.html
│   ├── 2.html
│   └── 3.html
├── css/
│   └── global.css
├── js/
│   └── reader.js
├── fonts/
│   ├── open-sans.ttf
│   ├── pt-serif.ttf
│   ├── pt-sans.ttf
│   ├── monnaco.otf
│   ├── georgia.ttf
│   └── open-dyslexic.otf
└── images/
    ├── fluerstar1.png
    ├── fluer1.svg
    ├── settings-outline.svg
    ├── home-outline.svg
    ├── download-outline.svg
    └── background-grid.png
```

## Running Tests

```bash
python tests/test_builder.py
```

## Companion tool

[mark2epub](../mark2epub/) — converts the same book directory into a standard EPUB 3 ebook. Both tools share the same `book.yml` input format and `src/` directory layout.
