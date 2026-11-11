"""Label taxonomy, label-space normalisation maps and the JSON contract used by the labeler.

The source dataset ships two free-text label columns:

    scene : 14 distinct values, many of them surface variants of the same concept
            (退换货 550 / 退货 4 / 换货 1, 质量问题 117 / 质量 5 / 质量反馈 1, ...)
    tone  : 26 distinct values that silently mix *tone* (安抚/致歉/友好) with
            *agent action* (询问/解释/协助/解决) and even *issue type* (投诉)

Both columns therefore fail the two properties a label space needs: **mutual
exclusivity** and **a fixed cardinality**. This module defines the controlled
taxonomy that the LLM labeler maps every dialogue into, plus the many-to-one
maps needed to score the model against the noisy source labels.
"""

from __future__ import annotations

from typing import Final, Literal

# --------------------------------------------------------------------------- #
# 1. Controlled taxonomy
# --------------------------------------------------------------------------- #

# Main user request. Decided by *what the user wants to happen*, not by what
# caused the problem -- this is the single rule that keeps the classes disjoint
# (e.g. "收到的杯子碎了，我要退钱" is `return_refund`, not `quality`).
ISSUE_TYPES: Final[dict[str, str]] = {
    "return_refund": "Return and/or refund: user wants money back (with or without shipping the item back).",
    "exchange": "Exchange: user wants a replacement of the same item.",
    "logistics": "Logistics: late delivery, lost parcel, wrong address, tracking stuck.",
    "quality": "Quality: user reports a defect/damage/counterfeit but has not asked for a remedy yet.",
    "compensation": "Compensation: user wants a coupon, price difference, shipping fee or other monetary make-good.",
    "complaint": "Complaint: user wants accountability, escalation, platform intervention or threatens a bad review.",
    "pre_sale": "Pre-sales: sizing, stock, shipping-time or usage questions before/without an order issue.",
    "other": "Other / cannot be determined from the dialogue.",
}

# User affect, judged from the user utterance only (not from the agent reply).
USER_EMOTION: Final[dict[str, str]] = {
    "calm": "Neutral or polite; states the issue without blame or threat.",
    "dissatisfied": "Explicit discontent, disappointment, sarcasm or repeated follow-up.",
    "angry": "Strong anger, accusation, threat to escalate / expose / leave a bad review.",
}

# Dominant action the agent takes in the reply.
AGENT_ACTION: Final[dict[str, str]] = {
    "empathize": "Apology / emotional acknowledgement is the dominant move.",
    "propose_solution": "Offers a concrete remedy (refund, replacement, coupon, compensation).",
    "guide_process": "Instructs the user how to proceed (upload photo, fill form, contact carrier).",
    "deflect_deny": "Refuses, limits liability, or pushes the problem back to the user.",
    "escalate": "Hands over to a supervisor, specialist team or platform.",
    "unclear": "Reply does not perform any of the above.",
}

# Data-quality flags. Not part of the semantic label; used to triage the corpus.
QUALITY_FLAGS: Final[dict[str, str]] = {
    "multi_issue": "Several independent requests are packed into one utterance.",
    "vague_user": "Too little information to act on (no order id, no description).",
    "unanswered": "The reply does not address the user's actual request.",
    "templated": "Reply is a boilerplate paragraph that would fit almost any dialogue.",
    "label_conflict": "The source `scene`/`tone` label contradicts the dialogue content.",
    "promise_without_policy": "Reply promises an outcome without stating any condition or limit.",
}

