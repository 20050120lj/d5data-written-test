# MIT Admissions Blogs Crawler — Playwright & DrissionPage

Two independent crawlers that scrape <https://mitadmissions.org/blogs/> and write the
same nine-column CSV, so the two browser-automation stacks can be compared on identical
input:

```
Title | Author | Comment Count | Time | Article Content | Images In Article
      | Image URLs | URL
```

The first six columns are exactly the ones required by the task, in the required order.
`Image URLs` and `URL` are appended afterwards as traceability helpers (the task asks for
the *number* of images, the URL list makes the number auditable and lets you re-download
assets later).

| File | Purpose |
| --- | --- |
| `crawler_playwright.py` | Playwright (sync API) implementation |
| `crawler_drissionpage.py` | DrissionPage (`ChromiumPage`) implementation, written from scratch |
| `blogs_playwright.csv` | 20 real rows produced by the Playwright crawler |
| `blogs_drissionpage.csv` | 20 real rows produced by the DrissionPage crawler |
| `run_playwright.log` / `run_drissionpage.log` | Full run logs (URLs, per-article timings, warnings) |
| `comparison.md` | Chinese write-up comparing the two stacks (numbers, differences, pros/cons) |
| `requirements.txt` | Runtime dependencies |
| `debug_list.html` | The list page HTML captured during selector discovery |

## 1. Target site structure (verified against the live DOM, not guessed)

The blogs index is a server-rendered WordPress archive. **There is no infinite scroll and
no JSON API involved** — plain pagination links:

- 16 article cards per page, wrapped in `li.tease-feed-item`
- next page link: `a.pagination__text-link--next` (currently 492 pages, ~7.8k posts)
- article permalink pattern: `https://mitadmissions.org/blogs/entry/<slug>/`

Card markup (list page):

```html
<li class="tease-feed-item">
  <article class="tease ...">
    <a class="post-tease__h__link" href=".../blogs/entry/chasing-butterflies/">
      <span class="post-tease__title">Chasing Butterflies</span>
      <span class="post-tease__subtitle">on community and friendship</span>
    </a>
    <ul class="post-tease__meta-list">
      <li class="post-tease__meta-item post-tease__meta-item--author">by <a href="...">Allison E. '27</a></li>
      <li class="post-tease__meta-item tease__meta-item--date">October 28, 2026</li>
      <li class="... tease__meta-item--comments"><a href="...#disqus_thread"></a></li>
    </ul>
  </article>
</li>
```

Article detail page:

```html
<h1 class="page-topper__title">Chasing Butterflies
  <a href="/blogs/author/allisone/"><span class="page-topper__title__name">by Allison E. '27</span></a>
</h1>
<p class="page-topper__sub">on community and friendship</p>
<time class="page-topper__date" datetime="2026-10-28T00:00:00-04:00">October 28, 2026</time>
<div class="article__body"> ...real post HTML... </div>
<div class="article__comments"><div id="disqus_thread"></div></div>
```

## 2. How each field is extracted

| CSV column | Where it comes from | Playwright | DrissionPage |
| --- | --- | --- | --- |
| `Title` | `h1.page-topper__title`, with the inner `span.page-topper__title__name` ("by …") removed | `page.evaluate()`: clone the `h1`, delete `.page-topper__title__name`, read `innerText` | `h1.text` minus the text of the child `.page-topper__title__name` element |
| `Author` | the anchor inside the `h1` that points to `/blogs/author/<name>/`, leading `by ` stripped; falls back to `h2.article__author-h` ("About X") | `document.querySelector('h1.page-topper__title a').innerText` | `h1.ele('css:h1.page-topper__title a').text`, regex strips `^(by|about)\s+` |
| `Comment Count` | Disqus thread count, `#disqus_thread a` (detail) / `.tease__comment-text a` (list) | `page.wait_for_function` until the text contains a digit, then `([\d,]+)` → int | polling `ele()` every 0.5 s for up to 6 s, then same regex |
| `Time` | `time.page-topper__date` → `datetime` attribute (ISO 8601), normalised to `YYYY-MM-DD` | `el.getAttribute('datetime') \|\| el.innerText` | `el.attr('datetime') or el.text` |
| `Article Content` | `div.article__body` `innerText`, whitespace collapsed (`\s+` → single space, `\xa0`/`\u200b` removed), truncated at 8 000 chars with a trailing `...` | `body.innerText` | `body.text` (⚠ includes `<img alt>` text — see `comparison.md` §4) |
| `Images In Article` | count of `<img>` inside `div.article__body`, each resolved from `src` → `data-flickity-lazyload-src` → `data-src`, deduplicated by absolute URL | `page.eval_on_selector_all` over `div.article__body img` | `body.eles('tag:img')` loop over `attr()` values |
| `Image URLs` | same collection joined with ` \| ` | as above | as above |
| `URL` | canonical article URL, `#` fragment removed | `a.post-tease__h__link.href` | `link.attr('href')` |

