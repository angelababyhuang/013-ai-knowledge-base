# Research: RSS 数据源 feed URL 与可用性调研

- **Query**: 为 `pipeline/rss_sources.yaml` 的 8 个源调研真实可用 RSS/Atom feed URL 与可用性（决定 `url` 与 `enabled` 默认值）
- **Scope**: external（实际 HTTP 请求验证）
- **Date**: 2026-08-06
- **验证方法**: `curl -L`（桌面 UA）逐个请求候选 URL，检查 HTTP 状态码 + 响应体是否含 `<rss`/`<feed` 根节点与 `<item`/`<entry` 条目，并抽查 `<pubDate>` 新鲜度

## 汇总表

| name | 验证后 url | HTTP | 有效 RSS/Atom | 量级评估 | 建议 enabled | 可用性结论 |
|---|---|---|---|---|---|---|
| Hacker News Best (AI 相关) | `https://hnrss.org/best` | 200 | ✅ RSS 2.0（30 items） | 中（每日数条新 best） | **true** | 已实测可用（第三方 hnrss.org，HN 官方无 RSS） |
| Lobsters AI/ML | `https://lobste.rs/t/ai.rss` | 200 | ✅ RSS 2.0（25 items） | 小（低频） | **true** | 已实测可用（官方 tag feed） |
| arXiv cs.AI | `https://rss.arxiv.org/rss/cs.AI` | 200 | ✅ RSS 2.0（416 items/快照，约 900KB） | **极大**（每日数百篇新论文） | **false** | 已实测可用，但量太大，默认关闭 |
| OpenAI Blog | `https://openai.com/blog/rss.xml` | 200 | ✅ RSS 2.0（1110 items 全量历史） | 小（新帖低频，feed 含全历史） | **true** | 已实测可用（官方） |
| Anthropic Research | `https://rsshub.rssforever.com/anthropic/news`（第三方镜像） | 200 | ✅ RSS 2.0（10 items，最新 2026-08-03） | 小 | **false** | 官方无 RSS；RSSHub 公共实例路由实测可用，依赖第三方稳定性 |
| Hugging Face Blog | `https://huggingface.co/blog/feed.xml`（未实测） | — | ⚠️ 未能验证 | 小（预期） | **false** | 官方 feed 路径已知，但本环境直连+代理均超时，未实测 |
| 机器之心 | 无可用官方 RSS | 200(HTML) | ❌ `/rss` 返回 SPA HTML，非 XML | 大（日更资讯） | **false** | 未找到可用 RSS；RSSHub 路由因公共实例过载未实测 |
| 量子位 (QbitAI) | `https://www.qbitai.com/feed` | 200 | ✅ RSS 2.0（10 items，最新 2026-08-05） | 中偏大（日更约 5-10 篇） | **false** | 已实测可用（官方 WordPress feed）；遵循课程默认 disabled，可按需开启 |

## 逐源详情

### 1. Hacker News Best (AI 相关) — 综合技术

- **URL**: `https://hnrss.org/best`
- **HTTP**: 200；有效 RSS 2.0，30 个 `<item>`
- **说明**: HN 官方（news.ycombinator.com）不提供 RSS，`hnrss.org` 是事实标准的第三方镜像（`<generator>hnrss v2.1.1</generator>`，长期稳定运行）。
- **注意**: `/best` 是**全站 best**，不是 AI 过滤源，AI 相关性需下游关键词过滤。hnrss 还支持 `hnrss.org/best?q=LLM` 等参数，可在采集层按需使用。
- **量级**: 中。`enabled: true`。

### 2. Lobsters AI/ML — 综合技术

- **URL**: `https://lobste.rs/t/ai.rss`（官方 tag feed）
- **HTTP**: 200；有效 RSS 2.0，25 个 `<item>`
- **重要陷阱**: `https://lobste.rs/t/ml.rss` 实测有效但标题为 *"MetaLanguage, OCaml programming"*——Lobsters 的 `ml` tag 是 OCaml/ML 语言，**不是机器学习**，不要用。
- **量级**: 小（低频）。`enabled: true`。

### 3. arXiv cs.AI — AI 研究

- **URL**: `https://rss.arxiv.org/rss/cs.AI`（官方；`https://export.arxiv.org/rss/cs.AI` 为等价镜像，亦 200 有效）
- **HTTP**: 200；有效 RSS 2.0，单快照 **416 个条目、约 900KB**
- **量级**: 极大——cs.AI 每日新增数百篇。全量消费会淹没流水线。
- **建议**: `enabled: false`。若未来启用，应在采集层叠加关键词/子领域过滤，或改用更窄的分类（如 `cs.CL`、`cs.LG` 同样量大）。

