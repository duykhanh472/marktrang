#!/usr/bin/env python3
"""
mark2web.py — Static Website Generator for Markdown books.

Converts a directory of Markdown files (book.yml + src/*.md + README.md)
into a fully self-contained static website with the visual design of
burgeonbook.org.

Design philosophy: Progressive Enhancement.
  - All content is 100% readable as plain HTML (no-JS, old browsers, e-readers).
  - JavaScript (reader.js) adds theme switching, font selection, alignment control,
    and chapter progress tracking ("Mark Done") only as an enhancement layer.

Usage:
    python mark2web.py <book_dir> [-o <output_dir>] [--serve [PORT]]
    python mark2web.py <book_dir> --push-gh-pages [--force-update] [--remote REMOTE]

Input structure:
    book_dir/
    ├── book.yml       # Required: metadata and chapter list
    ├── README.md      # Optional: rendered as about.html
    └── src/
        ├── 01.md      # Chapter files
        ├── 02.md
        └── images/    # Optional: chapter images

book.yml format (two styles supported):
    # Style A — key-value pairs per item (user-preferred):
    chapters:
      - 'Chapter 1': 01.md
      - 'Chapter 2': 02.md

    # Style B — explicit title/file dicts (mark2epub compatible):
    chapters:
      - title: 'Chapter 1'
        file: 01.md

Required Python packages:
    pip install markdown PyYAML Jinja2 beautifulsoup4
"""

import argparse
import datetime
import os
import re
import shutil
import subprocess
import sys
import http.server
import socketserver
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any

try:
    import yaml
except ImportError:
    sys.exit("[Error] PyYAML is required: pip install PyYAML")

try:
    import markdown
    from markdown.extensions.smarty import SmartyExtension
except ImportError:
    sys.exit("[Error] markdown is required: pip install markdown")

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
except ImportError:
    sys.exit("[Error] Jinja2 is required: pip install Jinja2")

# Directory where this script lives — used to locate assets/ and templates/
SCRIPT_DIR = Path(__file__).parent.resolve()
TEMPLATES_DIR = SCRIPT_DIR / "templates"
ASSETS_DIR    = SCRIPT_DIR / "assets"


# ==============================================================================
# Data Models
# ==============================================================================

@dataclass
class ChapterInfo:
    num: int
    title: str
    subtitle: str
    source_file: Path
    output_filename: str   # e.g. "1.html"

    @property
    def url(self) -> str:
        return self.output_filename


@dataclass
class DownloadLink:
    label: str
    url: str


@dataclass
class BookConfig:
    title: str
    author: str
    description: str
    language: str
    version: str
    cover: Optional[str]              # Relative path from book_dir root, e.g. "images/cover.jpg"
    banner: Optional[str]             # Optional announcement banner text
    downloads: List[DownloadLink]
    chapters: List[ChapterInfo]
    book_dir: Path                    # Absolute path to the input directory
    src_dir: Path                     # Absolute path to src/


# ==============================================================================
# Natural sort key (1, 2, ... 10, 11, not 1, 10, 11, 2 ...)
# ==============================================================================

def _natural_key(s: str):
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', s)]


# ==============================================================================
# Config Loader
# ==============================================================================

