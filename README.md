# 五维数据（d5data）笔试 · 六题交付

本仓库是「杭州五维数据有限责任公司」笔试的完整交付，覆盖 `题目.txt` 中列出的六个方向。
题目说明中写明"以上笔试题包含不同岗位，因为我们更想要交叉方向人才，请按照自身能力尽可能多的完成"，
因此六道题均按可运行、可复现的标准完成，而非只给设计思路。

> 六道题中五道有可执行产物；**AI Agent 题的正文由招聘方另行发送**（`Agent Data 算法实习生笔试题.md` + 附件 zip），
> 该题的答卷为 `answer.md` / `answer.pdf`，见 `05-ai-agent/`。

## 目录

| # | 题号 | 目录 | 技术栈 | 状态 |
| --- | --- | --- | --- | --- |
| 1 | 前端 | [`01-frontend/`](01-frontend) | HTML + CSS + 原生 JS | ✅ 1440 / 760 / 390 三档已验证 |
| 2 | 后端 | [`02-backend/`](02-backend) | Spring Boot 3.2.0 + Spring Security 6 + JWT | ✅ 构建成功，5 条 curl 断言全过 |
| 3 | 爬虫 | [`03-crawler/`](03-crawler) | Playwright + DrissionPage | ✅ 真实抓取，产出 CSV |
| 4 | Python | [`04-python-streaming/`](04-python-streaming) | FastAPI + SSE | ✅ 12/12 wire-level 检查通过 |
| 5 | AI Agent | [`05-ai-agent/`](05-ai-agent) | 任务包质量审核（文档题） | ✅ `answer.md` / `answer.pdf` |
| 6 | 算法 | [`06-auto-labeling/`](06-auto-labeling) | LLM Auto Labeling | ✅ 120 条标注 + 评估 + 报告 |

## 各题速览

### 01 前端 — Figma 还原

按设计稿实现「Upload Your Resume」页：左栏文案 + 插画，右栏 Upload file 卡片（虚线拖拽区、
双按钮、三点进度条）。颜色从设计稿采样（`#005EFF` / `#61AFFF` / `#F0FBFF`）。

```bash
cd 01-frontend && python -m http.server 8080   # http://127.0.0.1:8080/
```

加分项全部实现：点击/拖拽上传、hover/active、移动端上下布局、显示文件名、语义化 + 无障碍。

### 02 后端 — SpringBoot 3.2.0 + Security

`GET /api/hello` 需认证，返回纯文本 `Hello World`；`POST /api/login`（`test` / `123456`）签发 JWT；
未认证返回 **401**（而非 formLogin 的 302 或默认的 403，原因见 `SecurityConfig` 注释）。

```bash
cd 02-backend && ./mvnw spring-boot:run
```

真实运行记录见 `02-backend/verify.log`（含 5 条 curl 的完整响应头与 body）。

### 03 爬虫 — Playwright + DrissionPage

同一目标站点（`https://mitadmissions.org/blogs/`）用两种技术栈各实现一遍，输出字段：
`Title | Author | Comment Count | Time | Article Content | Images In Article`。

```bash
cd 03-crawler && pip install -r requirements.txt && python crawler_playwright.py --limit 20
```

### 04 Python — FastAPI streaming

SSE token 流 + 缓冲式基线 + 浏览器对比页；处理首字节、心跳、取消传播、带内错误四件事。

```bash
cd 04-python-streaming && pip install -r requirements.txt && uvicorn main:app --port 8000
python test_stream.py --base http://127.0.0.1:8000    # 12/12
```

### 05 AI Agent — 评测任务包质量审核

以甲方验收人员身份审计一个 Agent 评测包，结论：

```
任务状态：需要返修    评分器状态：需要修复
```

三条阻断问题（答案泄露、40% 公开权重被清零、冻结哈希短路使分数不可验证）见
`answer.md` 第 4.1 节。

### 06 算法 — LLM Auto Labeling

对 997 条电商售后对话做**标签体系归一化 + 标签噪声检出**（原始 `scene` 14 值 / `tone` 26 值，
其中 7 个 tone 根本不是语气）。120 条分层抽样，与源标签的一族级一致率 68.3%（κ=0.537），
逐条仲裁 38 条分歧后：**0 条模型错误、9 条源标签错误、29 条维度口径差异**。

```bash
cd 06-auto-labeling && python demo_code.py --provider offline --limit 0 --out output/offline_all
python evaluate.py
```

## 环境

| 依赖 | 版本 | 用于 |
| --- | --- | --- |
| JDK | 17 | 02-backend（项目自带 Maven Wrapper，无需预装 Maven） |
| Python | 3.10+ | 03 / 04 / 06 |
| Chrome | 任意近期版本 | 03-crawler（Playwright 可用自带 Chromium，DrissionPage 复用系统 Chrome） |

`06-auto-labeling` 仅用标准库，无需 `pip install`；`03` / `04` 的依赖见各自 `requirements.txt`。

## 关于「不使用框架」的说明

前端题允许使用框架。这里选择原生 HTML/CSS/JS，是因为该页面没有状态管理需求，引入构建链
会让评审多一步 `npm install`，且不利于直接双击打开验收。后端与 Python 题按题目指定技术栈实现。