### 4. OpenAI Blog — 公司博客

- **URL**: `https://openai.com/blog/rss.xml`
- **HTTP**: 200；有效 RSS 2.0，1110 个 `<item>`（含全量历史）
- **说明**: `https://openai.com/news/rss.xml` 返回**完全相同**的内容（title 为 "OpenAI News"），两者任选，建议用 `/blog/rss.xml`。
- **量级**: 新帖低频（feed 长只是因为含全历史；采集层按日期去重即可）。
- **建议**: `enabled: true`。

### 5. Anthropic Research — 公司博客

- **官方无 RSS**: `https://www.anthropic.com/rss.xml`、`/news/rss.xml`、`/feed`、`/feed.xml`、`/blog/rss.xml` 全部 **404**（Next.js 站点）；`/news` HTML 页面中未发现任何 `application/rss+xml`/`atom` 链接。
- **第三方镜像（已实测可用）**: `https://rsshub.rssforever.com/anthropic/news` — HTTP 200，有效 RSS 2.0，10 个 `<item>`，最新条目 `Mon, 03 Aug 2026`（新鲜）。即 RSSHub 路由 `/anthropic/news`。
- **风险**: RSSHub 官方实例（rsshub.app）从本环境**连接超时**；公共实例 rssforever.com 间歇性 503（过载），当日重试后可用。依赖第三方稳定性，不适合作为默认开启源。
- **建议**: `enabled: false`，url 填 RSSHub 路由并在备注说明"官方无 RSS；自建 RSSHub 后可置 true"。RSSHub `/anthropic/research` 路由实测返回 503（实例过载），未能确认该路由存在。

### 6. Hugging Face Blog — 公司博客

- **URL（已知官方路径）**: `https://huggingface.co/blog/feed.xml`
- **实测结果**: ⚠️ **未能验证**。本环境对 huggingface.co 直连两次均 TCP 超时（curl HTTP=000，30-40s）；`hf.co` 返回 307 跳转后同样超时；WebFetch 工具亦超时；经 allorigins / codetabs / jina 三个公共代理中转均失败（500/521/超时）。
- **判断**: 该 URL 是 HF 社区公认的官方 blog Atom feed 路径，失败原因疑似本环境网络出口到 HF 不通（或 HF 对出口 IP 段限制），非 feed 不存在。
- **建议**: `enabled: false`，url 先填官方路径，备注"本环境未能实测，部署环境验证后可开启"。

### 7. 机器之心 — 中文社区

- **官方 RSS 已失效**: `https://www.jiqizhixin.com/rss`（及 `/rss/`）HTTP 200 但返回 **SPA HTML 页面**（6.8KB），无任何 `<rss>`/`<item>`——历史上曾有 RSS，现为前端渲染站，无公开 feed。
- **RSSHub 镜像未实测**: 路由 `/jiqizhixin` 在 rssforever.com 实例两次请求均 **503**（实例过载，非路由不存在）；pseudoyu.com 实例 **522**；rsshub.app 官方实例本环境超时。未能确认可用性。
- **量级**: 大（日更资讯类）。
- **建议**: `enabled: false`，url 留空或填 RSSHub 路由待自建实例验证。

### 8. 量子位 (QbitAI) — 中文社区

- **URL**: `https://www.qbitai.com/feed`（官方 WordPress feed）
- **HTTP**: 200；有效 RSS 2.0，10 个 `<item>`；最新 5 条 pubDate 均为 `2026-08-05`（09:38-23:52 UTC），更新活跃。
- **注意**: `https://www.qbitai.com/feed.xml` 是 **404**，正确路径是 `/feed`。
- **量级**: 中偏大（日更约 5-10 篇）。
- **建议**: `enabled: false`（遵循课程默认 disabled 的点名要求），但备注明确"**实测可用**，需要时可安全置 true"。

## Caveats / Not Found

- **Hugging Face Blog 未实测**：本环境（curl/WebFetch/3 个公共代理）均无法连通 huggingface.co，无法确认 feed 当前状态。url 是基于公开认知的官方路径。
- **机器之心未找到任何实测可用的 RSS**：官方 feed 已失效，RSSHub 路由因公共实例不稳定未能验证。
- **Anthropic 官方无 RSS**，实测可用的是第三方 RSSHub 公共实例路由，生产使用建议自建 RSSHub 实例。
- **RSSHub 公共实例整体不稳定**（本次观测到 503/522/超时各一例），凡依赖 RSSHub 的源都不应默认 enabled。
- 量级判断基于单次快照的条目数与 pubDate 密度，为粗略评估。
