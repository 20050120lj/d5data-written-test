"""Crawl https://mitadmissions.org/blogs/ with Playwright (sync API).

Outputs a CSV with the required headers:
    Title | Author | Comment Count | Time | Article Content | Images In Article
plus two extra helper columns (Image URLs, URL) appended AFTER the required six.

Usage:
    python crawler_playwright.py --limit 20 --out blogs_playwright.csv
"""

from __future__ import annotations

import argparse
import csv
import logging
import random
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

BASE_URL = "https://mitadmissions.org/blogs/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

REQUIRED_HEADERS = [
    "Title",
    "Author",
    "Comment Count",
    "Time",
    "Article Content",
    "Images In Article",
]
EXTRA_HEADERS = ["Image URLs", "URL"]
HEADERS = REQUIRED_HEADERS + EXTRA_HEADERS

CONTENT_MAX_CHARS = 8000

log = logging.getLogger("playwright-crawler")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def setup_logging(logfile: Path) -> None:
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")

    fh = logging.FileHandler(logfile, mode="w", encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(sh)


def clean_text(text: str | None) -> str:
    """Collapse every kind of whitespace (incl. nbsp) into single spaces."""
    if not text:
        return ""
    text = text.replace("\xa0", " ").replace("\u200b", "")
    return re.sub(r"\s+", " ", text).strip()


def parse_comment_count(text: str | None) -> int:
    """Disqus renders things like '12 Comments' / '0 Comments' / '12'."""
    if not text:
        return 0
    m = re.search(r"([\d,]+)", text)
    if not m:
        return 0
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return 0


def disqus_reachable(timeout: float = 4.0) -> bool:
    """Comment counts come from disqus.com (client side). Probe once.

    If the host is unreachable from this machine we skip the per-article wait
    and record 0 instead of sleeping several seconds on every page.
    """
    try:
        requests.head("https://disqus.com/", timeout=timeout)
        return True
    except Exception as exc:  # noqa: BLE001 - any network error means "no"
        log.info("disqus.com unreachable (%s: %s) -> comment counts stay 0",
                 type(exc).__name__, str(exc)[:120])
        return False


# --------------------------------------------------------------------------- #
# list page
# --------------------------------------------------------------------------- #
LIST_ITEMS_JS = """
els => els.map(el => {
  const link = el.querySelector('a.post-tease__h__link');
  const title = el.querySelector('.post-tease__title');
  const sub = el.querySelector('.post-tease__subtitle');
  const author = el.querySelector('.post-tease__meta-item--author a');
  const date = el.querySelector('.tease__meta-item--date');
  const comments = el.querySelector('.tease__comment-text a');
  return {
    url: link ? link.href : null,
    title: title ? title.innerText : null,
    subtitle: sub ? sub.innerText : null,
    author: author ? author.innerText : null,
    date: date ? date.innerText : null,
    comments: comments ? comments.innerText : null,
  };
})
"""


def collect_article_links(page: Any, limit: int) -> list[dict[str, Any]]:
    """Walk the paginated list pages until `limit` unique articles are found."""
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    next_url: str | None = BASE_URL
    page_no = 1

    while next_url and len(found) < limit:
        log.info("list page %d: %s", page_no, next_url)
        page.goto(next_url, wait_until="domcontentloaded", timeout=45_000)
        page.wait_for_selector("li.tease-feed-item", timeout=30_000)

        items = page.eval_on_selector_all("li.tease-feed-item", LIST_ITEMS_JS)
        log.info("  -> %d cards on page", len(items))

        for it in items:
            url = (it.get("url") or "").split("#")[0]
            if not url or url in seen:
                continue
            seen.add(url)
            title = clean_text(it.get("title"))
            subtitle = clean_text(it.get("subtitle"))
            it["url"] = url
            it["title"] = f"{title} {subtitle}".strip() if subtitle else title
            it["author"] = clean_text(it.get("author"))
            it["date"] = clean_text(it.get("date"))
            it["comments"] = parse_comment_count(it.get("comments"))
            found.append(it)
            if len(found) >= limit:
                break

        next_el = page.query_selector("a.pagination__text-link--next, link[rel='next']")
        next_url = next_el.get_attribute("href") if next_el else None
        if next_url:
            next_url = urljoin(BASE_URL, next_url)
        page_no += 1

    log.info("collected %d unique article URLs", len(found))
    return found[:limit]


# --------------------------------------------------------------------------- #
# detail page
# --------------------------------------------------------------------------- #
DETAIL_JS = r"""
() => {
  const txt = el => el ? el.innerText : '';
  const h1 = document.querySelector('h1.page-topper__title');
  let title = '';
  if (h1) {
    const clone = h1.cloneNode(true);
    clone.querySelectorAll('.page-topper__title__name').forEach(n => n.remove());
    title = clone.innerText;
  }
  const authorEl = document.querySelector('h1.page-topper__title a') ||
                   document.querySelector('.article__author-h');
  let author = authorEl ? authorEl.innerText : '';
  author = author.replace(/^by\s+/i, '').replace(/^About\s+/i, '').trim();

  const timeEl = document.querySelector('time.page-topper__date');
  const time = timeEl ? (timeEl.getAttribute('datetime') || timeEl.innerText) : '';

  const body = document.querySelector('div.article__body');
  const content = body ? body.innerText : '';

  const urls = [];
  if (body) {
    body.querySelectorAll('img').forEach(img => {
      const u = img.currentSrc || img.getAttribute('src') ||
                img.getAttribute('data-flickity-lazyload-src') ||
                img.getAttribute('data-src') || '';
      if (u) urls.push(u);
    });
  }

  const commentEl = document.querySelector('#disqus_thread a') ||
                    document.querySelector('.tease__comment-text a');
  const comments = commentEl ? commentEl.innerText : '';

  return {title, author, time, content, urls, comments};
}
"""


def scrape_detail(page: Any, url: str, wait_disqus: bool) -> dict[str, Any]:
    page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    page.wait_for_selector("div.article__body", timeout=30_000)

    if wait_disqus:
        # count.js fills in "<n> Comments"; give it a short chance, never fail.
        try:
            page.wait_for_function(
                r"""() => {
                     const a = document.querySelector('#disqus_thread a') ||
                               document.querySelector('.tease__comment-text a');
                     return !!a && /\d/.test(a.innerText || '');
                   }""",
                timeout=6_000,
            )
        except PlaywrightTimeout:
            pass

    raw = page.evaluate(DETAIL_JS)

    content = clean_text(raw.get("content"))
    if len(content) > CONTENT_MAX_CHARS:
        content = content[:CONTENT_MAX_CHARS] + " ..."

    image_urls: list[str] = []
    for u in raw.get("urls") or []:
        u = urljoin(url, u.strip())
        if u and u not in image_urls:
            image_urls.append(u)

    time_value = clean_text(raw.get("time"))
    if "T" in time_value:  # normalise ISO datetime to date only
        time_value = time_value.split("T")[0]

    return {
        "Title": clean_text(raw.get("title")),
        "Author": clean_text(raw.get("author")),
        "Comment Count": parse_comment_count(raw.get("comments")),
        "Time": time_value,
        "Article Content": content,
        "Images In Article": len(image_urls),
        "Image URLs": " | ".join(image_urls),
        "URL": url,
    }


def scrape_with_retry(page: Any, url: str, wait_disqus: bool, retries: int = 1) -> dict[str, Any] | None:
    for attempt in range(retries + 1):
        try:
            return scrape_detail(page, url, wait_disqus)
        except Exception as exc:  # noqa: BLE001
            log.warning("  attempt %d/%d failed for %s: %s: %s",
                        attempt + 1, retries + 1, url, type(exc).__name__, str(exc)[:160])
            if attempt < retries:
                time.sleep(2.0)
    return None


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="Playwright crawler for MIT Admissions blogs")
    ap.add_argument("--limit", type=int, default=20, help="number of articles to scrape (default 20)")
    ap.add_argument("--out", default="blogs_playwright.csv", help="output CSV path")
    ap.add_argument("--log", default="run_playwright.log", help="log file path")
    ap.add_argument("--headless", default="1", help="1 = headless (default), 0 = show browser")
    ap.add_argument("--slow", type=float, default=1.4, help="base sleep seconds between articles")
    args = ap.parse_args()

    setup_logging(Path(args.log))
    log.info("start: limit=%d out=%s", args.limit, args.out)

    reachable = disqus_reachable()
    if not reachable:
        log.info("comment counts will be written as 0 (Disqus is rendered client-side only)")

    rows: list[dict[str, Any]] = []
    started = time.time()

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=args.headless != "0")
            log.info("launched system Chrome (channel=chrome) %s", browser.version)
        except Exception:
            browser = p.chromium.launch(headless=args.headless != "0")
            log.info("launched bundled Chromium %s", browser.version)

        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1440, "height": 900},
            locale="en-US",
        )
        page = context.new_page()

        try:
            links = collect_article_links(page, args.limit)

            for idx, item in enumerate(links, 1):
                url = item["url"]
                log.info("[%d/%d] %s", idx, len(links), url)
                data = scrape_with_retry(page, url, reachable)
                if data is None:
                    # keep the row so the CSV still documents the failure
                    data = {
                        "Title": item.get("title", ""),
                        "Author": item.get("author", ""),
                        "Comment Count": item.get("comments", 0),
                        "Time": item.get("date", ""),
                        "Article Content": "",
                        "Images In Article": 0,
                        "Image URLs": "",
                        "URL": url,
                    }
                    log.warning("  giving up on %s, row kept with empty content", url)
                else:
                    # list page metadata is a sane fallback for missing fields
                    data["Title"] = data["Title"] or item.get("title", "")
                    data["Author"] = data["Author"] or item.get("author", "")
                    data["Time"] = data["Time"] or item.get("date", "")
                    if not data["Comment Count"]:
                        data["Comment Count"] = item.get("comments", 0)

                rows.append(data)
                log.info("  ok title=%r author=%r time=%s images=%d content_chars=%d",
                         data["Title"][:60], data["Author"], data["Time"],
                         data["Images In Article"], len(data["Article Content"]))
                time.sleep(args.slow + random.uniform(0, 0.6))
        finally:
            context.close()
            browser.close()

    out_path = Path(args.out)
    with out_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)

    elapsed = time.time() - started
    log.info("wrote %d rows to %s (%.1fs)", len(rows), out_path.resolve(), elapsed)
    log.info("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
