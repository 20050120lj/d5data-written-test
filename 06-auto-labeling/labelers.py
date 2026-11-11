"""Label providers: real LLM endpoints (OpenAI-compatible / Ollama) plus a rule baseline.

All providers share one interface::

    label(dialogue) -> dict matching taxonomy.LABEL_SCHEMA

The rule baseline exists for two reasons:

1. It gives the deliverable a *gold-ish reference* that does not depend on any
   API key, so the comparison "LLM vs. keyword rules" can be reported honestly.
2. It exposes exactly which cases are hard: every case where rules and the LLM
   disagree is by construction a case that needs semantic understanding.

Nothing here fabricates model output. If no endpoint is configured, run.py
refuses to write a file that claims to be LLM-labelled.
"""

from __future__ import annotations

import json
import os
import random
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from taxonomy import LABEL_SCHEMA, taxonomy_prompt_block

# --------------------------------------------------------------------------- #
# Prompt design
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT = """You are a data-quality annotator for a Chinese e-commerce after-sales corpus.
You will be shown one customer-service dialogue (one user turn, one agent reply).
Assign labels from the CLOSED taxonomy below. Never invent a label that is not listed.

{taxonomy}

Rules of application:
1. `issue_type` is decided by the remedy the user is asking for, not by the cause.
   "杯子碎了" (no remedy asked yet) -> quality. "杯子碎了，退钱" -> return_refund.
2. If the user asks for two different remedies, pick the one they lead with and add
   the flag `multi_issue`.
3. `user_emotion` is judged from the USER turn only. A polite agent reply must not
   make an angry user look calm.
4. `agent_action` is the single dominant move. An apology followed by a concrete
   remedy is `propose_solution`, not `empathize`.
5. Only raise a `quality_flag` when the text itself is the evidence. Do not guess.
6. `confidence` is your own probability that `issue_type` is correct. Use < 0.6 when
   the dialogue is genuinely ambiguous.

Return one JSON object and nothing else."""

USER_TEMPLATE = """<user>{user}</user>
<agent>{bot}</agent>
{source_hint}
Return JSON with keys: issue_type, user_emotion, agent_action, quality_flags, confidence."""


def build_messages(user: str, bot: str, source_scene: str | None = None, source_tone: str | None = None) -> list[dict]:
    hint = ""
    if source_scene or source_tone:
        # The source label is shown as *context only*; the prompt explicitly tells
        # the model it may be wrong. This is what lets us measure label noise.
        hint = (
            f"<existing_labels scene=\"{source_scene or ''}\" tone=\"{source_tone or ''}\"/>\n"
            "These existing labels were produced by a weaker process and are known to be "
            "inconsistent. Treat them as a hint that may be wrong; label from the text."
        )
    return [
        {"role": "system", "content": SYSTEM_PROMPT.format(taxonomy=taxonomy_prompt_block())},
        {"role": "user", "content": USER_TEMPLATE.format(user=user, bot=bot, source_hint=hint)},
    ]


# --------------------------------------------------------------------------- #
# Provider: OpenAI-compatible endpoint (DeepSeek / Qwen / GPT / vLLM ...)
# --------------------------------------------------------------------------- #

@dataclass
class ChatProvider:
    """Minimal OpenAI-compatible chat client (works with DeepSeek, DashScope, vLLM, Ollama)."""

    base_url: str
    api_key: str
    model: str
    temperature: float = 0.0
    max_tokens: int = 300
    timeout: int = 60
    max_retries: int = 3

    def __post_init__(self) -> None:
        import urllib.request  # stdlib only: keeps requirements.txt empty
        self._urlopen = urllib.request.urlopen

    def label(self, record: dict) -> dict:
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
            "messages": build_messages(
                record["user"], record["bot"], record.get("scene"), record.get("tone")
            ),
        }
        body = json.dumps(payload).encode()
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                req = __import__("urllib.request", fromlist=["Request"]).Request(
                    self.base_url.rstrip("/") + "/chat/completions",
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.api_key}",
                    },
                )
                with self._urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode())
                text = data["choices"][0]["message"]["content"]
                return parse_label_json(text)
            except Exception as exc:  # noqa: BLE001 - transport errors are expected
                last_err = exc
                time.sleep(min(2 ** attempt + random.random(), 10))
        raise RuntimeError(f"LLM call failed after {self.max_retries} retries: {last_err}")


# --------------------------------------------------------------------------- #
# Provider: rule baseline
# --------------------------------------------------------------------------- #
# Deliberately keyword-driven. It is *not* a strawman: the keyword lists are
# curated and ordered by priority, and the baseline reaches a reasonable
# agreement with the source labels. Its failures are what justify the LLM.

_ISSUE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("logistics", ("物流", "快递", "发货", "到货", "派送", "签收", "运输", "单号", "配送", "多久到", "几天到", "运单")),
    ("complaint", ("投诉", "曝光", "315", "消协", "工商", "起诉", "差评", "举报", "维权", "告你们", "骗子", "欺骗")),
    ("compensation", ("补偿", "赔偿", "优惠券", "差价", "运费", "红包", "赔", "补发")),
    ("exchange", ("换货", "换一个", "换新", "换件", "重发一个")),
    ("return_refund", ("退款", "退货", "退钱", "退掉", "退了", "退换", "申请退")),
    ("quality", ("质量", "破损", "碎了", "坏了", "瑕疵", "污渍", "过期", "假货", "开线", "掉色", "缩水", "异味", "少件", "缺件")),
    ("pre_sale", ("尺码", "颜色有", "有没有货", "库存", "什么时候发", "怎么用", "能用吗", "适合")),
]