Notes that matter for correctness:

- **Lazy images.** Some posts embed a Flickity carousel where `<img>` has **no `src`**, only
  `data-flickity-lazyload-src`. Reading `src` alone silently under-counts; both crawlers
  check the lazy attributes too.
- **List pages only carry the first 16 posts**, so `--limit` above 16 forces pagination.
  Both crawlers follow `a.pagination__text-link--next` until `--limit` unique URLs are queued.
- **Duplicate URLs** are filtered with a `seen` set before any detail page is opened.
- **Title without the subtitle.** Both engines store only `span.post-tease__title`, not the
  `span.post-tease__subtitle` tagline, so the two CSVs line up field by field.

## 3. Running

```bash
cd 03-crawler
pip install -r requirements.txt

# Playwright — reuses the system Google Chrome, no 150 MB browser download needed
python crawler_playwright.py --limit 20 --out blogs_playwright.csv --log run_playwright.log

# DrissionPage — attaches to the local Chrome binary
python crawler_drissionpage.py --limit 20 --out blogs_drissionpage.csv --log run_drissionpage.log
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `--limit N` | 20 | number of unique articles to scrape (the site has ~7.8k) |
| `--out` | `blogs_playwright.csv` / `blogs_drissionpage.csv` | output CSV path |
| `--log` | `run_playwright.log` / `run_drissionpage.log` | log file path |
| `--headless` | `1` | `0` opens a visible browser window |
| `--slow` | `1.4` | base delay in seconds; the actual gap is `slow + random(0, 0.6)` |

Both scripts are idempotent: a re-run overwrites the CSV and the log, so results are always
a consistent snapshot of one execution. Exit code is 0 on success.

Browser resolution: Playwright first tries `channel="chrome"` (the installed
`C:\Program Files\Google\Chrome\Application\chrome.exe`) and falls back to Playwright's
bundled Chromium (`python -m playwright install chromium` if that binary is missing).
DrissionPage probes Chrome, Chrome x86 and Edge paths in that order.

## 4. Output data: what is real and what is 0

Measured on this machine, 2026-11-11:

| Metric | Playwright | DrissionPage |
| --- | --- | --- |
| Rows | 20 | 20 |
| Post date range | 2026-10-17 → 2026-11-10 | same |
| Distinct authors | 15 | 15 |
| Total images | 219 (max 59 in one post, 16/20 posts have ≥1 image) | 219 (identical) |
| Body length | avg 4754, max 8004 (6 rows truncated) | avg 4907, max 8004 (6 rows truncated) |
| Comment counts | 20/20 non-zero, **99 total** | identical row by row |
| Wall clock | 179.7 s | 150.5 s / 104.0 s (network dependent) |

### How `Comment Count` is obtained

The count is **not in the server HTML**. The page only ships an empty
`<div id="disqus_thread"></div>`; the number is injected by
`https://mitadmissions.disqus.com/embed.js` / `count.js` after load.

Two approaches were tried, and only one of them is reliable:

| Approach | Result |
| --- | --- |
| Wait for `#disqus_thread a` to contain a digit in headless Chrome | **Unreliable.** Waits 15 s and still returns an empty anchor, *even when the proxy works*. Disqus' embed does not render in headless/incognito contexts. |
| Query the official counter endpoint `mitadmissions.disqus.com/count-data.js?1=<identifier>` | **Reliable.** Returns the authoritative number in one request, no JS involved. |

The identifier matters: it is **not** the article URL but the value of `this.page.identifier`
inside the page (`129942 https://mitadmissions.org/?p=129942`), captured with a regex while the
detail page is open.

Both crawlers use the counter endpoint; each resolved **20/20** rows and the two CSVs agree
row by row (99 comments total, max 21 on the `dream` comic post). Requires outbound access to
`disqus.com`, which is why the script takes `--proxy`:

```bash
python crawler_playwright.py  --limit 20 --proxy http://127.0.0.1:7897
python crawler_drissionpage.py --limit 20 --proxy http://127.0.0.1:7897
```

Two implementation notes learned the hard way:

- The proxy drops roughly 1 in 15 TLS handshakes, so each lookup retries up to 3 times.
- `requests.Session.trust_env = False` is required: otherwise the host-injected `HTTP(S)_PROXY`
  is merged with the explicit proxy and produces intermittent `SSLEOFError`.

Without a proxy the column falls back to `0` and the log says so explicitly — it never
fabricates a number.

### Content correctness spot-checks

- `dream` (comic post) has 34 visible characters and 5 images — the "article" really is a
  comic strip, so short text is correct, not a failed extraction.
- `something-to-believe-in` has 59 images (a photo gallery) — the highest count in the sample.
- 6 rows hit the 8 000-character cap and end with `...`; increasing
  `CONTENT_MAX_CHARS` (top of either script) is a one-line change.

## 5. Anti-crawler / operational observations