def load_book_config(book_dir_path: Path) -> BookConfig:
    """
    Loads book.yml and resolves all chapter paths inside src/.
    """
    book_dir = book_dir_path.resolve()

    config_path = book_dir / "book.yml"
    if not config_path.is_file():
        raise FileNotFoundError(
            f"Missing required 'book.yml' in: '{book_dir}'"
        )

    src_dir = book_dir / "src"
    if not src_dir.is_dir():
        raise FileNotFoundError(
            f"Missing required 'src/' directory in: '{book_dir}'"
        )

    with open(config_path, "r", encoding="utf-8") as f:
        cfg: Dict[str, Any] = yaml.safe_load(f) or {}

    # --- Basic metadata ---
    folder_title = book_dir.name.replace("-", " ").replace("_", " ").title()
    title        = str(cfg.get("title",  folder_title)).strip() or folder_title
    author       = str(cfg.get("author", "Anonymous")).strip() or "Anonymous"
    description  = str(cfg.get("description", "")).strip()
    language     = str(cfg.get("language", "en")).strip() or "en"
    version      = str(cfg.get("version", "")).strip()
    banner       = str(cfg.get("banner",  "")).strip() or None
    cover_raw    = cfg.get("cover")
    cover: Optional[str] = str(cover_raw).strip() if cover_raw else None

    # --- Downloads ---
    downloads: List[DownloadLink] = []
    for dl in cfg.get("downloads", []) or []:
        if isinstance(dl, dict):
            label = str(dl.get("label", dl.get("format", "Download"))).strip()
            url   = str(dl.get("url", "#")).strip()
            downloads.append(DownloadLink(label=label, url=url))

    # --- Chapters ---
    raw_chapters = cfg.get("chapters", []) or []
    chapter_pairs: List[tuple] = []  # (title, filename, subtitle)

    if raw_chapters:
        for item in raw_chapters:
            if isinstance(item, dict):
                # Style B: {title: ..., file: ...} or {title: ..., file: ..., subtitle: ...}
                if "title" in item and "file" in item:
                    chapter_pairs.append((
                        str(item["title"]).strip(),
                        str(item["file"]).strip(),
                        str(item.get("subtitle", "")).strip(),
                    ))
                # Style A: {'Chapter 1': '01.md'}  (single key-value pair)
                else:
                    keys = [k for k in item if k != "subtitle"]
                    if keys:
                        ch_title    = str(keys[0]).strip()
                        ch_filename = str(item[keys[0]]).strip()
                        ch_subtitle = str(item.get("subtitle", "")).strip()
                        chapter_pairs.append((ch_title, ch_filename, ch_subtitle))
    else:
        # Auto-scan src/ for .md files using natural sort
        md_files = sorted(src_dir.glob("*.md"), key=lambda p: _natural_key(p.name))
        for p in md_files:
            chapter_pairs.append(("", p.name, ""))

    # --- Build ChapterInfo list ---
    chapters: List[ChapterInfo] = []
    for idx, (specified_title, filename, subtitle) in enumerate(chapter_pairs, start=1):
        chapter_file = src_dir / filename
        if not chapter_file.is_file():
            raise FileNotFoundError(
                f"Chapter file '{filename}' listed in book.yml not found in '{src_dir}'"
            )

        # Determine title: specified > first H1 in file > file stem
        ch_title = specified_title
        if not ch_title:
            try:
                with open(chapter_file, "r", encoding="utf-8") as f:
                    for line in f:
                        stripped = line.strip()
                        if stripped.startswith("#"):
                            ch_title = stripped.lstrip("#").strip()
                            break
            except Exception:
                pass
        if not ch_title:
            ch_title = chapter_file.stem

        chapters.append(ChapterInfo(
            num=idx,
            title=ch_title,
            subtitle=subtitle,
            source_file=chapter_file,
            output_filename=f"{idx}.html",
        ))

    return BookConfig(
        title=title,
        author=author,
        description=description,
        language=language,
        version=version,
        cover=cover,
        banner=banner,
        downloads=downloads,
        chapters=chapters,
        book_dir=book_dir,
        src_dir=src_dir,
    )


# ==============================================================================
# Markdown → HTML Converter
# ==============================================================================

def make_md_parser() -> markdown.Markdown:
    return markdown.Markdown(
        extensions=[
            "tables",
            "fenced_code",
            "codehilite",
            "footnotes",
            "smarty",
            "toc",
            "attr_list",
            "nl2br",
        ],
        extension_configs={
            "codehilite": {"guess_lang": False, "css_class": "codehilite"},
            "smarty": {
                "smart_quotes": True,
                "smart_dashes": True,
                "smart_ellipses": True,
            },
        },
    )


def md_to_html(md_text: str, md_parser: markdown.Markdown) -> str:
    md_parser.reset()
    return md_parser.convert(md_text)


