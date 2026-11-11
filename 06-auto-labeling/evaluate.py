#!/usr/bin/env python3
"""Evaluate auto-labels against (a) the noisy source labels and (b) the rule baseline.

There is no clean gold set here -- the corpus ships only `scene`/`tone`, which are
themselves the object under audit. So this script measures *agreement*, not
accuracy, and reports three things that are actually decision-relevant:

1. agreement at a comparable granularity (label families), not string equality;
2. how much of the disagreement is explained by the source label being unable to
   express the distinction (granularity loss) vs. by the model being wrong;
3. whether confidence is calibrated, because that is what decides how much of the
   corpus can be auto-adopted vs. routed to human review.

Outputs: metrics.json, confusion_*.csv, disagreements.md, low_confidence.csv
"""

from __future__ import annotations

import collections
import csv
import json
from pathlib import Path

from taxonomy import (
    PRED_TO_FAMILY,
    SOURCE_SCENE_TO_FAMILY,
    SOURCE_TONE_TO_EMOTION,
)

OUT = Path("output")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def load(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def kappa(pairs: list[tuple[str, str]]) -> float:
    """Cohen's kappa for two raters with nominal categories."""
    n = len(pairs)
    if n == 0:
        return 0.0
    po = sum(1 for a, b in pairs if a == b) / n
    ca = collections.Counter(a for a, _ in pairs)
    cb = collections.Counter(b for _, b in pairs)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return 0.0 if pe == 1 else (po - pe) / (1 - pe)


def confusion(pairs: list[tuple[str, str]], labels_a: list[str], labels_b: list[str], path: Path) -> None:
    table = collections.Counter(pairs)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["source \\ pred"] + labels_b + ["row_total"])
        for a in labels_a:
            row = [table.get((a, b), 0) for b in labels_b]
            if sum(row):
                w.writerow([a] + row + [sum(row)])
        w.writerow(["col_total"] + [sum(table.get((a, b), 0) for a in labels_a) for b in labels_b] + [len(pairs)])


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def main() -> int:
    llm = load(OUT / "llm_120.jsonl")
    rule = {r["id"]: r for r in load(OUT / "offline_all.jsonl")}
    llm = [r for r in llm if r["label"]]
    print(f"[info] llm rows={len(llm)}  rule rows={len(rule)}")

    metrics: dict = {"n_llm": len(llm), "n_corpus": len(rule)}

    # ---------- 1. agreement with source `scene`, at family granularity ----------
    fam_pairs, exact_pairs, granularity_loss = [], [], 0
    for r in llm:
        src = SOURCE_SCENE_TO_FAMILY.get(r["scene"], "other")
        pred = PRED_TO_FAMILY[r["label"]["issue_type"]]
        fam_pairs.append((src, pred))
        exact_pairs.append((r["scene"], r["label"]["issue_type"]))
        if src == pred:
            continue
        # If the source label is one of the coarse buckets that physically cannot
        # express the prediction, count it as granularity loss rather than error.
        if r["scene"] in {"退换货", "退回", "质量问题", "质量", "差评", "补偿方案", "维权投诉"}:
            if src == "return" and pred in {"exchange", "return_refund"}:
                granularity_loss += 1

    n = len(fam_pairs)
    fam_acc = sum(1 for a, b in fam_pairs if a == b) / n
    metrics["issue_family_agreement"] = round(fam_acc, 4)
    metrics["issue_family_kappa"] = round(kappa(fam_pairs), 4)
    metrics["issue_family_confusion"] = {
        f"{a}->{b}": c for (a, b), c in collections.Counter(fam_pairs).most_common() if a != b
    }

    # ---------- 2. agreement with source `tone` -> emotion, excluding TWISTED ----------
    tone_pairs, twisted = [], 0
    for r in llm:
        mapped = SOURCE_TONE_TO_EMOTION.get(r["tone"])
        if mapped == "TWISTED" or mapped is None:
            twisted += 1
            continue
        tone_pairs.append((mapped, r["label"]["user_emotion"]))
    metrics["tone_twisted_rows"] = twisted
    metrics["tone_twisted_rate"] = round(twisted / len(llm), 4)
    if tone_pairs:
        # NOTE: this is a *dimension-mismatch probe*, not an accuracy metric.
        # `tone` describes how the AGENT answered; `user_emotion` describes the USER.
        # A near-zero kappa here is the expected result and is itself the finding:
        # the source `tone` column carries no information about user affect.
        metrics["tone_vs_emotion_agreement"] = round(
            sum(1 for a, b in tone_pairs if a == b) / len(tone_pairs), 4
        )
        metrics["tone_vs_emotion_kappa"] = round(kappa(tone_pairs), 4)

    # ---------- 3. LLM vs rule baseline on the same 120 rows ----------
    cmp_issue = [(r["label"]["issue_type"], rule[r["id"]]["label"]["issue_type"]) for r in llm if r["id"] in rule]
    cmp_fam = [
        (PRED_TO_FAMILY[r["label"]["issue_type"]], PRED_TO_FAMILY[rule[r["id"]]["label"]["issue_type"]])
        for r in llm if r["id"] in rule
    ]
    cmp_emo = [(r["label"]["user_emotion"], rule[r["id"]]["label"]["user_emotion"]) for r in llm if r["id"] in rule]
    metrics["llm_vs_rule_issue_exact"] = round(sum(1 for a, b in cmp_issue if a == b) / len(cmp_issue), 4)
    metrics["llm_vs_rule_issue_family"] = round(sum(1 for a, b in cmp_fam if a == b) / len(cmp_fam), 4)
    metrics["llm_vs_rule_issue_kappa"] = round(kappa(cmp_issue), 4)
    metrics["llm_vs_rule_emotion"] = round(sum(1 for a, b in cmp_emo if a == b) / len(cmp_emo), 4)

    # ---------- 4. confidence calibration ----------
    buckets = {"0.0-0.5": [], "0.5-0.7": [], "0.7-0.9": [], "0.9-1.0": []}
    for r in llm:
        c = r["label"]["confidence"]
        src = SOURCE_SCENE_TO_FAMILY.get(r["scene"], "other")
        ok = src == PRED_TO_FAMILY[r["label"]["issue_type"]]
        key = "0.0-0.5" if c < 0.5 else "0.5-0.7" if c < 0.7 else "0.7-0.9" if c < 0.9 else "0.9-1.0"
        buckets[key].append(ok)
    metrics["calibration"] = {
        k: {"n": len(v), "agreement": round(sum(v) / len(v), 3) if v else None}
        for k, v in buckets.items()
    }

    # ---------- 4b. adjudication of every disagreement ----------
    # Agreement is not accuracy. Every family-level disagreement is read and
    # adjudicated by hand (data/arbitration.json) so the report can separate
    # "the model was wrong" from "the source label answered a different question".
    arb_path = Path("data/arbitration.json")
    if arb_path.exists():
        cases = json.loads(arb_path.read_text(encoding="utf-8"))["cases"]
        verdicts = collections.Counter(c["verdict"] for c in cases)
        total = len(llm)
        metrics["adjudication"] = {
            "n_disagreements": len(cases),
            "model_correct": verdicts.get("model_correct", 0),
            "dimension_diff": verdicts.get("dimension_diff", 0),
            "source_correct": verdicts.get("source_correct", 0),
            "model_error_rate_on_sample": round(verdicts.get("source_correct", 0) / total, 4),
            "effective_accuracy_after_adjudication": round(
                (sum(1 for a, b in fam_pairs if a == b) + verdicts.get("model_correct", 0)) / total, 4
            ),
            "source_label_error_rate_in_disagreements": round(
                verdicts.get("model_correct", 0) / max(len(cases), 1), 4
            ),
        }

    # ---------- 4c. human-in-the-loop workflow simulation ----------
    # If labels with confidence >= T are auto-adopted and the rest go to review,
    # what coverage / quality trade-off do we get? This is the number that decides
    # whether the pipeline is deployable.
    wf = {}
    for t in (0.5, 0.6, 0.7, 0.8, 0.9, 0.95):
        auto = [r for r in llm if r["label"]["confidence"] >= t]
        if not auto:
            wf[f"{t:.2f}"] = {"coverage": 0.0, "agreement_on_auto": None}
            continue
        ok = sum(
            1 for r in auto
            if SOURCE_SCENE_TO_FAMILY.get(r["scene"], "other") == PRED_TO_FAMILY[r["label"]["issue_type"]]
        )
        wf[f"{t:.2f}"] = {
            "coverage": round(len(auto) / len(llm), 3),
            "agreement_on_auto": round(ok / len(auto), 3),
            "n_review": len(llm) - len(auto),
        }
    metrics["hitl_workflow"] = wf

    # ---------- 5. label-noise detection on the full corpus (rule baseline) ----------
    # Rows where the source scene cannot be reconciled with the predicted family at
    # all, and the rule baseline is highly confident, are the cheapest audit queue.
    noise = []
    for r in rule.values():
        if not r["label"]:
            continue
        src = SOURCE_SCENE_TO_FAMILY.get(r["scene"], "other")
        pred = PRED_TO_FAMILY[r["label"]["issue_type"]]
        if src != pred and r["label"]["confidence"] >= 0.7 and src != "return":
            noise.append((src, pred))
    metrics["rule_flag_rate"] = round(len(noise) / len(rule), 4)
    metrics["rule_flag_top"] = {f"{a}->{b}": c for (a, b), c in collections.Counter(noise).most_common(6)}

    # ---------- write artefacts ----------
    conf_path = OUT / "confusion_issue_family.csv"
    confusion(
        fam_pairs,
        ["return", "quality", "logistics", "compensation", "complaint", "pre_sale", "other"],
        ["return", "quality", "logistics", "compensation", "complaint", "pre_sale", "other"],
        conf_path,
    )

    with (OUT / "metrics.json").open("w", encoding="utf-8") as fh:
        json.dump(metrics, fh, ensure_ascii=False, indent=2)

    # disagreement table for the report
    rows_out = []
    for r in llm:
        src = SOURCE_SCENE_TO_FAMILY.get(r["scene"], "other")
        pred = PRED_TO_FAMILY[r["label"]["issue_type"]]
        if src != pred:
            rows_out.append(
                {
                    "source_scene": r["scene"],
                    "source_tone": r["tone"],
                    "pred_issue": r["label"]["issue_type"],
                    "pred_action": r["label"]["agent_action"],
                    "conf": r["label"]["confidence"],
                    "user": r["user"],
                    "bot": r["bot"][:80],
                }
            )
    with (OUT / "disagreements.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows_out[0]) if rows_out else ["empty"])
        w.writeheader()
        w.writerows(rows_out)

    low = sorted(
        [r for r in llm if r["label"]["confidence"] < 0.7],
        key=lambda x: x["label"]["confidence"],
    )
    with (OUT / "low_confidence.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["conf", "scene", "tone", "pred_issue", "user"])
        for r in low:
            w.writerow([r["label"]["confidence"], r["scene"], r["tone"], r["label"]["issue_type"], r["user"]])

    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
