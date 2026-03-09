#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "requests>=2.28",
#   "beautifulsoup4>=4.12",
#   "lxml>=4.9",
#   "ebooklib>=0.18",
# ]
# ///
"""
acoup_reader.py — Fetch acoup.blog articles and export them as EPUB for iPhone/Apple Books.

Usage:
    # Single article
    uv run acoup_reader.py https://acoup.blog/2026/01/30/...

    # Follow the whole series automatically (detects "next post" links)
    uv run acoup_reader.py --series https://acoup.blog/2026/01/30/...

    # Override output filename
    uv run acoup_reader.py --output lba_collapse.epub https://acoup.blog/2026/01/30/...
"""

import argparse
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from ebooklib import epub

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Sec-CH-UA": '"Not A(Brand";v="99", "Google Chrome";v="121", "Chromium";v="121"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"macOS"',
    "DNT": "1",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def fetch(url: str) -> BeautifulSoup:
    print(f"  Fetching: {url}")
    for attempt in range(5):
        resp = SESSION.get(url, timeout=30)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 2 ** (attempt + 1)))
            print(f"  Rate limited — waiting {wait}s before retry…")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    resp.raise_for_status()  # raise after all retries exhausted


# ---------------------------------------------------------------------------
# Article extraction
# ---------------------------------------------------------------------------

# Tags / classes that are definitely not article content
_NOISE_SELECTORS = [
    "script", "style", "noscript",
    ".sharedaddy", ".jp-relatedposts", ".wpcnt",
    ".entry-footer", ".post-navigation", ".site-footer",
    ".widget", ".sidebar", "nav", "header.site-header",
    ".comment-respond", "#comments", ".comments-area",
    ".addtoany_share_save_container",
    "[class*='share']", "[class*='social']",
    "[class*='subscribe']", "[class*='newsletter']",
    "[class*='popup']", "[class*='banner']",
    "figure.wp-block-image > figcaption",   # keep figcaption below, just testing
]


def _clean_soup(article_el: BeautifulSoup) -> BeautifulSoup:
    """Remove noise elements in-place and return the element."""
    for sel in _NOISE_SELECTORS:
        for tag in article_el.select(sel):
            tag.decompose()
    # Remove empty paragraphs
    for p in article_el.find_all("p"):
        if not p.get_text(strip=True):
            p.decompose()
    return article_el


def extract_article(soup: BeautifulSoup, url: str) -> dict:
    """
    Returns a dict with keys:
        title (str), date (str), html_content (str), next_url (str|None)
    """
    # --- Title ---
    title = ""
    title_el = soup.find("h1", class_=re.compile(r"entry-title|post-title"))
    if not title_el:
        title_el = soup.find("h1")
    if title_el:
        title = title_el.get_text(strip=True)

    # --- Date ---
    date = ""
    date_el = soup.find("time", class_=re.compile(r"entry-date|published"))
    if not date_el:
        date_el = soup.find("time")
    if date_el:
        date = date_el.get("datetime", date_el.get_text(strip=True))[:10]

    # --- Article body ---
    content_el = (
        soup.find("div", class_=re.compile(r"entry-content|post-content"))
        or soup.find("article")
        or soup.find("main")
    )
    if not content_el:
        raise ValueError(f"Could not find article content at {url}")

    _clean_soup(content_el)

    # Make all internal links absolute
    for a in content_el.find_all("a", href=True):
        a["href"] = urljoin(url, a["href"])
    for img in content_el.find_all("img", src=True):
        img["src"] = urljoin(url, img["src"])

    html_content = str(content_el)

    # --- Next post link (series navigation) ---
    next_url = _find_next_url(soup, url)

    return {
        "title": title,
        "date": date,
        "url": url,
        "html_content": html_content,
        "next_url": next_url,
    }


def _find_next_url(soup: BeautifulSoup, current_url: str) -> str | None:
    """
    Detect the "next post" link.  acoup.blog uses standard WP navigation:
      <a rel="next" ...> or links with class nav-next / next-post.
    Also look inside the article text for explicit "Part II", "Part 2", "next part" links.
    """
    base = "acoup.blog"

    # WP post-navigation
    for a in soup.find_all("a", rel=lambda r: r and "next" in r):
        href = a.get("href", "")
        if base in href:
            return href

    for sel in [".nav-next a", ".next-post a", "[class*='next'] a"]:
        el = soup.select_one(sel)
        if el and base in el.get("href", ""):
            return el["href"]

    # Inline series links: "Part II", "Part 2", "next part", "Continue reading"
    content_el = soup.find("div", class_=re.compile(r"entry-content|post-content"))
    if content_el:
        pattern = re.compile(
            r"\b(part\s+(ii|iii|iv|v|vi|vii|viii|2|3|4|5|6|7|8)|next\s+part|continue\s+reading)\b",
            re.IGNORECASE,
        )
        for a in content_el.find_all("a", href=True):
            text = a.get_text(strip=True)
            if pattern.search(text) and base in urljoin(current_url, a["href"]):
                return urljoin(current_url, a["href"])

    return None


# ---------------------------------------------------------------------------
# Series crawler
# ---------------------------------------------------------------------------

def collect_series(start_url: str, max_parts: int = 20) -> list[dict]:
    """Fetch start_url and follow next-post links, returning list of article dicts."""
    articles = []
    seen = set()
    url = start_url

    while url and len(articles) < max_parts:
        if url in seen:
            break
        seen.add(url)

        try:
            soup = fetch(url)
            article = extract_article(soup, url)
        except Exception as exc:
            print(f"  Warning: could not fetch {url}: {exc}", file=sys.stderr)
            break

        articles.append(article)
        print(f"  Found: {article['title']!r} ({article['date']})")

        url = article["next_url"]
        if url:
            time.sleep(0.8)  # be polite

    return articles


