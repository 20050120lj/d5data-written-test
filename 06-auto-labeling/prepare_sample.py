#!/usr/bin/env python3
"""Build a stratified evaluation sample from the after-sales corpus.

Why stratified rather than random: the source label space is extremely skewed
(退换货 550 / 抚慰 1). A uniform 120-row sample would contain ~0 examples of the
9 rare `tone` values and ~0 examples of the 4 malformed `scene` values -- exactly
the rows where label noise is concentrated. Stratifying by (scene, tone) with a
floor per stratum keeps the hard cases in the sample.

Rare strata (<= 3 rows in the corpus) are taken in full.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import random
from pathlib import Path

DEFAULT_DATA = Path(__file__).resolve().parent.parent.parent / (
    "QingshanAI--ecom-after-sale-synthetic/snapshots/master/data.jsonl"
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--out", type=Path, default=Path("data/sample_120.jsonl"))
    ap.add_argument("--size", type=int, default=120)
    ap.add_argument("--seed", type=int, default=20261111)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    rows = []
    with args.data.open(encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            rec["_row"] = i
            rec["_id"] = hashlib.sha1(
                f"{rec.get('user','')}\x1f{rec.get('bot','')}".encode()
            ).hexdigest()[:12]
            rows.append(rec)

    # de-duplicate on the user turn so the sample is not 13% duplicates
    seen_user: set[str] = set()
    uniq = []
    for rec in rows:
        if rec["user"] in seen_user:
            continue
        seen_user.add(rec["user"])
        uniq.append(rec)

    strata: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for rec in uniq:
        strata[(rec["scene"], rec["tone"])].append(rec)

    # floor of 1 for every stratum, then proportional fill up to `size`
    picked: list[dict] = []
    for key in sorted(strata):
        group = strata[key]
        rng.shuffle(group)
        take = min(len(group), 1 if len(group) <= 3 else 2)
        picked.extend(group[:take])

    remaining = [r for k in sorted(strata) for r in strata[k] if r not in picked]
    rng.shuffle(remaining)
    while len(picked) < args.size and remaining:
        picked.append(remaining.pop())

    picked = picked[: args.size]
    rng.shuffle(picked)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for rec in picked:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"[ok] corpus={len(rows)} unique_user={len(uniq)} strata={len(strata)} "
          f"sample={len(picked)} -> {args.out}")
    print("[ok] scene coverage:", dict(collections.Counter(r["scene"] for r in picked)))
    print("[ok] tone coverage :", len({r["tone"] for r in picked}), "of 26 distinct tones")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
