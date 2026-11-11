# Auto-labelling an e-commerce after-sales corpus with a foundation model

Submission for **"Auto Labeling with LLM / VLM / Other foundation models"**.

The corpus ships two free-text label columns that are themselves the problem: `scene` has 14
values for ~6 concepts, `tone` has 26 values of which 7 are not tone at all. So the task is
**label-space normalisation + label-noise detection**, not "label from scratch".

## Quick start

```bash
python prepare_sample.py --size 120                # stratified sample -> data/sample_120.jsonl
python demo_code.py --provider offline --limit 0 --out output/offline_all   # rule baseline, no key
python demo_code.py --provider deepseek --sample data/sample_120.jsonl --out output/llm_120
python evaluate.py                                 # -> output/metrics.json, confusion, disagreements
```

`demo_code.py` talks to any OpenAI-compatible endpoint. Configure with:

| env var | default |
| --- | --- |
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` |
| `LLM_API_KEY` | *(required for non-offline providers)* |
| `LLM_MODEL` | `deepseek-chat` |

Local model instead of an API: `python demo_code.py --provider ollama --sample …`
(needs `ollama serve` + `ollama pull qwen2.5:7b-instruct`).

## Files

| File | Role |
| --- | --- |
| `taxonomy.py` | Closed label space (8 issue / 3 emotion / 6 action / 6 flags) + the many-to-one maps used to score against the noisy source labels |
| `labelers.py` | Prompt template, OpenAI-compatible client, rule baseline, fail-closed JSON validator |
| `demo_code.py` | CLI entry point: concurrency, content-hash cache, retry, JSONL + CSV output with provenance |
| `prepare_sample.py` | Stratified sampler (floor per stratum so rare/malformed labels are represented) |
| `evaluate.py` | Agreement, κ, adjudication roll-up, confidence calibration, HITL coverage/quality curve |
| `report.md` | 2-page write-up: dataset, method, results, human-vs-model, improvements |
| `data/sample_120.jsonl` | The 120 evaluated rows (14/14 scene, 26/26 tone covered) |
| `data/arbitration.json` | Hand adjudication of all 38 disagreements |
| `output/llm_120.{jsonl,csv}` | Model labels + provenance |
| `output/offline_all.{jsonl,csv}` | Rule baseline over all 997 rows |
| `output/metrics.json` | Every number quoted in `report.md` |

## Headline results (120 stratified rows)

| Metric | Value |
| --- | --- |
| Agreement with source `scene` (family level) | 68.3 % (κ = 0.537) |
| Adjudicated disagreements | 38 → **0** model errors, **9** source-label errors, 29 dimension differences |
| Calibration (conf ≥ 0.90) | 50 rows, **90.0 %** agreement |
| HITL @ threshold 0.80 | 71.7 % auto-adopted, 81.4 % agreement, 34 rows to review |
| Rule baseline `other` rate (997 rows) | 20.7 % (LLM: 0 %) |

## Design notes

* **Fail closed.** Invalid model output is retried and then recorded as an error; it is never
  coerced into the nearest valid label.
* **The existing label is shown to the model as untrusted context**, explicitly marked as
  possibly wrong. Without this the model anchors on it and disagreement collapses to zero.
* **Provenance on every row** — provider, model, prompt version, UTC timestamp — because a
  label you cannot audit later is not a label.
* **No data is fabricated.** `output/llm_120.jsonl` was produced by a foundation model and
  cached; `python demo_code.py --provider deepseek` reproduces it against the real endpoint.
* **Stdlib only** — no `openai` dependency, so the file runs anywhere Python runs.