# ---------------------------------------------------------------------------
# EPUB builder
# ---------------------------------------------------------------------------

# Minimal CSS that looks great in Apple Books on iPhone
BOOK_CSS = """
body {
    font-family: Georgia, 'Times New Roman', serif;
    font-size: 1em;
    line-height: 1.7;
    margin: 0;
    padding: 0;
    color: #1a1a1a;
}
h1, h2, h3 {
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    font-weight: bold;
    margin-top: 2em;
    margin-bottom: 0.5em;
    line-height: 1.3;
}
h1 { font-size: 1.6em; }
h2 { font-size: 1.3em; }
h3 { font-size: 1.1em; }
p {
    margin: 0 0 1em 0;
    text-align: left;
    orphans: 2;
    widows: 2;
}
blockquote {
    border-left: 3px solid #999;
    margin: 1.2em 0;
    padding: 0.2em 1em;
    font-style: italic;
    color: #444;
}
a {
    color: #2a5db0;
    text-decoration: none;
}
hr {
    border: none;
    border-top: 1px solid #ccc;
    margin: 2em 0;
}
.footnote-marker {
    font-size: 0.75em;
    vertical-align: super;
}
ol, ul {
    margin: 0.5em 0 1em 1.5em;
}
li {
    margin-bottom: 0.4em;
}
img {
    max-width: 100%;
    height: auto;
}
.chapter-meta {
    font-size: 0.85em;
    color: #666;
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    margin-bottom: 2em;
    border-bottom: 1px solid #eee;
    padding-bottom: 0.8em;
}
"""


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def build_epub(articles: list[dict], output_path: Path) -> None:
    book = epub.EpubBook()

    # Metadata — use first article's info
    first = articles[0]
    book_title = first["title"] if len(articles) == 1 else _infer_series_title(articles)
    book.set_title(book_title)
    book.set_language("en")
    book.add_author("Bret Devereaux")
    book.add_metadata("DC", "source", first["url"])
    if first["date"]:
        book.add_metadata("DC", "date", first["date"])

    # Stylesheet
    css_item = epub.EpubItem(
        uid="style",
        file_name="style/book.css",
        media_type="text/css",
        content=BOOK_CSS,
    )
    book.add_item(css_item)

    chapters = []
    for i, art in enumerate(articles, 1):
        slug = _slugify(art["title"]) or f"chapter-{i}"
        file_name = f"chap_{i:02d}_{slug}.xhtml"

        meta_html = f'<div class="chapter-meta">'
        if art["date"]:
            meta_html += f"Published {art['date']} · "
        meta_html += f'<a href="{art["url"]}">Original post</a></div>'

        chapter_html = (
            f"<html><head><title>{art['title']}</title>"
            f"<link rel=\"stylesheet\" href=\"../style/book.css\" type=\"text/css\"/>"
            f"</head><body>"
            f"<h1>{art['title']}</h1>"
            f"{meta_html}"
            f"{art['html_content']}"
            f"</body></html>"
        )

        chap = epub.EpubHtml(
            title=art["title"],
            file_name=file_name,
            lang="en",
            content=chapter_html,
        )
        chap.add_item(css_item)
        book.add_item(chap)
        chapters.append(chap)

    # Table of contents + spine
    book.toc = tuple(epub.Link(c.file_name, c.title, c.file_name) for c in chapters)
    book.spine = ["nav"] + chapters
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    epub.write_epub(str(output_path), book)
    print(f"\nSaved: {output_path}  ({output_path.stat().st_size // 1024} KB)")
    print("AirDrop this file to your iPhone — it will open in Apple Books.")


def _infer_series_title(articles: list[dict]) -> str:
    """Try to extract a common series name from the article titles."""
    titles = [a["title"] for a in articles]
    # Look for "Collections: <Series Name>" pattern
    m = re.match(r"Collections?:\s*(.+?)(?:,|\s+Part|\s+–|\s+-|$)", titles[0], re.IGNORECASE)
    if m:
        return f"ACOUP – {m.group(1).strip()}"
    return titles[0]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Fetch acoup.blog articles and export as EPUB for iPhone/Apple Books."
    )
    parser.add_argument("url", help="URL of the first (or only) article")
    parser.add_argument(
        "--series",
        action="store_true",
        help="Follow 'next post' links and bundle the whole series into one EPUB",
    )
    parser.add_argument(
        "--output", "-o",
        help="Output filename (default: derived from article title)",
    )
    parser.add_argument(
        "--max-parts",
        type=int,
        default=20,
        metavar="N",
        help="Maximum number of parts to collect when --series is used (default: 20)",
    )
    args = parser.parse_args()

    print(f"\nacoup → EPUB reader")
    print(f"{'─' * 40}")

    if args.series:
        print(f"Mode: series (following next-post links, max {args.max_parts} parts)")
        articles = collect_series(args.url, max_parts=args.max_parts)
    else:
        print("Mode: single article")
        soup = fetch(args.url)
        article = extract_article(soup, args.url)
        print(f"  Found: {article['title']!r} ({article['date']})")
        articles = [article]

    if not articles:
        print("No articles fetched. Check the URL and your internet connection.")
        sys.exit(1)

    # Determine output path
    if args.output:
        out = Path(args.output)
        if out.suffix.lower() != ".epub":
            out = out.with_suffix(".epub")
    else:
        series_title = _infer_series_title(articles)
        out = Path(_slugify(series_title) + ".epub")

    print(f"\nBuilding EPUB ({len(articles)} chapter(s))…")
    build_epub(articles, out)


if __name__ == "__main__":
    main()
