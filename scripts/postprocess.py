#!/usr/bin/env python3
"""Quarto post-render step.

Two jobs, both about being findable:

1. Quarto renders `aliases:` entries as a JS-only redirect page. Search engines
   handle those poorly and most LLM crawlers do not run JS at all, so the link
   equity of the old fastpages URLs is stranded. We add a `<meta http-equiv=
   "refresh">`, a `rel="canonical"` and a plain <a> fallback.

2. Generate `llms.txt` (see llmstxt.org) so that AI crawlers get a clean,
   link-per-post index of the site instead of having to scrape the listing page.
"""

import html
import json
import os
import re
import sys
from pathlib import Path

SITE_URL = "https://blog.dmytro.ai"
SITE_TITLE = "Dmytro's Blog"
SITE_DESCRIPTION = (
    "Computer vision, image matching, deep learning and academic life "
    "— notes by Dmytro Mishkin, PhD."
)

OUT_DIR = Path(os.environ.get("QUARTO_PROJECT_OUTPUT_DIR", "docs"))

REDIRECT_RE = re.compile(r"var redirects = (\{.*?\});", re.S)


def site_path(path: Path) -> str:
    """docs/posts/foo.html -> /posts/foo.html"""
    return "/" + path.relative_to(OUT_DIR).as_posix()


def absolute(path: Path) -> str:
    return SITE_URL + site_path(path)


def fix_alias_pages() -> int:
    """Give Quarto's JS-only alias pages a meta refresh and a canonical link."""
    fixed = 0
    for page in OUT_DIR.rglob("*.html"):
        source = page.read_text(encoding="utf-8")
        if "var redirects" not in source or 'http-equiv="refresh"' in source:
            continue

        match = REDIRECT_RE.search(source)
        if not match:
            continue
        try:
            redirects = json.loads(match.group(1))
        except json.JSONDecodeError:
            print(f"[postprocess] could not parse redirects in {page}", file=sys.stderr)
            continue

        relative_target = redirects.get("")
        if not relative_target:
            continue

        # Resolve the relative target against the alias page's own directory so
        # that we can state the canonical URL in absolute form.
        resolved = (page.parent / relative_target).resolve()
        try:
            relative_to_root = resolved.relative_to(OUT_DIR.resolve())
        except ValueError:
            print(f"[postprocess] {relative_target} escapes {OUT_DIR}", file=sys.stderr)
            continue
        target_url = f"{SITE_URL}/{relative_to_root.as_posix()}"

        escaped = html.escape(target_url, quote=True)
        head_extra = (
            f'  <link rel="canonical" href="{escaped}">\n'
            f'  <meta http-equiv="refresh" content="0; url={escaped}">\n'
        )
        source = source.replace("  <title>Redirect</title>", head_extra + "  <title>Redirect</title>", 1)
        source = source.replace(
            "<body>",
            f'<body>\n  <p>This page has moved to <a href="{escaped}">{escaped}</a>.</p>',
            1,
        )
        page.write_text(source, encoding="utf-8")
        fixed += 1
    return fixed


def canonical_url(page: Path) -> str:
    """Preferred URL for a page. `index.html` collapses to its directory URL so
    that `/` and `/index.html` do not compete as two crawlable duplicates."""
    path = site_path(page)
    if path.endswith("/index.html"):
        path = path[: -len("index.html")]
    return SITE_URL + path


def add_canonical_links() -> int:
    """Quarto does not emit `rel="canonical"`, so add one to every page."""
    added = 0
    for page in OUT_DIR.rglob("*.html"):
        source = page.read_text(encoding="utf-8")
        if 'rel="canonical"' in source or "</head>" not in source:
            continue
        link = f'<link rel="canonical" href="{html.escape(canonical_url(page), quote=True)}">\n'
        page.write_text(source.replace("</head>", link + "</head>", 1), encoding="utf-8")
        added += 1
    return added


def normalize_sitemap() -> None:
    """Keep the sitemap agreeing with the canonical links above."""
    sitemap = OUT_DIR / "sitemap.xml"
    if not sitemap.exists():
        return
    source = sitemap.read_text(encoding="utf-8")
    updated = re.sub(r"(<loc>[^<]*?)/index\.html(</loc>)", r"\1/\2", source)
    if updated != source:
        sitemap.write_text(updated, encoding="utf-8")


def page_metadata(page: Path) -> tuple[str, str]:
    source = page.read_text(encoding="utf-8")

    title = ""
    match = re.search(r"<title>(.*?)</title>", source, re.S)
    if match:
        title = html.unescape(match.group(1)).strip()
        # Quarto appends " – Dmytro’s Blog" to every page title.
        title = re.split(r"\s+–\s+", title)[0].strip()

    description = ""
    match = re.search(r'<meta name="description" content="(.*?)"', source, re.S)
    if match:
        description = html.unescape(match.group(1)).strip()

    return title, description


def write_llms_txt() -> None:
    listings = json.loads((OUT_DIR / "listings.json").read_text(encoding="utf-8"))
    hrefs = [href for listing in listings for href in listing.get("items", [])]

    lines = [
        f"# {SITE_TITLE}",
        "",
        f"> {SITE_DESCRIPTION}",
        "",
        "Written by Dmytro Mishkin, PhD — computer vision researcher and consultant,",
        "maintainer of the Kornia library. Full CV, publications and talks: https://dmytro.ai",
        "",
        "## Posts",
        "",
    ]

    for href in hrefs:
        page = OUT_DIR / href.lstrip("/")
        if not page.exists():
            print(f"[postprocess] listed but missing: {page}", file=sys.stderr)
            continue
        title, description = page_metadata(page)
        entry = f"- [{title}]({SITE_URL}{href})"
        if description:
            entry += f": {description}"
        lines.append(entry)

    about = OUT_DIR / "about.html"
    if about.exists():
        title, description = page_metadata(about)
        lines += ["", "## Optional", "", f"- [{title}]({absolute(about)}): {description}"]

    (OUT_DIR / "llms.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    if not OUT_DIR.is_dir():
        sys.exit(f"[postprocess] output directory {OUT_DIR} not found")
    fixed = fix_alias_pages()
    canonical = add_canonical_links()
    normalize_sitemap()
    write_llms_txt()
    print(
        f"[postprocess] alias pages fixed: {fixed}; canonical links added: {canonical}; "
        f"wrote {OUT_DIR / 'llms.txt'}"
    )


if __name__ == "__main__":
    main()
