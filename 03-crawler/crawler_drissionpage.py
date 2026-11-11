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
import json
import logging
import os
import random
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, quote

import requests
from DrissionPage import ChromiumOptions, ChromiumPage
from DrissionPage.errors import ElementNotFoundError

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
    # Block third-party scripts at DNS level. Without this the Disqus embed keeps
    # the load event pending for ~70s per page, which is what made the first run
    # look "hung". Mapping them to 127.0.0.1 fails fast instead of timing out.
    opts.set_argument(
        "--host-resolver-rules="
        "MAP disqus.com 127.0.0.1, MAP *.disqus.com 127.0.0.1, "
        "MAP *.google-analytics.com 127.0.0.1, MAP *.googletagmanager.com 127.0.0.1, "
        "MAP *.doubleclick.net 127.0.0.1, MAP *.facebook.net 127.0.0.1"
    )
    opts.set_timeouts(base=10, page_load=15, script=10)
    opts.auto_port()
    page = ChromiumPage(opts)
    # Don't block on third-party resources (the Disqus embed never resolves here).
    # load_mode=none returns as soon as the request is committed; we then wait for
    # the specific element we need instead of for the full load event.
    try:
        page.set.load_mode.none()
    except Exception as exc:  # noqa: BLE001
        log.warning("could not switch load_mode to 'none': %s", exc)
    return page


def load(page: ChromiumPage, url: str, selector: str, timeout: float = 20) -> None:
    """get() + wait for `selector`, with one retry on a broken/failed load."""
    last: Exception | None = None
    for attempt in (1, 2):
        try:
            page.get(url, timeout=30)
            page.wait.ele_displayed(selector, timeout=timeout)
            return
        except Exception as exc:  # noqa: BLE001
            last = exc
            log.warning("  load attempt %d for %s failed: %s", attempt, url, type(exc).__name__)
    raise last if last else RuntimeError(f"cannot load {url}")


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
        try:
            load(page, url, "css:li.tease-feed-item", timeout=25)
        except Exception as exc:  # noqa: BLE001
            log.error("  list page unusable (%s: %s), stopping pagination",
                      type(exc).__name__, str(exc)[:120])
            break

        try:
            rows = read_list_page(page)
        except Exception as exc:  # noqa: BLE001 - tab crash / disconnect
            log.error("  reading cards failed (%s: %s), stopping pagination",
                      type(exc).__name__, str(exc)[:120])
            break
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
    load(page, url, "css:div.article__body", timeout=25)

    body = page.ele("css:div.article__body", timeout=10)
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

    # Disqus keys its counter API on this string, not on the page URL.
    ident = ""
    try:
        mi = re.search(r"this\.page\.identifier\s*=\s*'([^']*)'", page.html or "")
        if mi:
            ident = mi.group(1)
    except Exception:  # noqa: BLE001 - identifier is optional
        pass

    return {
        "Title": title,
        "Author": author,
        "Comment Count": to_int(comment_text),
        "Time": when,
        "Article Content": content,
        "Images In Article": len(image_urls),
        "Image URLs": " | ".join(image_urls),
        "URL": url,
        "_identifier": ident,
    }


DISQUS_COUNT_URL = "https://mitadmissions.disqus.com/count-data.js"


def resolve_proxy(cli_value: str | None) -> str | None:
    if cli_value:
        return cli_value
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        value = os.environ.get(key)
        if value:
            return value
    return None


def fetch_comment_counts(rows: list[dict], proxy: str | None) -> int:
    """Fill Comment Count from the Disqus counter endpoint.

    The in-page counter (`#disqus_thread a`) is injected by embed.js and never
    resolves in headless mode even through a working proxy, so the number is
    fetched over HTTP against the same thread identifier. One request per
    article, failures leave the row at its existing value.
    """
    sess = requests.Session()
    sess.trust_env = False  # do not merge the host-injected proxy with ours
    if proxy:
        sess.proxies = {"http": proxy, "https": proxy}
    sess.headers.update({"User-Agent": USER_AGENT, "Referer": BASE_URL})

    resolved = 0
    for row in rows:
        ident = row.get("_identifier") or ""
        if not ident:
            continue
        # The proxy drops a request now and then (measured ~1 in 15); retry
        # rather than silently leaving a wrong 0 in a data column.
        for attempt in range(3):
            try:
                resp = sess.get(f"{DISQUS_COUNT_URL}?1={quote(ident, safe='')}", timeout=15)
                resp.raise_for_status()
                m = re.search(r'"counts":\s*(\[.*?\])', resp.text, re.S)
                if not m:
                    break
                arr = json.loads(m.group(1))
                if arr:
                    row["Comment Count"] = int(arr[0].get("comments", 0))
                resolved += 1
                break
            except Exception as exc:  # noqa: BLE001
                if attempt == 2:
                    log.warning("  comment lookup failed for %s: %s: %s",
                                row.get("URL", "?"), type(exc).__name__, str(exc)[:100])
                else:
                    time.sleep(1.0)
    log.info("comment counts resolved via Disqus API: %d/%d", resolved, len(rows))
    return resolved


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
    ap.add_argument("--proxy", default=None,
                    help="HTTP proxy for the Disqus counter API (defaults to $HTTPS_PROXY)")
    args = ap.parse_args()

    setup_logging(Path(args.log))
    log.info("start: limit=%d out=%s", args.limit, args.out)

    proxy = resolve_proxy(args.proxy)
    if proxy:
        log.info("using proxy for Disqus: %s", proxy)
    wait_disqus = disqus_alive()
    if not wait_disqus:
        log.info("in-page Disqus counter unavailable, will use the counter API instead")

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

    fetch_comment_counts(rows, proxy)

    out_path = Path(args.out)
    with out_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADERS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    log.info("wrote %d rows to %s (%.1fs)", len(rows), out_path.resolve(), time.time() - started)
    log.info("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
