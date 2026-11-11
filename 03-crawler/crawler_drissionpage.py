"""Crawl https://mitadmissions.org/blogs/ with DrissionPage (ChromiumPage).

Independent implementation - no shared code with crawler_playwright.py.

Outputs a CSV with the required headers:
    Title | Author | Comment Count | Time | Article Content | Images In Article
plus two extra helper columns (Image URLs, URL) appended AFTER the required six.

Usage:
    python crawler_drissionpage.py --limit 20 --out blogs_drissionpage.csv
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
from urllib.parse import urljoin

import requests
from DrissionPage import ChromiumOptions, ChromiumPage
from DrissionPage.errors import ElementNotFoundError, PageDisconnectedError

BASE_URL = "https://mitadmissions.org/blogs/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]

HEADERS = [
    "Title",
    "Author",
    "Comment Count",
    "Time",
    "Article Content",
    "Images In Article",
    "Image URLs",
    "URL",
]
CONTENT_MAX_CHARS = 8000

log = logging.getLogger("dp-crawler")


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


def squeeze(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.replace("\xa0", " ").replace("\u200b", "")).strip()


def to_int(text: str | None) -> int:
    if not text:
        return 0
    hit = re.search(r"([\d,]+)", text)
    if not hit:
        return 0
    try:
        return int(hit.group(1).replace(",", ""))
    except ValueError:
        return 0


def pick_chrome_path() -> str | None:
    for path in CHROME_CANDIDATES:
        if Path(path).exists():
            return path
    return None


def disqus_alive() -> bool:
    """Comment counts are injected by disqus.com - probe before waiting on it."""
    try:
        requests.head("https://disqus.com/", timeout=4)
        return True
    except Exception as exc:  # noqa: BLE001
        log.info("disqus.com unreachable (%s: %s) -> comment counts stay 0",
                 type(exc).__name__, str(exc)[:120])
        return False


def safe_ele(parent, locator):
    """DP returns a falsy NoneElement when nothing matches - normalise to None.

    Depending on version/config ele(timeout=0) may also raise ElementNotFoundError.
    """
    try:
        el = parent.ele(locator, timeout=0)
    except Exception:  # noqa: BLE001
        return None
    return el if el else None


def build_page(headless: bool) -> ChromiumPage:
    opts = ChromiumOptions()
    chrome = pick_chrome_path()
    if chrome:
        opts.set_browser_path(chrome)
        log.info("using browser binary: %s", chrome)
    opts.headless(headless)
    opts.set_argument("--no-sandbox")
    opts.set_argument("--disable-gpu")
    opts.set_argument(f"--user-agent={USER_AGENT}")
    opts.set_argument("--lang=en-US")
    opts.set_timeouts(base=30, page_load=30, script=30)
    opts.auto_port()
    page = ChromiumPage(opts)
    # Don't block on third-party resources (Disqus embed never resolves here).
    try:
        page.set.load_mode.eager()
    except Exception:  # noqa: BLE001
        pass
    return page


# --------------------------------------------------------------------------- #
# list page
# --------------------------------------------------------------------------- #
def read_list_page(page: ChromiumPage) -> list[dict]:
    cards = page.eles("css:li.tease-feed-item")
    out: list[dict] = []
    for card in cards:
        link = safe_ele(card, "css:a.post-tease__h__link")
        if link is None:
            continue
        url = (link.attr("href") or "").split("#")[0]
        if not url:
            continue

        title_ele = safe_ele(card, "css:.post-tease__title")
        sub_ele = safe_ele(card, "css:.post-tease__subtitle")
        author_ele = safe_ele(card, "css:.post-tease__meta-item--author a")
        date_ele = safe_ele(card, "css:.tease__meta-item--date")
        comment_ele = safe_ele(card, "css:.tease__comment-text a")

        title = squeeze(title_ele.text if title_ele else "")
        sub = squeeze(sub_ele.text if sub_ele else "")

        out.append(
            {
                "url": url,
                "title": title,
                "subtitle": sub,
                "author": squeeze(author_ele.text if author_ele else ""),
                "date": squeeze(date_ele.text if date_ele else ""),
                "comments": to_int(comment_ele.text if comment_ele else ""),
            }
        )
    return out


def walk_list(page: ChromiumPage, limit: int) -> list[dict]:
    collected: list[dict] = []
    seen: set[str] = set()
    url: str | None = BASE_URL
    page_no = 1

    while url and len(collected) < limit:
        log.info("list page %d: %s", page_no, url)
        page.get(url)
        page.wait.doc_loaded(timeout=45)
        try:
            page.wait.ele_displayed("css:li.tease-feed-item", timeout=20)
        except Exception:  # noqa: BLE001
            log.warning("  no article cards found on %s", url)

        rows = read_list_page(page)
        log.info("  -> %d cards on page", len(rows))
        for row in rows:
            if row["url"] in seen:
                continue
            seen.add(row["url"])
            collected.append(row)
            if len(collected) >= limit:
                break

        nxt = page.ele("css:a.pagination__text-link--next", timeout=0)
        href = nxt.attr("href") if nxt else None
        url = urljoin(BASE_URL, href) if href else None
        page_no += 1

    log.info("%d unique article URLs queued", len(collected))
    return collected[:limit]


# --------------------------------------------------------------------------- #
# detail page
# --------------------------------------------------------------------------- #
def read_detail(page: ChromiumPage, url: str, wait_disqus: bool) -> dict:
    page.get(url, timeout=30)
    page.wait.doc_loaded(timeout=30)

    body = page.ele("css:div.article__body", timeout=20)
    if body is None or not body:
        raise ElementNotFoundError("div.article__body not found")

    # ---- title (drop the trailing "by <author>" span) --------------------- #
    title = ""
    h1 = safe_ele(page, "css:h1.page-topper__title")
    if h1 is not None:
        inner_author = safe_ele(h1, "css:.page-topper__title__name")
        title = squeeze(h1.text)
        if inner_author is not None:
            title = squeeze(title.replace(squeeze(inner_author.text), ""))

    # ---- author ---------------------------------------------------------- #
    author = ""
    author_ele = safe_ele(page, "css:h1.page-topper__title a")
    if author_ele is not None:
        author = squeeze(author_ele.text)
    if not author:
        bio = safe_ele(page, "css:h2.article__author-h")  # "About X"
        if bio is not None:
            author = squeeze(bio.text)
    author = re.sub(r"^(by|about)\s+", "", author, flags=re.I).strip()

    # ---- time ------------------------------------------------------------ #
    when = ""
    time_ele = safe_ele(page, "css:time.page-topper__date")
    if time_ele is not None:
        when = squeeze(time_ele.attr("datetime") or time_ele.text)
    if "T" in when:
        when = when.split("T")[0]

    # ---- body text ------------------------------------------------------- #
    content = squeeze(body.text)
    if len(content) > CONTENT_MAX_CHARS:
        content = content[:CONTENT_MAX_CHARS] + " ..."

    # ---- images (src / flickity lazy / data-src) -------------------------- #
    image_urls: list[str] = []
    for img in body.eles("tag:img"):
        candidate = (
            img.attr("src")
            or img.attr("data-flickity-lazyload-src")
            or img.attr("data-src")
            or ""
        )
        candidate = candidate.strip()
        if not candidate:
            continue
        absolute = urljoin(url, candidate)
        if absolute not in image_urls:
            image_urls.append(absolute)

    # ---- comment count (Disqus, client side) ----------------------------- #
    comment_text = ""
    node = safe_ele(page, "css:#disqus_thread a") or safe_ele(page, "css:.tease__comment-text a")
    if node is not None:
        comment_text = node.text or ""
    if wait_disqus and not re.search(r"\d", comment_text):
        deadline = time.time() + 6
        while time.time() < deadline:
            node = safe_ele(page, "css:#disqus_thread a")
            if node is not None and re.search(r"\d", node.text or ""):
                comment_text = node.text
                break
            time.sleep(0.5)

    return {
        "Title": title,
        "Author": author,
        "Comment Count": to_int(comment_text),
        "Time": when,
        "Article Content": content,
        "Images In Article": len(image_urls),
        "Image URLs": " | ".join(image_urls),
        "URL": url,
    }


def read_detail_retry(page: ChromiumPage, url: str, wait_disqus: bool, retries: int = 1) -> dict | None:
    for attempt in range(retries + 1):
        try:
            return read_detail(page, url, wait_disqus)
        except Exception as exc:  # noqa: BLE001 - any failure triggers one retry
            log.warning("  attempt %d/%d failed for %s: %s: %s",
                        attempt + 1, retries + 1, url, type(exc).__name__, str(exc)[:160])
            if attempt < retries:
                time.sleep(2.0)
    return None


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="DrissionPage crawler for MIT Admissions blogs")
    ap.add_argument("--limit", type=int, default=20, help="number of articles to scrape (default 20)")
    ap.add_argument("--out", default="blogs_drissionpage.csv", help="output CSV path")
    ap.add_argument("--log", default="run_drissionpage.log", help="log file path")
    ap.add_argument("--headless", default="1", help="1 = headless (default), 0 = show browser")
    ap.add_argument("--slow", type=float, default=1.4, help="base sleep seconds between articles")
    args = ap.parse_args()

    setup_logging(Path(args.log))
    log.info("start: limit=%d out=%s", args.limit, args.out)

    wait_disqus = disqus_alive()
    if not wait_disqus:
        log.info("skip Disqus wait, comment counts will be 0")

    rows: list[dict] = []
    started = time.time()
    page = None

    try:
        page = build_page(headless=args.headless != "0")
        queue = walk_list(page, args.limit)

        for idx, item in enumerate(queue, 1):
            log.info("[%d/%d] %s", idx, len(queue), item["url"])
            data = read_detail_retry(page, item["url"], wait_disqus)
            if data is None:
                data = {
                    "Title": item["title"],
                    "Author": item["author"],
                    "Comment Count": item["comments"],
                    "Time": item["date"],
                    "Article Content": "",
                    "Images In Article": 0,
                    "Image URLs": "",
                    "URL": item["url"],
                }
                log.warning("  row kept without content: %s", item["url"])
            else:
                data["Title"] = data["Title"] or item["title"]
                data["Author"] = data["Author"] or item["author"]
                data["Time"] = data["Time"] or item["date"]
                if not data["Comment Count"]:
                    data["Comment Count"] = item["comments"]

            rows.append(data)
            log.info("  ok title=%r author=%r time=%s images=%d content_chars=%d",
                     data["Title"][:60], data["Author"], data["Time"],
                     data["Images In Article"], len(data["Article Content"]))
            time.sleep(args.slow + random.uniform(0, 0.6))
    finally:
        if page is not None:
            try:
                page.quit()
            except Exception:  # noqa: BLE001
                pass

    out_path = Path(args.out)
    with out_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)

    log.info("wrote %d rows to %s (%.1fs)", len(rows), out_path.resolve(), time.time() - started)
    log.info("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