# ==============================================================================
# Jinja2 Environment & Filters
# ==============================================================================

def make_jinja_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )

    # Custom filter: basename (last component of a path)
    def _basename(value: str) -> str:
        return Path(str(value)).name

    env.filters["basename"] = _basename
    return env


# ==============================================================================
# Output Builder
# ==============================================================================

class WebsiteBuilder:
    def __init__(self, config: BookConfig, output_dir: Path):
        self.cfg    = config
        self.out    = output_dir
        self.env    = make_jinja_env()
        self.md     = make_md_parser()
        self._setup_output_dir()

    # ------------------------------------------------------------------
    # Output directory setup
    # ------------------------------------------------------------------

    def _setup_output_dir(self):
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "chapter").mkdir(exist_ok=True)

    # ------------------------------------------------------------------
    # Asset copying
    # ------------------------------------------------------------------

    def _copy_assets(self):
        """Copy static assets (css, js, fonts, images) from assets/."""
        for sub in ("css", "js", "fonts", "images"):
            src = ASSETS_DIR / sub
            dst = self.out / sub
            if src.is_dir():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(str(src), str(dst))

    def _copy_book_images(self):
        """Copy book-specific images from src/images/ and cover into dist/images/."""
        dst_images = self.out / "images"
        dst_images.mkdir(exist_ok=True)

        # src/images/
        src_images = self.cfg.src_dir / "images"
        if src_images.is_dir():
            for img_file in src_images.iterdir():
                if img_file.is_file():
                    shutil.copy2(str(img_file), str(dst_images / img_file.name))

        # Cover at book_dir root (if specified)
        if self.cfg.cover:
            cover_src = self.cfg.book_dir / self.cfg.cover
            if cover_src.is_file():
                # Place it flat inside images/ directory
                shutil.copy2(str(cover_src), str(dst_images / cover_src.name))

        # favicon: use cover or default
        favicon_dst = self.out / "favicon.png"
        favicon_src = ASSETS_DIR / "images" / "fluerstar1.png"
        # Try a favicon in the book root first
        for candidate in ["favicon.png", "favicon.ico"]:
            cand_path = self.cfg.book_dir / candidate
            if cand_path.is_file():
                shutil.copy2(str(cand_path), str(favicon_dst))
                break
        else:
            if favicon_src.is_file() and not favicon_dst.exists():
                shutil.copy2(str(favicon_src), str(favicon_dst))

    # ------------------------------------------------------------------
    # Template rendering helpers
    # ------------------------------------------------------------------

    def _base_context(self) -> dict:
        """Common Jinja2 context values shared by all pages."""
        return {
            "book": self.cfg,
            "chapters": self.cfg.chapters,
            "downloads": self.cfg.downloads,
            "readme_exists": (self.cfg.book_dir / "README.md").is_file(),
        }

    def _render(self, template_name: str, context: dict) -> str:
        tmpl = self.env.get_template(template_name)
        return tmpl.render(**context)

    def _write(self, path: Path, html: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"    ✓  {path.relative_to(self.out)}")

    # ------------------------------------------------------------------
    # Page generators
    # ------------------------------------------------------------------

    def render_index(self):
        ctx = self._base_context()
        ctx["page_title"] = self.cfg.title
        ctx["root_path"]  = ""
        ctx["og_image_path"] = (
            f"./images/{Path(self.cfg.cover).name}" if self.cfg.cover else ""
        )
        html = self._render("index.html", ctx)
        self._write(self.out / "index.html", html)

    def render_about(self):
        readme = self.cfg.book_dir / "README.md"
        if not readme.is_file():
            return

        with open(readme, "r", encoding="utf-8") as f:
            md_text = f.read()

        ctx = self._base_context()
        ctx["page_title"]  = f"About — {self.cfg.title}"
        ctx["root_path"]   = ""
        ctx["about_html"]  = md_to_html(md_text, self.md)
        html = self._render("about.html", ctx)
        self._write(self.out / "about.html", html)

    def render_chapters(self):
        chapters = self.cfg.chapters
        for i, chapter in enumerate(chapters):
            with open(chapter.source_file, "r", encoding="utf-8") as f:
                md_text = f.read()

            ctx = self._base_context()
            ctx["page_title"]    = f"Chapter {chapter.num} — {chapter.title} ({self.cfg.title})"
            ctx["root_path"]     = "../"
            ctx["chapter"]       = chapter
            ctx["in_chapter"]    = True
            ctx["chapter_html"]  = md_to_html(md_text, self.md)
            ctx["prev_chapter"]  = chapters[i - 1] if i > 0 else None
            ctx["next_chapter"]  = chapters[i + 1] if i < len(chapters) - 1 else None

            html = self._render("chapter.html", ctx)
            self._write(self.out / "chapter" / chapter.output_filename, html)

    # ------------------------------------------------------------------
    # Main build orchestration
    # ------------------------------------------------------------------

    def build(self):
        print(f"\n[*] Copying static assets...")
        self._copy_assets()
        self._copy_book_images()

        print(f"\n[*] Rendering pages...")
        self.render_index()
        self.render_about()
        self.render_chapters()

        print(f"\n[✓] Build complete → {self.out}\n")


