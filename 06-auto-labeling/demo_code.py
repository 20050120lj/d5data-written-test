#!/usr/bin/env python3
"""Auto-labelling demo: label an e-commerce after-sales dialogue corpus with a foundation model.

Usage
-----
    # 1) rule baseline over the whole corpus (no API key needed)
    python demo_code.py --provider offline --limit 0 --out output/offline_all

    # 2) real LLM over a stratified sample
    export LLM_BASE_URL=https://api.deepseek.com/v1
    export LLM_API_KEY=sk-...
    export LLM_MODEL=deepseek-chat
    python demo_code.py --provider deepseek --sample data/sample_120.jsonl --out output/llm_120

    # 3) local Ollama
    python demo_code.py --provider ollama --sample data/sample_120.jsonl --out output/llm_120

Outputs (per run)
-----------------
    <out>.jsonl   one record per dialogue: source fields + predicted labels + provenance
    <out>.csv     flat table for spreadsheet review (utf-8-sig)

Design notes
------------
* **Fail closed.** A malformed model answer is retried; after the retry budget it
  is written as an explicit error record, never coerced into a guess. Coercing
  would hide the very failure mode we are auditing.
* **Cache by content hash.** Re-running after a crash does not re-bill the API.
* **Concurrency with a hard cap.** 8 workers by default; the corpus is small and
  the endpoint is the bottleneck, so backoff matters more than parallelism.
* **Provenance on every row.** provider, model id, temperature, prompt version
  and a UTC timestamp travel with the label, because a label without provenance
  cannot be audited later.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from labelers import build_provider
from taxonomy import (
    AGENT_ACTION,
    ISSUE_TYPES,
    QUALITY_FLAGS,
    USER_EMOTION,
    LABEL_SCHEMA,
)

PROMPT_VERSION = "v1.2-2026-11-11"
DEFAULT_DATA = Path(__file__).resolve().parent.parent.parent / (
    "QingshanAI--ecom-after-sale-synthetic/snapshots/master/data.jsonl"
)


# --------------------------------------------------------------------------- #
# I/O
# --------------------------------------------------------------------------- #

def read_jsonl(path: Path, limit: int | None = None) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            rec.setdefault("_row", line_no)
            rec["_id"] = hashlib.sha1(
                f"{rec.get('user','')}\x1f{rec.get('bot','')}".encode()
            ).hexdigest()[:12]
            rows.append(rec)
            if limit and len(rows) >= limit:
                break
    return rows


def load_cache(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    cache = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # partial last line after a crash
            if rec.get("label") and not rec.get("error"):
                cache[rec["_id"]] = rec["label"]
    return cache


def write_csv(records: list[dict], path: Path) -> None:
    cols = [
        "id", "row", "scene", "tone", "user",
        "issue_type", "user_emotion", "agent_action", "quality_flags", "confidence",
        "provider", "model", "error",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig so the file opens cleanly in Excel with Chinese text
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for rec in records:
            flat = dict(rec)
            lbl = rec.get("label") or {}
            flat.update({k: lbl.get(k, "") for k in LABEL_SCHEMA["properties"]})
            flat["quality_flags"] = "|".join(lbl.get("quality_flags") or [])
            writer.writerow(flat)


# --------------------------------------------------------------------------- #
# Main loop
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="LLM auto-labelling demo")
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--sample", type=Path, default=None,
                    help="optional pre-sampled jsonl; overrides --data/--limit")
    ap.add_argument("--provider", default="offline",
                    choices=["offline", "openai", "deepseek", "qwen", "compatible", "ollama"])
    ap.add_argument("--model", default=None, help="override model id recorded in provenance")
    ap.add_argument("--limit", type=int, default=0, help="0 = all rows")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default="output/run")
    ap.add_argument("--cache", type=Path, default=Path("output/.label_cache.jsonl"))
    ap.add_argument("--resume", action="store_true", help="reuse cached labels by content hash")
    args = ap.parse_args(argv)

    src = args.sample or args.data
    if not src.exists():
        print(f"[fatal] data not found: {src}", file=sys.stderr)
        return 2

    rows = read_jsonl(src, args.limit or None)
    print(f"[info] loaded {len(rows)} dialogues from {src}")

    label_fn = build_provider(args.provider)
    model_id = args.model or os.getenv("LLM_MODEL") or ("rule-baseline" if args.provider == "offline" else "unknown")

    cache: dict[str, dict] = {}
    if args.resume:
        cache = load_cache(args.cache)
        print(f"[info] resume: {len(cache)} cached labels")

    todo = [r for r in rows if r["_id"] not in cache]
    done: dict[str, dict] = dict(cache)
    errors: dict[str, str] = {}
    started = time.time()

    if todo:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = {pool.submit(label_fn, r): r for r in todo}
            for i, fut in enumerate(as_completed(futures), 1):
                rec = futures[fut]
                try:
                    done[rec["_id"]] = fut.result()
                except Exception as exc:  # noqa: BLE001
                    errors[rec["_id"]] = str(exc)[:300]
                if i % 20 == 0 or i == len(todo):
                    rate = i / max(time.time() - started, 1e-6)
                    print(f"[info] {i}/{len(todo)}  {rate:.1f} req/s  errors={len(errors)}")
    else:
        print("[info] nothing to do (all cached)")

    # Append-only cache so a crash never loses paid calls.
    args.cache.parent.mkdir(parents=True, exist_ok=True)
    with args.cache.open("a", encoding="utf-8") as fh:
        for rec in rows:
            lbl = done.get(rec["_id"])
            if lbl and rec["_id"] not in cache:
                fh.write(json.dumps({"_id": rec["_id"], "label": lbl}, ensure_ascii=False) + "\n")

    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out_records = []
    for rec in rows:
        item = {
            "id": rec["_id"],
            "row": rec.get("_row"),
            "scene": rec.get("scene", ""),
            "tone": rec.get("tone", ""),
            "user": rec.get("user", ""),
            "bot": rec.get("bot", ""),
            "label": done.get(rec["_id"]),
            "error": errors.get(rec["_id"]),
            "provider": args.provider,
            "model": model_id,
            "prompt_version": PROMPT_VERSION,
            "labelled_at": stamp,
        }
        out_records.append(item)

    out_base = Path(args.out)
    out_base.parent.mkdir(parents=True, exist_ok=True)
    with out_base.with_suffix(".jsonl").open("w", encoding="utf-8") as fh:
        for item in out_records:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
    write_csv(out_records, out_base.with_suffix(".csv"))

    ok = sum(1 for r in out_records if r["label"])
    low = sum(1 for r in out_records if r["label"] and r["label"]["confidence"] < 0.6)
    print(f"[done] {ok}/{len(out_records)} labelled, {len(errors)} errors, "
          f"{low} low-confidence (<0.6)")
    print(f"[done] wrote {out_base.with_suffix('.jsonl')} and {out_base.with_suffix('.csv')}")
    print(f"[done] label space: {len(ISSUE_TYPES)} issue / {len(USER_EMOTION)} emotion / "
          f"{len(AGENT_ACTION)} action / {len(QUALITY_FLAGS)} flags")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
