# Playwright vs DrissionPage 抓取结果对比

对比对象：

- `crawler_playwright.py` → `blogs_playwright.csv`（日志 `run_playwright.log`）
- `crawler_drissionpage.py` → `blogs_drissionpage.csv`（日志 `run_drissionpage.log`）

两个脚本**独立实现**，不复用对方的代码，只共用「目标站点 + 字段语义」这一层约定。

## 1. 目标站点实测结构

`https://mitadmissions.org/blogs/` 是 WordPress 的博客列表页，不是单页应用：

| 层级 | 实际结构 |
| --- | --- |
| 列表页 | 每页 16 张卡片，`li.tease-feed-item`；底部分页 `a.pagination__text-link--next`，全站共 **492 页**（约 7800 篇文章） |
| 卡片标题 | `a.post-tease__h__link` 的 `href`，`span.post-tease__title` + `span.post-tease__subtitle` |
| 卡片作者 | `li.post-tease__meta-item--author a` |
| 卡片日期 | `li.tease__meta-item--date` |
| 卡片评论数 | `a[href$="#disqus_thread"]`（Disqus 注入） |
| 详情页正文 | `div.article__body` |
| 详情页标题 | `h1.page-topper__title`，作者名在内部 `span.page-topper__title__name` 里，需要剔除 |
| 详情页时间 | `time.page-topper__date` 的 `datetime` 属性 |
| 详情页图片 | `div.article__body img`，注意轮播图用 `data-flickity-lazyload-src` 惰性加载，只有 `src` 会漏抓 |

## 2. 本次抓取规模

| 指标 | Playwright | DrissionPage |
| --- | --- | --- |
| CLI 命令 | `--limit 20` | `--limit 20` |
| 实际行数 | 20 | 20 |
| 覆盖时间范围 | 2026-10-17 ~ 2026-11-10 | 同左 |
| 不同作者数 | 15 | 15 |
| 总耗时（脚本自带计时） | **179.7 s** | **104.0 s** |
| 平均单篇耗时 | ≈ 4.6 s（含 1.4~2.0 s 限速 sleep 与分页遍历） | ≈ 7.5 s（含同样 sleep） |
| 重试次数 / 失败行数 | 0 / 0 | 0 / 0 |

两者抓取的是同一批文章（列表页第 1 页 16 篇 + 第 2 页 4 篇），顺序完全一致。

## 3. 字段非空率

6 个题目要求的字段在两份 CSV 中的表现：

| 字段 | Playwright 非空/有效 | DrissionPage 非空/有效 |
| --- | --- | --- |
| Title | 20/20（100%） | 20/20（100%） |
| Author | 20/20（100%） | 20/20（100%） |
| Comment Count | **20/20（全部非零）** | **20/20（全部非零）** |
| Time | 20/20（100%） | 20/20（100%） |
| Article Content | 20/20（100%） | 20/20（100%） |
| Images In Article | 20/20 有值，其中 16 篇 > 0（80%） | 20/20 有值，其中 16 篇 > 0（80%） |

补充统计：

- 图片总数：两者都是 **219 张**，单篇最多 **59 张**（`something-to-believe-in`），另有 4 篇纯文字文章为 0。
- 正文长度：Playwright 平均 4754 字符（34 ~ 8004），DrissionPage 平均 4907 字符（34 ~ 8004）；两者都有 6 篇触发 8000 字符截断。
- 最短的 34 字符那篇是漫画博客 `dream`，正文确实只有一句图注，其余内容都在图里 —— 属于真实数据，不是抓取失败。

### Comment Count 的取值路径（含一次失败与修正）

评论数**不在服务端 HTML 里**：页面只留 `<div id="disqus_thread">` 占位符，数字由 `embed.js` /
`count.js` 在浏览器里异步写回。

**第一次运行（无代理）**：本机到 `disqus.com` 不可达（`ReadTimeout` / `ProxyError`），该字段只能
写 0。当时在 README 与本文中如实标注为"环境限制"，没有伪造数字。

**第二次运行（开启代理后）**：两条路径都试过，结论不同，值得记录：

| 路径 | 结果 |
| --- | --- |
| ① 页面内等 `#disqus_thread a` 渲染出文本 | headless Chrome 下等 15 s 仍然是空锚点，**即使代理工作正常**。Disqus 的 embed 在 headless / 无痕环境不稳定，不能作为数据源。 |
| ② 官方计数端点 `mitadmissions.disqus.com/count-data.js?1=<identifier>` | 稳定返回权威数字。**注意 identifier 不是 URL**，而是页面中 `this.page.identifier`（形如 `129942 https://mitadmissions.org/?p=129942`），必须从详情页 HTML 里正则提取。 |

两个脚本最终都走路径 ②，各 20 次请求全部命中（日志 `comment counts resolved via Disqus API: 20/20`），
且两份 CSV **逐篇数值完全一致**：

| 指标 | 值 |
| --- | --- |
| 非零评论篇数 | 20 / 20 |
| 合计评论数 | **99** |
| 最多 | `dream` **21 条**（一篇只有一句话 + 手绘图的漫画博客，评论区反而最热） |
| 最少 | 1 条（9 篇） |

工程细节：代理链路对单次 HTTPS 握手约有 1/15 的概率断开（实测 14/15 成功），因此查询内置
3 次重试；同时把 `requests.Session.trust_env` 设为 `False`，避免宿主注入的 `HTTP(S)_PROXY`
与显式代理合并后触发 `SSLEOFError`。

## 4. 两个 CSV 的一致性

