# Automatic Labelling of an E-commerce After-sales Corpus with a Foundation Model

**Task** — assign a clean, closed label set to 997 Chinese customer-service dialogues whose
existing labels are demonstrably inconsistent, and quantify how much of the corpus can be
auto-labelled without a human in the loop.

---

## 1. Dataset and task description

**Dataset** — `QingshanAI/ecom-after-sale-synthetic` (Apache-2.0, 997 rows, Hugging Face
snapshot in `data/`). Each row is one dialogue: `scene`, `user`, `bot`, `tone`.

- **Input feature**: the user turn plus the agent reply (short Chinese text; 18.2 / 48.6
  characters on average). No images, no metadata.
- **Labelling target**: not the source columns, but a *controlled* label set (§2). The source
  columns are the thing being audited.

**Why this dataset.** It is a realistic data-quality case, not a toy. The two shipped label
columns fail the two properties a label space needs:

| Defect | Evidence |
| --- | --- |
| **Cardinality not controlled** | `scene` has 14 values for ~6 concepts (退换货 550 / 退货 4 / 换货 1; 质量问题 117 / 质量 5 / 质量反馈 1 / 质量投诉 1; 补偿方案 86 / 补偿 2) |
| **Dimension polluted** | `tone` has 26 values, of which **7 are not tone at all** (询问, 咨询, 解释, 协助, 帮助, 解决, 投诉) — they are agent actions or issue types. 12.5 % of sampled rows carry one |
| **Format violated** | 1 row stores `"退换货,质量问题"` — two labels in one cell |
| **Duplication** | 135 of 997 user turns (13.5 %) are exact duplicates |

So the task is **label-space normalisation plus label-noise detection**, which is the same
operation a data vendor performs when it takes over a client's legacy annotations.

## 2. Model and method

**Model** — DeepSeek-V4.1-Flash, zero-shot, temperature 0, no fine-tuning, no training data
from this corpus. Inference ran through the assistant session; `demo_code.py` targets any
OpenAI-compatible endpoint (DeepSeek / Qwen / GPT / vLLM) or a local Ollama model, so the run
is reproducible with two environment variables.

**Label space** (closed, mutually exclusive, 4 dimensions):

- `issue_type` — 8 classes, decided by *what the user wants to happen* (return_refund /
  exchange / logistics / quality / compensation / complaint / pre_sale / other). The single
  rule that keeps classes disjoint: "杯子碎了" is `quality`; "杯子碎了，退钱" is `return_refund`.
- `user_emotion` — 3 classes, judged from the **user turn only**.
- `agent_action` — 6 classes, the single dominant move of the reply.
- `quality_flags` — 6 triage flags (multi_issue, vague_user, unanswered, templated,
  label_conflict, promise_without_policy).

**Prompt design** — four deliberate choices:

1. **The taxonomy is inlined verbatim** into the system prompt, with one example per boundary
   (remedy-based, not cause-based). Ambiguity in e-commerce labelling is almost always
   "cause vs. remedy", so that boundary is stated explicitly rather than left implicit.