# ==============================================================================
# Dev Server
# ==============================================================================

def serve(out_dir: Path, port: int = 8080):
    """Launch a simple HTTP server in out_dir for local preview."""
    os.chdir(out_dir)
    handler = http.server.SimpleHTTPRequestHandler
    # Silence GET/HEAD log noise for quick preview
    handler.log_message = lambda self, fmt, *args: None

    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"[>] Preview server running at http://localhost:{port}/")
        print(f"    Press Ctrl+C to stop.\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[*] Server stopped.")


# ==============================================================================
# GitHub Pages Deploy
# ==============================================================================

def _git(args: List[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command in `cwd`, streaming output to the terminal."""
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        check=check,
    )


def _git_out(args: List[str], cwd: Path) -> str:
    """Run a git command and return its stdout as a stripped string."""
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def deploy_gh_pages(
    out_dir: Path,
    repo_dir: Path,
    remote: str = "origin",
    force_update: bool = False,
) -> None:
    """
    Push the contents of `out_dir` to the `gh-pages` branch of the git
    repository at `repo_dir`.

    Behaviour mirrors deploy-gh-pages.sh:
      - Must be on `main` branch with a clean working tree.
      - Skips push if output is identical to the previous deploy AND
        --force-update is not set.
      - Always force-pushes to gh-pages (the branch is treated as a
        generated artefact, not a development branch).
      - Returns to the original branch after deploying.

    Args:
        out_dir:      Directory that contains the built website files.
        repo_dir:     Root of the git repository (must contain .git/).
        remote:       Git remote name (default: "origin").
        force_update: Push even when build output is identical to last deploy.
    """
    TARGET_BRANCH = "gh-pages"
    LAST_BUILD_FILE = ".last_build_commit"

    # ------------------------------------------------------------------ sanity
    if not (repo_dir / ".git").is_dir():
        raise RuntimeError(
            f"'{repo_dir}' is not a git repository (.git not found)."
        )
    if not out_dir.is_dir():
        raise RuntimeError(
            f"Output directory '{out_dir}' does not exist. "
            "Run the build step first."
        )

    # -------------------------------------------------------- guard: main only
    current_branch = _git_out(["rev-parse", "--abbrev-ref", "HEAD"], repo_dir)
    if current_branch != "main":
        raise RuntimeError(
            f"You are on branch '{current_branch}'. "
            "Please checkout 'main' before deploying."
        )

    # --------------------------------------------------- guard: clean worktree
    dirty = subprocess.run(
        ["git", "diff-index", "--quiet", "HEAD", "--"],
        cwd=str(repo_dir),
    ).returncode != 0
    if dirty:
        raise RuntimeError(
            "Working tree is not clean. "
            "Please commit or stash all changes before deploying."
        )

    main_commit = _git_out(["rev-parse", "HEAD"], repo_dir)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ----------------------------------- ensure gh-pages branch exists locally
    branches_raw = _git_out(["branch", "--list", TARGET_BRANCH], repo_dir)
    gh_pages_exists_locally = bool(branches_raw)

    if not gh_pages_exists_locally:
        # Check if it exists on the remote
        remote_branches = subprocess.run(
            ["git", "ls-remote", "--heads", remote, TARGET_BRANCH],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
        ).stdout.strip()

        if remote_branches:
            # Fetch and track it
            print(f"[*] Fetching existing '{TARGET_BRANCH}' from '{remote}'...")
            _git(["fetch", remote, TARGET_BRANCH], repo_dir)
            _git(["checkout", "-b", TARGET_BRANCH, f"{remote}/{TARGET_BRANCH}"], repo_dir)
        else:
            # Create a fresh orphan branch
            print(f"[*] Creating new orphan branch '{TARGET_BRANCH}'...")
            _git(["checkout", "--orphan", TARGET_BRANCH], repo_dir)
            _git(["rm", "-rf", "."], repo_dir, check=False)
            _git(["commit", "--allow-empty", "-m", f"Initial gh-pages branch"], repo_dir)
        # Go back to main so the rest of the flow is uniform
        _git(["checkout", "main"], repo_dir)

    # ----------------------------------------- optional: skip if nothing new
    if not force_update:
        # Read last deployed commit from gh-pages branch (without switching)
        try:
            last_commit = _git_out(
                ["show", f"{TARGET_BRANCH}:{LAST_BUILD_FILE}"],
                repo_dir,
            )
            if last_commit == main_commit:
                print(
                    f"[i] No changes on main since last deploy ({main_commit[:8]}). "
                    "Skipping. Use --force-update to override."
                )
                return
        except subprocess.CalledProcessError:
            pass  # File doesn't exist yet — first deploy

    # ----------------------------------------------- copy output to a tmp dir
    import tempfile
    tmp_dir = Path(tempfile.mkdtemp(prefix="mark2web_ghpages_"))
    try:
        print(f"[*] Copying build output to staging area...")
        # Copy everything from out_dir into tmp_dir
        for item in out_dir.iterdir():
            src = out_dir / item.name
            dst = tmp_dir / item.name
            if src.is_dir():
                shutil.copytree(str(src), str(dst))
            else:
                shutil.copy2(str(src), str(dst))

        # Write the sentinel file so we can skip unchanged deploys later
        (tmp_dir / LAST_BUILD_FILE).write_text(main_commit + "\n", encoding="utf-8")

        # ------------------------------------------- switch to gh-pages branch
        print(f"[*] Switching to '{TARGET_BRANCH}'...")
        _git(["checkout", "-f", TARGET_BRANCH], repo_dir)

        try:
            # Verify branch switch succeeded
            actual = _git_out(["rev-parse", "--abbrev-ref", "HEAD"], repo_dir)
            if actual != TARGET_BRANCH:
                raise RuntimeError(
                    f"Expected to be on '{TARGET_BRANCH}', got '{actual}'."
                )

            # ------------------------------------------- wipe old content
            print("[*] Removing old content...")
            _git(["rm", "-rf", "."], repo_dir, check=False)

            # ------------------------------------------- copy new content
            print("[*] Copying new build output...")
            for item in tmp_dir.iterdir():
                src = tmp_dir / item.name
                dst = repo_dir / item.name
                if src.is_dir():
                    shutil.copytree(str(src), str(dst))
                else:
                    shutil.copy2(str(src), str(dst))

            # ------------------------------------- add, commit, push
            _git(["add", "."], repo_dir)

            # Check if anything actually changed
            nothing_changed = subprocess.run(
                ["git", "diff-index", "--quiet", "HEAD", "--"],
                cwd=str(repo_dir),
            ).returncode == 0

            if nothing_changed:
                if force_update:
                    print("⚠️  Build output unchanged, but pushing anyway (--force-update).")
                    _git(
                        ["commit", "--allow-empty", "-m",
                         f"Force deploy @ {main_commit[:8]} ({timestamp})"],
                        repo_dir,
                    )
                else:
                    print(
                        "[i] Build output is identical to the previous deploy. "
                        "Nothing to push."
                    )
                    _git(["checkout", current_branch], repo_dir)
                    return
            else:
                _git(
                    ["commit", "-m",
                     f"Deploy from main @ {main_commit[:8]} ({timestamp})"],
                    repo_dir,
                )

            print(f"🚀 Force-pushing to {remote}/{TARGET_BRANCH}...")
            _git(["push", "--force", remote, TARGET_BRANCH], repo_dir)
            print("✨ Deploy completed successfully!")

        finally:
            # Always return to the original branch
            print(f"[*] Returning to branch '{current_branch}'...")
            _git(["checkout", current_branch], repo_dir)

    finally:
        shutil.rmtree(str(tmp_dir), ignore_errors=True)


# ==============================================================================
# CLI Entry Point
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        prog="mark2web",
        description=(
            "Convert a Markdown book directory to a static website.\n"
            "Requires 'book.yml' and a 'src/' folder inside book_dir."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "book_dir",
        help="Path to the book directory containing 'book.yml' and 'src/'",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        metavar="OUTPUT_DIR",
        help="Output directory (default: <book_dir>/dist/)",
    )
    parser.add_argument(
        "--serve",
        nargs="?",
        const=8080,
        type=int,
        metavar="PORT",
        help="Start a local preview server after building (default port: 8080)",
    )
    parser.add_argument(
        "--push-gh-pages",
        action="store_true",
        help=(
            "After building, push the output to the 'gh-pages' branch of the\n"
            "git repository that contains book_dir (or the repo specified by\n"
            "--repo-dir). Must be run from the 'main' branch with a clean\n"
            "working tree."
        ),
    )
    parser.add_argument(
        "--repo-dir",
        default=None,
        metavar="REPO_DIR",
        help=(
            "Root of the git repository to deploy to. Defaults to book_dir.\n"
            "Useful when book_dir is a subdirectory of the repo root."
        ),
    )
    parser.add_argument(
        "--remote",
        default="origin",
        metavar="REMOTE",
        help="Git remote to push to (default: origin)",
    )
    parser.add_argument(
        "--force-update",
        action="store_true",
        help="Push even if the build output is identical to the last deploy.",
    )

    args = parser.parse_args()

    book_dir = Path(args.book_dir).resolve()
    if not book_dir.is_dir():
        print(f"[Error] Directory not found: '{book_dir}'", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output).resolve() if args.output else book_dir / "dist"

    try:
        print(f"[*] Loading book config from: '{book_dir}'")
        config = load_book_config(book_dir)
        print(f"    Title:    {config.title}")
        print(f"    Author:   {config.author}")
        print(f"    Language: {config.language}")
        print(f"    Chapters: {len(config.chapters)}")
        if config.cover:
            print(f"    Cover:    {config.cover}")
        if config.downloads:
            print(f"    Downloads:{len(config.downloads)} link(s)")
    except Exception as e:
        print(f"\n[Error] {e}", file=sys.stderr)
        sys.exit(1)

    try:
        builder = WebsiteBuilder(config, output_dir)
        builder.build()
    except Exception as e:
        print(f"\n[Error during build] {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

    if args.push_gh_pages:
        repo_dir = Path(args.repo_dir).resolve() if args.repo_dir else book_dir
        try:
            deploy_gh_pages(
                out_dir=output_dir,
                repo_dir=repo_dir,
                remote=args.remote,
                force_update=args.force_update,
            )
        except Exception as e:
            print(f"\n[Error during deploy] {e}", file=sys.stderr)
            sys.exit(1)

    if args.serve is not None:
        serve(output_dir, port=args.serve)


if __name__ == "__main__":
    main()