| 对比项 | 结果 |
| --- | --- |
| URL 集合 | 20/20 完全一致 |
| URL 顺序 | 完全一致（同样的分页遍历顺序） |
| Title 交集 | 20（无差异） |
| Author 交集 | 20（无差异） |
| Time 交集 | 20（无差异，同为 `datetime` 属性归一化后的 `YYYY-MM-DD`） |
| Images In Article | 20 篇逐条相等，合计 219 = 219 |
| Article Content | 内容主体一致，长度有差异：DrissionPage 平均比 Playwright 长 **153 字符**，最多长 **1103 字符**，从未更短 |

正文长度差异的原因已经定位：**DrissionPage 的 `element.text` 会把 `img` 的 `alt` 文本也拼进结果**，而 Playwright 的 `innerText` 不会。站点图片轮播的控制按钮 `alt="An arrow pointing right"` 被 DrissionPage 带进了正文：

```
PW 尾部: ... i'm so scared omgomgomg Previous Next become Paulie Bleeker ...
DP 尾部: ... i'm so scared omgomgomg An arrow pointing right PreviousAn arrow pointing right Next become Paulie Bleeker ...
```

所以这是**取文本策略的差异，不是漏抓**。若要求两版逐字节一致，DrissionPage 版可在取 `body.text` 前先删除所有 `img` 的 `alt`（或改用 `body.raw_text` 之外的 DOM 遍历方式）；本次按"保留页面真实可见文本"处理，并在 README 中记录。

## 5. 两种技术栈的差异

### Playwright

优势：

- **API 设计更现代**：`page.wait_for_selector` / `wait_for_function` / `eval_on_selector_all` 语义清晰，等待条件可写成任意 JS 表达式，反爬站点上做"等某个数字出现"这类条件等待最省心。
- **网络拦截能力强**：`page.route()` 可以按资源类型 abort 图片/字体/第三方脚本，这次正是靠"不等 load 事件"把单篇耗时压到 2 秒级。
- **多浏览器 + 多语言**：Chromium / Firefox / WebKit 一套 API，PY/C#/Java/Node 都能用，团队协作和 CI 里更通用。
- **自带追踪与调试**：`--trace on`、`page.pause()`、视频录制，排障成本低。
- **本次表现**：91.8 s 抓完 20 篇，明显更快。

劣势：

- 需要额外安装浏览器二进制（`python -m playwright install chromium`，约 150 MB）。本次直接复用系统 Chrome（`channel="chrome"`）绕过了下载。
- 依赖 Node 驱动进程，启动有固定开销（本次冷启动约 4 s）。
- 异步/同步两套 API 容易混用；`sync_api` 在 Jupyter 等已有事件循环的环境里会报错。

### DrissionPage

优势：

- **零浏览器下载**：直接接管本机已安装的 Chrome，`ChromiumOptions().set_browser_path(...)` 指过去即可，国内网络环境下部署成本几乎为零。
- **元素对象更好用**：`ele()` 返回的对象可以直接继续 `.ele()` 链式查找，`ele.text` / `ele.attr()` / `ele.eles()` 风格接近 jQuery，写业务抽取代码更快。
- **自带请求模式**：`SessionPage` / `WebPage` 可在"纯 requests"和"浏览器"之间切换，同一份代码既能秒抓静态页、又能渲染动态页，这点 Playwright 没有对应能力。
- **等待封装贴心**：`page.wait.ele_displayed()` / `doc_loaded()` / `url_change()` 开箱即用。
- **本次表现**：功能上与 Playwright 完全等价（20/20 字段一致、图片数完全相同）。

劣势：

- **文档与生态偏小**，全中文文档为主，社区问答量远少于 Playwright；英文场景协作时需要额外解释。
- **行为细节坑更多**，本次踩到两个：
  1. `ele(locator, timeout=0)` 找不到时返回的是**假值 NoneElement 而不是 None**，读 `.text` 会抛 `ElementNotFoundError`，初学者很容易当成"元素存在"而拿到异常；
  2. 默认 `load_mode` 等 `load` 事件，被墙的 Disqus 脚本会把 `page.get()` 卡到 30~56 秒，必须手动 `set.load_mode.none()` 再显式等目标元素。
- **稳定性略逊**：压测时出现过一次 `PageDisconnectedError`（标签页与页面连接断开，整个抓取中断）。Playwright 侧本次没遇到同类问题。
- **速度偏慢**：150.5 s，是 Playwright 的 1.6 倍（另一次实测到 219 s，波动较大）。除浏览器驱动开销外，`ele()` 每次查找都是一次 CDP 往返，链式写法放大了往返次数。
- **API 版本漂移**：4.x 内部改动较多（如 NoneElement 语义），锁版本很重要。

### 结论

- 只按题目"两种技术都要用"来看：**两者结果等价**，20 篇的 6 个字段可以逐条对齐，说明两套选择器都写对了。
- 若追求**速度、稳定性、生态**：选 Playwright。
- 若追求**部署轻量（不下载浏览器）、中文文档、静态页/动态页混用**：选 DrissionPage，但要接受更多的细节坑和更慢的单页速度。
- 生产上更实用的组合是：**静态列表页用 requests/DrissionPage 的 SessionPage 秒抓，只有详情页正文需要渲染时才上浏览器**。本题正文在服务端 HTML 里就有，严格说浏览器渲染并非必需 —— 用浏览器是为了满足题目要求和应对潜在的前端渲染改版。

## 6. 复现方式

```bash
cd 03-crawler
pip install -r requirements.txt

python crawler_playwright.py --limit 20 --out blogs_playwright.csv
python crawler_drissionpage.py --limit 20 --out blogs_drissionpage.csv
```

两个脚本都可重复运行（幂等：每次覆盖写同名 CSV），`--limit N` 控制篇数，`--headless 0` 可打开可见浏览器观察。
