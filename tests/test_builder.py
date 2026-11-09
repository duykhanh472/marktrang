#!/usr/bin/env python3
"""
test_builder.py — Automated tests for mark2web.py

Tests:
  1. Config loading (both YAML chapter formats)
  2. HTML output completeness (all expected files present)
  3. No-JS correctness (links not disabled, js-only class presence)
  4. CSS fallback presence
  5. Navigation integrity (prev/next links per chapter)
  6. <noscript> and class="no-js" presence

Usage:
    python tests/test_builder.py
"""

import subprocess
import sys
import os
from pathlib import Path

try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("BeautifulSoup4 required: pip install beautifulsoup4")

SCRIPT_DIR  = Path(__file__).parent.parent.resolve()
SAMPLE_BOOK = Path(__file__).parent / "sample_book"
OUTPUT_DIR  = Path(__file__).parent / "output"
MARK2WEB    = SCRIPT_DIR / "mark2web.py"

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"

failures = []


def check(condition: bool, description: str):
    if condition:
        print(f"  {PASS}  {description}")
    else:
        print(f"  {FAIL}  {description}")
        failures.append(description)


# ==============================================================================
# Step 1: Run the builder
# ==============================================================================
print("\n[1] Running mark2web builder on sample_book/ ...")
result = subprocess.run(
    [sys.executable, str(MARK2WEB), str(SAMPLE_BOOK), "-o", str(OUTPUT_DIR)],
    capture_output=True, text=True
)
print(result.stdout)
if result.returncode != 0:
    print(result.stderr)
    sys.exit(f"[Error] Builder failed with exit code {result.returncode}")

# ==============================================================================
# Step 2: Check all expected files exist
# ==============================================================================
print("\n[2] Checking output files exist ...")
expected_files = [
    "index.html",
    "about.html",
    "chapter/1.html",
    "chapter/2.html",
    "chapter/3.html",
    "css/global.css",
    "js/reader.js",
    "fonts/open-sans.ttf",
    "fonts/monnaco.otf",
    "fonts/pt-serif.ttf",
    "fonts/pt-sans.ttf",
    "fonts/georgia.ttf",
    "fonts/open-dyslexic.otf",
    "images/settings-outline.svg",
    "images/fluerstar1.png",
    "images/home-outline.svg",
    "images/download-outline.svg",
]
for rel in expected_files:
    path = OUTPUT_DIR / rel
    check(path.exists(), f"File exists: {rel}")


# ==============================================================================
# Helper: parse an HTML file
# ==============================================================================
def parse(rel_path: str) -> BeautifulSoup:
    return BeautifulSoup((OUTPUT_DIR / rel_path).read_text(encoding="utf-8"), "html.parser")


# ==============================================================================
# Step 3: index.html checks
# ==============================================================================
print("\n[3] Checking index.html ...")
soup = parse("index.html")

check(soup.find("html")["class"] == ["no-js"], "<html> has class='no-js'")
check(bool(soup.find("noscript")),             "<noscript> tag present")
check("An Example Book for Testing" in soup.find("title").text, "<title> contains book title")

# TOC links: 3 chapters
toc_links = soup.select("ul.toc-list a")
check(len(toc_links) == 3, f"TOC has 3 chapter links (found {len(toc_links)})")

# TOC link hrefs should be chapter/N.html
for i, link in enumerate(toc_links, start=1):
    href = link.get("href", "")
    check(href == f"chapter/{i}.html", f"TOC link {i} href='chapter/{i}.html' (got '{href}')")

# About link present
about_link = soup.find("a", href="about.html")
check(bool(about_link), "Link to about.html present on index page")

# Downloads section
dl_section = soup.find(id="downloads-section")
check(bool(dl_section), "Downloads section (#downloads-section) present")


# ==============================================================================
# Step 4: about.html checks
# ==============================================================================
print("\n[4] Checking about.html ...")
soup = parse("about.html")

check(soup.find("html")["class"] == ["no-js"],    "<html> has class='no-js'")
check(bool(soup.find("noscript")),                 "<noscript> tag present")
check("About" in soup.find("title").text,          "<title> mentions 'About'")
check(bool(soup.select_one("a[href='index.html']")),"Back to Home link present")

# README content rendered
writeup = soup.select_one("#about-content")
check(bool(writeup),                               "#about-content div present")
check(bool(writeup and writeup.find("p")),          "README.md content rendered as <p> tags")