No CAPTCHA, no login, no Cloudflare JS challenge was served for these pages (HTTP 200,
server-rendered HTML). Observed friction and how it is handled:

1. **Third-party script hangs the load event.** The Disqus embed never resolves on this
   network, so a naive "wait for `load`" blocks every navigation for 30–56 s.
   - Playwright: `goto(..., wait_until="domcontentloaded")` + explicit `wait_for_selector("div.article__body")`.
   - DrissionPage: `page.set.load_mode.none()` + `page.wait.ele_displayed(...)`.
   This alone was the difference between ~9 s and ~3 s per article.
2. **DrissionPage `NoneElement`.** `ele(loc, timeout=0)` returns a falsy object, not `None`;
   touching `.text` on it raises `ElementNotFoundError`. Both the crawler and the shared
   `safe_ele()` helper normalise this to a real `None`.
3. **Transient tab disconnect.** One DrissionPage run died with `PageDisconnectedError`
   mid-pagination. The crawler now (a) retries a failed `get()` once, (b) stops pagination
   gracefully instead of crashing, and (c) keeps a partial row with list-page metadata if a
   detail page fails twice, so the CSV always documents what happened.
4. **Politeness.** Real Chrome UA, `1440x900` viewport, `en-US` locale, 30 s page timeout,
   1 attempt + 1 retry per article, and `1.4–2.0 s` randomized sleep between articles.
   20 articles cost the site ~22 requests in ~1.5–3.5 minutes.

## 6. Limitations

- **Dynamic comments only.** `Comment Count` depends on `disqus.com`; behind a blocked
  network it is necessarily `0` (see §4).
- **`Article Content` is plain text.** Formatting, links and inline captions are flattened.
  HTML is available in `div.article__body` if you need it — store `body.innerHTML()`.
- **8 000-character cap.** Six of the 20 sampled posts are longer.
- **DrissionPage includes `<img alt>` text in `body.text`**, so carousel control alts like
  "An arrow pointing right" leak into the body (avg +153 chars vs Playwright, max +1103).
  Documented rather than silently patched; see `comparison.md` §4 for the one-line fix.
- **Only the newest N posts.** There is no crawl of the archive and no state between runs;
  re-running re-fetches everything.
- **Single-threaded, one page at a time.** Fine for 20 posts, slow for 7 800.
- **Brittle to redesigns.** Selectors are tied to the current theme classes
  (`post-tease__*`, `page-topper__*`, `article__body`). A theme change breaks them — no
  fallback heuristics are implemented on purpose, so failures are loud instead of silent.
- **No robots.txt/TOS review in code.** Only a friendly rate and a single host are touched.

## 7. If this had to be productionised

Current shape: "open the site, walk N pages, write a CSV". A real pipeline would need:

1. **Incremental crawl** — store the newest seen post ID / `datetime` in a state file (or DB)
   and stop paginating once every card on a page is already known. WordPress exposes
   `lastBuildDate` in `/blogs/feed/`, a cheap way to skip a full crawl when nothing changed.
2. **Deduplication** — a stable key (`/blogs/entry/<slug>/`, or the WP post ID embedded in
   `data-disqus-identifier="129684 …"`) as the primary key, with upsert instead of append.
   Content hashes let you detect edited posts and only re-download changed bodies.
3. **Resumable crawling** — a work queue (SQLite / Redis) of `pending / done / failed` URLs
   plus a checkpoint file, so a crash or a `Ctrl-C` continues where it stopped instead of
   restarting. Never lose the 900 pages already fetched.
4. **Concurrency control** — 3–5 browser contexts (Playwright) behind an `asyncio.Semaphore`,
   or a worker pool with a shared token bucket for rate limiting (e.g. 1 req/s host-wide),
   plus exponential backoff + jitter on 429/5xx and a circuit breaker per host.
5. **Layer the fetcher** — the article body is server-rendered, so 95 % of the traffic could
   use plain `requests`/`SessionPage` and only fall back to a browser when
   `div.article__body` is missing. That removes the browser cost for the bulk path.
6. **Schema and storage** — land raw HTML in object storage (bronze), parsed rows in
   Postgres/Parquet (silver), and only then build the CSV/report (gold). CSV is an export
   format, not a database.
7. **Observability** — structured JSON logs, per-run metrics (rows, empty fields, retries,
   HTTP status histogram), alert when the non-empty rate of a required field drops.
8. **Contract tests** — a `pytest` suite that runs against 2–3 saved HTML fixtures (like
   `debug_list.html`) and asserts that each selector still yields a non-empty value, so a
   site redesign fails CI instead of producing silently empty columns.
9. **Config over code** — selectors and field mappings in a YAML/JSON profile, one crawler
   engine selected by CLI flag, so adding a site is configuration, not a new script.
10. **Compliance** — honour `robots.txt` and the site's terms, keep contact info in the UA,
    respect `Retry-After`, and cap concurrency per host.