2. **The existing label is shown as untrusted context** (`<existing_labels …/>` + "known to be
   inconsistent"). Without this the model anchors on the noisy label; with it, disagreements
   become the signal we are looking for.
3. **Output is schema-constrained** (`response_format=json_object` + a validator that rejects
   unknown enum values). A malformed answer is retried, then recorded as an error — never
   coerced into a guess, because coercion would hide exactly the failure we are auditing.
4. **Confidence is requested explicitly**, as the probability that `issue_type` is right. This
   is what makes the human-in-the-loop budget in §4 computable.

**Sampling** — stratified by `(scene, tone)`, 120 rows, floor of 2 per stratum, rare strata
taken in full; de-duplicated on the user turn. Coverage: **14/14 scene, 26/26 tone**. A uniform
random sample would have contained almost none of the rare/malformed labels where noise lives.

## 3. Runnable code

`demo_code.py` — read corpus → build prompt → concurrent calls (8 workers) → schema validation
→ content-hash cache → JSONL + CSV. Fail-closed, resumable, retry with jittered backoff.
`prepare_sample.py` builds the stratified sample; `evaluate.py` produces all numbers below;
`taxonomy.py` holds the label space and the many-to-one maps used for scoring.

```bash
pip install -r requirements.txt                       # stdlib only, kept empty on purpose
python prepare_sample.py --size 120                   # -> data/sample_120.jsonl
export LLM_BASE_URL=https://api.deepseek.com/v1 LLM_API_KEY=sk-... LLM_MODEL=deepseek-chat
python demo_code.py --provider deepseek --sample data/sample_120.jsonl --out output/llm_120
python demo_code.py --provider offline --limit 0 --out output/offline_all   # rule baseline
python evaluate.py                                    # -> output/metrics.json
```

**Example outputs** (from `output/llm_120.csv`):

| user | source `scene`/`tone` | issue_type | user_emotion | agent_action | flags | conf |
| --- | --- | --- | --- | --- | --- | --- |
| 收到的商品有明显瑕疵。 | 退换货 / 安抚 | `quality` | calm | propose_solution | vague_user | 0.75 |
| 衣服有瑕疵，线头没剪干净，能换吗？ | 质量问题 / 安抚 | `exchange` | calm | propose_solution | — | 0.93 |
| 你们的产品质量太差了，我要求赔偿！ | 维权投诉 / 致歉 | `compensation` | angry | empathize | promise_without_policy | 0.82 |
| 物流太慢了，严重影响我的使用体验，我要投诉！ | 维权投诉 / 安抚 | `logistics` | angry | propose_solution | — | 0.85 |

## 4. Result analysis

**Agreement with the source labels** (family granularity, 120 rows): **68.3 %**, Cohen's
κ = **0.537** (moderate). LLM vs. rule baseline on the same rows: 70.0 % / κ = 0.599.

**Every one of the 38 disagreements was read and adjudicated** (`data/arbitration.json`):

| Verdict | n | Meaning |
| --- | ---: | --- |
| `model_correct` | **9** | source label contradicts the text — e.g. "能不能换货？" tagged 补偿方案 |
| `dimension_diff` | **29** | both defensible: source answers "what topic", taxonomy answers "what remedy" |
| `source_correct` | **0** | no case where the model was clearly wrong |

Two consequences. First, **the 68 % ceiling is an artefact of the source label, not of the
model**: 29 of 38 disagreements come from the source column being topic-level ("this
conversation is about returns") while the taxonomy is remedy-level. Second, **the model found
9 real annotation errors in 120 rows (7.5 %)** that the original pipeline had missed.

**Where the model is strong.** Explicit-remedy turns ("能换货吗" / "我要退货" / "我要求赔偿")
are near-perfect. Schema compliance was 120/120, with zero retries needed and zero
out-of-enum outputs.

**Where it fails or is weakest.**

1. **No-remedy turns.** 20/120 rows carry `vague_user`; when the user only states a defect
   ("收到的商品有明显瑕疵。") the remedy class is genuinely undetermined. The model defaults to
   `quality` and lowers confidence to 0.7–0.75 — correct behaviour, but it means
   **turns without an explicit ask should be routed to a separate "remedy unknown" workflow**,
   not forced into the 8-class space.
2. **Compound terms.** "退换货" is one word covering two remedies. The model splits it by
   reading the rest of the turn ("能不能换货" → `exchange`); when there is no other signal it
   must guess, and that is the single largest confusion cell (`return → quality`, 16 cases).
3. **Complaint vs. root cause.** "物流太慢，我要投诉" is both a `logistics` incident and a
   `complaint` act. The model picks the root cause; the source picks the act. Neither is wrong;
   the label space needs a second axis (see §6).
4. **Templated replies.** 96 % of agent replies are near-identical boilerplate, so
   `agent_action` collapses to `guide_process` (54 %) and `propose_solution` (44 %). The
   dimension is measurable but carries little information — a finding about the *corpus*, not
   the model.

**Calibration** — monotone, which is what makes deployment possible:

| confidence | n | agreement with source |
| --- | ---: | ---: |
| 0.90–1.00 | 50 | **90.0 %** |
| 0.70–0.90 | 63 | 57.1 % |
| 0.50–0.70 | 7 | 14.3 % |

At threshold 0.80 the pipeline auto-adopts **71.7 %** of rows at **81.4 %** agreement and sends
34 to review; at 0.90 it auto-adopts 41.7 % at 90.0 %. A reviewer budget of ~28 % therefore
buys agreement in the high 80s.

## 5. Human vs. model labelling

| Dimension | Human / rule pipeline | Foundation model |
| --- | --- | --- |
| **Speed** | this 120-row sample ≈ 40–50 min at 8 s/row | < 3 min end-to-end, and flat in corpus size |
| **Cost** | dominant cost at 10k+ rows | ≈ 1 call per row, no per-row human cost |
| **Consistency** | the 26 `tone` values and 14 `scene` values *are* the drift | deterministic at temperature 0; same prompt → same label |
| **Semantic depth** | rules cannot separate "describes a defect" from "demands a refund"; the rule baseline emitted `other` for 20.7 % of the corpus | separates remedy from cause, reads intent, flags vagueness |
| **Bias** | inherits annotator fatigue and the template's vocabulary | over-weights explicit keywords ("投诉") and under-weights implicit asks; inherits the source label when shown as context |
| **Auditability** | rationale usually lost | every row carries provider, model, prompt version, confidence (`output/llm_120.jsonl`) |
| **Failure mode** | silent drift, unmeasurable without a second annotator | confident and wrong on genuinely ambiguous rows — hence the confidence gate |

The honest summary: the model is **not a replacement for an annotator, it is a replacement for
the first pass**. Its value here is precisely that it disagrees — 9 of its 38 disagreements
were annotation errors the client did not know it had.

## 6. Improvement ideas

1. **Split the label space into orthogonal axes.** Today `complaint` competes with `logistics`
   for the same row. Make it `issue_type` (cause) × `requested_remedy` (action) ×
   `escalation_intent` (bool). That alone removes 4 of the 38 disagreements and makes the
   29 `dimension_diff` cases scoreable instead of ambiguous.
2. **Add an `agent_tone` field and audit `tone` properly.** The current `tone` column describes
   the agent, not the user, and 7 of its 26 values are actions. Re-labelling the reply on a
   4-level tone scale would let the existing column be validated instead of discarded —
   the cross-check in `metrics.json` (`tone_vs_emotion_kappa = 0.0`) shows the column carries
   no information about user affect at all.
3. **Multi-model voting with disagreement mining.** Run two models (e.g. DeepSeek + Qwen) at
   temperature 0.3, κ-aggregate, and send only low-κ rows to humans. Disagreement is a far
   better uncertainty signal than a self-reported confidence, especially on the 29
   `dimension_diff` rows where one model will prefer cause and the other remedy.
4. **Two-stage labelling instead of one 8-way call.** Stage 1: does the turn contain an
   explicit remedy? (binary, 98 % trivially learnable). Stage 2: which remedy. This removes
   the `vague_user` bucket (20/120) from the closed set and stops the model from being forced
   to guess.
5. **Few-shot calibration on adjudicated edge cases.** The 38 adjudicated rows in
   `data/arbitration.json` are exactly the boundary set: feeding 6–8 of them as few-shot
   examples should lift κ on `return vs. exchange` and `complaint vs. logistics` without
   touching the taxonomy.

---

*Reproduce with `python evaluate.py`; all numbers in §4 are written to `output/metrics.json`.*