LABEL_SCHEMA: Final[dict] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["issue_type", "user_emotion", "agent_action", "quality_flags", "confidence"],
    "properties": {
        "issue_type": {"type": "string", "enum": list(ISSUE_TYPES)},
        "user_emotion": {"type": "string", "enum": list(USER_EMOTION)},
        "agent_action": {"type": "string", "enum": list(AGENT_ACTION)},
        "quality_flags": {
            "type": "array",
            "items": {"type": "string", "enum": list(QUALITY_FLAGS)},
            "uniqueItems": True,
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
}

IssueType = Literal[
    "return_refund", "exchange", "logistics", "quality",
    "compensation", "complaint", "pre_sale", "other",
]

# --------------------------------------------------------------------------- #
# 2. Many-to-one maps for scoring against the noisy source labels
# --------------------------------------------------------------------------- #
# The source `scene` column cannot be mapped one-to-one onto ISSUE_TYPES because
# it does not separate "refund" from "return and refund" and never separates
# "defect reported" from "defect + remedy requested". Scoring is therefore done
# on *coarse families*; a mismatch inside a family is reported separately as
# "granularity loss" instead of "model error".

SOURCE_SCENE_TO_FAMILY: Final[dict[str, str]] = {
    "退换货": "return",
    "退货": "return",
    "退款": "return",
    "换货": "return",           # kept in the same family: source never distinguishes
    "质量问题": "quality",
    "质量": "quality",
    "质量反馈": "quality",
    "质量投诉": "quality",
    "物流": "logistics",
    "补偿方案": "compensation",
    "补偿": "compensation",
    "维权投诉": "complaint",
    "差评": "complaint",
    "差评处理": "complaint",
    "退换货,质量问题": "return",  # malformed multi-label cell -> take the primary
}

PRED_TO_FAMILY: Final[dict[str, str]] = {
    "return_refund": "return",
    "exchange": "return",
    "quality": "quality",
    "logistics": "logistics",
    "compensation": "compensation",
    "complaint": "complaint",
    "pre_sale": "pre_sale",
    "other": "other",
}

# 26 source `tone` values collapsed onto the 3-level affect scale.
# Several source values are not tone at all (询问/解释/协助/解决/投诉) - they are
# agent actions or issue types. Those rows are tagged `TWISTED` and excluded
# from affect scoring, because agreement with them would measure nothing.
SOURCE_TONE_TO_EMOTION: Final[dict[str, str]] = {
    "安抚": "calm",
    "致歉": "calm",
    "抱歉": "calm",
    "歉意": "calm",
    "道歉": "calm",
    "诚恳": "calm",
    "礼貌": "calm",
    "友好": "calm",
    "友好协商": "calm",
    "耐心": "calm",
    "关心": "calm",
    "理解": "calm",
    "重视": "calm",
    "专业": "calm",
    "中肯": "calm",
    "抚慰": "calm",
    "致歉+安抚": "calm",
    "致歉安抚": "calm",
    "商量": "calm",
    # not an affect label at all -> TWISTED
    "询问": "TWISTED",
    "咨询": "TWISTED",
    "解释": "TWISTED",
    "协助": "TWISTED",
    "帮助": "TWISTED",
    "解决": "TWISTED",
    "投诉": "TWISTED",
}

# Which source labels we actively audit for semantic contradiction.
SUSPECT_TONE_LABELS: Final[set[str]] = {k for k, v in SOURCE_TONE_TO_EMOTION.items() if v == "TWISTED"}


def taxonomy_prompt_block() -> str:
    """Render the closed label space for injection into the system prompt."""
    lines = ["ISSUE_TYPE (choose exactly one; decide by what the user wants to happen):"]
    lines += [f"  - {k}: {v}" for k, v in ISSUE_TYPES.items()]
    lines += ["", "USER_EMOTION (choose exactly one, judged from the user turn only):"]
    lines += [f"  - {k}: {v}" for k, v in USER_EMOTION.items()]
    lines += ["", "AGENT_ACTION (choose the single dominant move of the agent reply):"]
    lines += [f"  - {k}: {v}" for k, v in AGENT_ACTION.items()]
    lines += ["", "QUALITY_FLAGS (zero or more; only when the evidence is in the text):"]
    lines += [f"  - {k}: {v}" for k, v in QUALITY_FLAGS.items()]
    return "\n".join(lines)