# ==============================================================================
# Step 5: chapter/1.html — No-JS correctness
# ==============================================================================
print("\n[5] Checking chapter/1.html (No-JS correctness) ...")
soup = parse("chapter/1.html")

check(soup.find("html")["class"] == ["no-js"],     "<html> has class='no-js'")

# Mark Done button must have class js-only
mark_done = soup.find("button", class_="mark_done_button")
check(bool(mark_done),                             "Mark Done button exists")
if mark_done:
    check("js-only" in (mark_done.get("class") or []), "Mark Done has class 'js-only'")

# Settings icon must have class js-only
settings_icon = soup.find(class_="open-settings-btn")
check(bool(settings_icon),                          "Settings button exists")
if settings_icon:
    check("js-only" in (settings_icon.get("class") or []), "Settings icon has class 'js-only'")

# Next chapter button must be inside an <a> tag and NOT disabled
next_btn = soup.find("button", class_="completion-button")
check(bool(next_btn),                              "Next chapter button exists")
if next_btn:
    parent_a = next_btn.find_parent("a")
    check(bool(parent_a),                          "Next chapter button is inside <a> tag")
    if parent_a:
        check(bool(parent_a.get("href")),          "Next chapter <a> has valid href")

    check("disabled" not in (next_btn.attrs or {}), "Next chapter button is NOT disabled")

# No Previous button on chapter 1
prev_btn = soup.find("button", string=lambda t: t and "Chapter" in t and "←" in t)
check(prev_btn is None,                            "No 'Previous' button on chapter 1")


# ==============================================================================
# Step 6: chapter/2.html — Navigation links
# ==============================================================================
print("\n[6] Checking chapter/2.html (navigation) ...")
soup = parse("chapter/2.html")

# Active chapter in side-nav
active_links = soup.select(".side-nav .active-link")
check(len(active_links) == 1,                     "Exactly one active-link in side-nav")
if active_links:
    check(active_links[0].get_text(strip=True) == "2", "Active link is chapter 2")

# Previous button links to 1.html
nav_btns = soup.find_all("a", class_="nav-button")
hrefs = [a.get("href", "") for a in nav_btns]
check("1.html" in hrefs,                          "Previous button links to 1.html")
check("3.html" in hrefs,                          "Next button links to 3.html")


# ==============================================================================
# Step 7: chapter/3.html — Last chapter uses "Finish Book" button
# ==============================================================================
print("\n[7] Checking chapter/3.html (last chapter) ...")
soup = parse("chapter/3.html")

finish_btn = soup.find("button", class_="completion-button")
check(bool(finish_btn),                            "'Finish Book' button exists on last chapter")
if finish_btn:
    check("Finish" in finish_btn.get_text(),       "Button text contains 'Finish'")
    parent_a = finish_btn.find_parent("a")
    check(bool(parent_a),                          "'Finish Book' button is inside <a> tag")
    if parent_a:
        check(parent_a.get("href","").endswith("index.html"), "'Finish Book' links to index.html")


# ==============================================================================
# Step 8: CSS fallback checks
# ==============================================================================
print("\n[8] Checking CSS fallbacks in global.css ...")
css_text = (OUTPUT_DIR / "css/global.css").read_text(encoding="utf-8")

check("background-color: #1a1713" in css_text,    "Static background fallback present")
check("color: #dbdbdb"             in css_text,    "Static text color fallback present")
check("font-family: -apple-system" in css_text,    "System font stack fallback present")
check("display: block"             in css_text,    "display:block flexbox fallback present")
check(".no-js .js-only"            in css_text,    ".no-js .js-only rule present")
check("var(--main-background"      in css_text,    "CSS variable usage present")


# ==============================================================================
# Step 9: reader.js safety checks
# ==============================================================================
print("\n[9] Checking reader.js safety ...")
js_text = (OUTPUT_DIR / "js/reader.js").read_text(encoding="utf-8")

check("try {" in js_text,              "try-catch safety blocks present")
check("localStorage" in js_text,       "localStorage usage present")
check("SecurityError" in js_text or "catch" in js_text, "Error handling for localStorage")
check("'use strict'" in js_text,       "'use strict' directive present")


# ==============================================================================
# Summary
# ==============================================================================
print(f"\n{'='*55}")
if failures:
    print(f"\n{FAIL}  {len(failures)} test(s) FAILED:\n")
    for f in failures:
        print(f"    - {f}")
    print()
    sys.exit(1)
else:
    print(f"\n{PASS}  All tests passed!\n")