_ANGRY = ("垃圾", "无语", "气死", "过分", "骗子", "曝光", "投诉", "什么破", "恶心", "坑人", "退钱！！", "！！")
_DISSAT = ("不满意", "失望", "太差", "很差", "不好", "有问题", "怎么这样", "为什么", "还没", "一直没", "迟迟")

_EMPATHIZE = ("抱歉", "对不起", "谅解", "理解您", "给您带来不便", "非常抱歉", "不好意思")
_SOLUTION = ("可以为您", "为您办理", "给您退款", "换货", "补发", "补偿", "优惠券", "退货", "退款", "重新")
_GUIDE = ("请提供", "请上传", "请您", "麻烦您", "点击", "填写", "联系快递", "拍照", "照片", "截图")
_DENY = ("不支持", "无法", "不能", "不在", "不符合", "抱歉无法", "超过", "规定")


def rule_label(record: dict) -> dict:
    user = record["user"]
    bot = record["bot"]
    flags: list[str] = []
    confidence = 0.55

    issue = "other"
    for name, kws in _ISSUE_RULES:
        if any(k in user for k in kws):
            issue = name
            confidence = 0.7
            break

    # A second, different ask in the same utterance -> multi_issue
    hits = [n for n, kws in _ISSUE_RULES if any(k in user for k in kws)]
    if len(hits) >= 2:
        flags.append("multi_issue")
        confidence -= 0.1

    emotion = "calm"
    if any(k in user for k in _ANGRY):
        emotion = "angry"
    elif any(k in user for k in _DISSAT) or "!" in user or "！" in user:
        emotion = "dissatisfied"

    if any(k in bot for k in _DENY):
        action = "deflect_deny"
    elif any(k in bot for k in _EMPATHIZE) and not any(k in bot for k in _SOLUTION):
        action = "empathize"
    elif any(k in bot for k in _SOLUTION):
        action = "propose_solution"
    elif any(k in bot for k in _GUIDE):
        action = "guide_process"
    elif "转" in bot or "主管" in bot or "专员" in bot:
        action = "escalate"
    else:
        action = "unclear"

    if len(user) < 8:
        flags.append("vague_user")
    if len(bot) > 90 and bot.count("，") >= 4:
        flags.append("templated")
    if issue != "other" and not any(k in bot for k in _SOLUTION + _GUIDE + _DENY + _EMPATHIZE):
        flags.append("unanswered")

    return {
        "issue_type": issue,
        "user_emotion": emotion,
        "agent_action": action,
        "quality_flags": sorted(set(flags)),
        "confidence": round(max(0.3, min(0.85, confidence)), 2),
    }


# --------------------------------------------------------------------------- #
# Parsing / validation
# --------------------------------------------------------------------------- #

def parse_label_json(text: str) -> dict:
    """Extract the first JSON object and validate it against the closed schema."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    start, depth = None, 0
    for i, ch in enumerate(text):
        if ch == "{":
            if start is None:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if start is not None and depth == 0:
                obj = json.loads(text[start : i + 1])
                return validate_label(obj)
    raise ValueError(f"No JSON object found in model output: {text[:200]}")


def validate_label(obj: dict) -> dict:
    """Fail closed: an invalid label must not silently enter the dataset."""
    props = LABEL_SCHEMA["properties"]
    out: dict[str, Any] = {}
    for key in ("issue_type", "user_emotion", "agent_action"):
        value = obj.get(key)
        if value not in props[key]["enum"]:
            raise ValueError(f"invalid {key}: {value!r}")
        out[key] = value
    flags = obj.get("quality_flags") or []
    if not isinstance(flags, list):
        raise ValueError("quality_flags must be a list")
    allowed = set(props["quality_flags"]["items"]["enum"])
    out["quality_flags"] = sorted({f for f in flags if f in allowed})
    try:
        conf = float(obj.get("confidence", 0.5))
    except (TypeError, ValueError):
        conf = 0.5
    out["confidence"] = round(min(1.0, max(0.0, conf)), 3)
    return out


def build_provider(name: str) -> Callable[[dict], dict]:
    """Factory used by run.py. `offline` is the only key-free option."""
    name = name.lower()
    if name == "offline":
        return rule_label
    if name in {"openai", "deepseek", "qwen", "compatible"}:
        base = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
        key = os.getenv("LLM_API_KEY", "")
        model = os.getenv("LLM_MODEL", "deepseek-chat")
        if not key:
            raise SystemExit(
                "LLM_API_KEY is not set. Export LLM_BASE_URL / LLM_API_KEY / LLM_MODEL, "
                "or run with --provider offline to get the rule baseline."
            )
        return ChatProvider(base_url=base, api_key=key, model=model).label
    if name == "ollama":
        base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")
        return ChatProvider(base_url=base, api_key="ollama", model=model).label
    raise SystemExit(f"unknown provider: {name}")
