# AI Agent 题 · 任务包质量审核

## 题目定位

`题目.txt` 中"笔试题-AI Agent"一节只有标题，没有正文。实际交付的题目正文是招聘方另行发送的

> **Agent Data 算法实习生笔试题 — Agent 评测任务包质量审核**
> （`../Agent Data 算法实习生笔试题.md` + 附件 `agent-data-quality-audit-written-test-20261103-final.zip`）

该题要求以甲方验收人员身份，审核一个 Agent 评测任务包（材料 / Gold / 5 份 rollout / 3 个 probe /
rubric / scorer），判断任务可行性与评分器可靠性，并给出验收结论与回归测试。

## 交付物

答卷在工作区根目录：

| 文件 | 说明 |
| --- | --- |
| `../../answer.md` | 答卷正文（Markdown，约 7.8k 字，含 47 张表） |
| `../../answer.pdf` | 同内容 PDF（6 页，题目建议 ≤8 页） |

结构与 `answer-template.md` 对齐：0 工具与独立复核声明 → 1 任务可行性与事实基线 → 2 Rollout
风险导向抽查 → 3 Probe 审查 → 4 评分器诊断与 Rubric 重构 → 5 验收结论与回归测试 → 6 AI 使用披露。

## 结论摘要

```
任务状态：需要返修
评分器状态：需要修复
```

三条阻断级发现：

1. `instruction.md:9` 直接给出 `/workspace/solution/solve.py`，可一键生成完整答案；
2. 公开 rubric 的 40% 权重（R1 5% + R2 8% + R3 18% + R7 9%）在实际结算的
   `fresh_owner_policy.WEIGHTS` 中为 0，R5 由 25% 降至 5.56%，R6B+R6E 由 10% 放大至 65%，
   另有未公开维度 R9 占 5.99%；
3. `validator.py:22-30` 对 33 个预登记哈希直接返回存储 reward；5 份 rollout 与 Gold 的 SHA-256
   全部命中，`current_scores.md` 因此是历史回放而非本次测量。

详见 `../../answer.md`。
