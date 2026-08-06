# 添加 RSS 数据源配置 rss_sources.yaml

## Goal

按课程要求创建 `pipeline/rss_sources.yaml`，声明知识库的 RSS 数据源（name/url/category/enabled），用 `enabled` 控制是否采集，为后续 RSS 采集能力打底。本任务聚焦**配置文件本身**，并厘清它与现有架构（schema 契约 / pipeline.py）的边界，避免污染现有数据契约。

## 课程要求原文

- YAML 格式，每个源含 `name`、`url`、`category`、`enabled` 四字段。
- 分类与源：
  - 综合技术：Hacker News Best (AI 相关)、Lobsters AI/ML
  - AI 研究：arXiv cs.AI
  - 公司博客：OpenAI Blog、Anthropic Research、Hugging Face Blog
  - 中文社区：机器之心、量子位（默认 disabled，需确认 RSS 可用性）
- `enabled` 控制是否采集；量太大的源默认 `enabled: false`。

## 现状核查（已确认）

- `schemas/article.schema.json`：`source` 枚举 = `[github-hot-repos, hackernews-top]`；`category` 枚举 = `[open-source, paper-or-talk, article-or-news]`。
- `pipeline/pipeline.py`：无任何 RSS / yaml 代码；当前数据源仅 GitHub + HN。
- `pipeline/` 目录现有：`__init__.py` / `model_client.py` / `pipeline.py`。

## 与现有架构的冲突点（需对齐）

| # | 课程 | 项目现状 | 冲突 |
| --- | --- | --- | --- |
| 1 | yaml `category` = 来源分组（综合技术/AI研究/公司博客/中文社区） | article `category` = 内容类型（open-source/paper-or-talk/article-or-news） | ★★★ 同名不同义 |
| 2 | RSS 源标识（OpenAI Blog 等） | schema `source` 枚举仅 github-hot-repos/hackernews-top | ★★ 将来进 articles 会破枚举 |
| 3 | 新增 yaml 配置 | pipeline.py 无 yaml 读取逻辑 | ★ 本节只建配置，不接管 |

### 冲突 1 的处理原则（判定）

yaml 的 `category` 是**来源分组标签**（采集侧组织用），与 article 的内容类型 `category`（open-source/paper-or-talk/article-or-news）是**两个不同字段、不同维度**。本任务的 yaml 仅作数据源登记，**不写入 article.category**；未来 RSS 内容若进 articles，其类型 category 仍需按 analyzer 规则（LLM 判定）归为 3 枚举之一。二者解耦，不混淆。

## Decided Scope

1. **范围（已决）**：`rss_sources.yaml` 配置 + RSS 采集逻辑（pipeline.py 读 yaml + httpx 抓 RSS + 解析）。复杂任务，需 design.md + implement.md。
2. **产物（已决）**：RSS 走完整四步进 `articles/`，扩展 schema 契约（source 枚举 +`rss`、category 由 LLM 判定、meta 加 RSS 字段集）。
3. **源调整（用户定）**：
   - **去掉 hackernews-best**——与现有 `hackernews-top` 数据源重叠（同为 HN 数据），避免重复。
   - **arxiv-cs-ai 保留但限量**——RSS 采集统一取每个 enabled feed 的最新 N 条（默认 10，可被 `--limit` 覆盖），arXiv 量大自然只取前 10。
   - 最终 7 个源：lobsters-ai / arxiv-cs-ai / openai-blog（enabled: true）+ anthropic-research / huggingface-blog / jiqizhixin / qbitai（enabled: false）。

## Open Questions（需用户决策）

（已澄清完毕，剩余 design 细节见 design.md，review 时统一确认）

## 待研究（trellis-research）

- 各 RSS 源的真实可用 feed URL 与可用性（量子位/机器之心尤需确认），据此设 `enabled` 默认值。结果存 `.trellis/tasks/08-06-rss-sources/research/`。

## Out of Scope

- 不修改 `pipeline.py` 的采集逻辑（除非范围决策要求连带实现）。
- 不修改 `schemas/article.schema.json` 的 source/category 枚举（RSS 源暂不进 articles）。
- 不删除现有 GitHub / HN 数据源与历史数据。

## Acceptance Criteria

- [x] `pipeline/rss_sources.yaml` 存在，7 源（去 hackernews-best），每源含 name/url/category/enabled（+note）；yaml 语法合法（实测 7 源）。
- [x] arxiv-cs-ai 等大流量源通过统一 limit（默认 10）截取最新条目（parse_feed 排序+limit 实测）。
- [x] `--sources rss` 触发 RSS 采集：读 yaml enabled 源 → httpx 抓 feed → ElementTree 解析 → 幂等写 `raw/rss-{date}.json`（dry-run 实测 lobste.rs/arxiv 抓取 200 解析成功）。
- [x] RSS 条目走完整四步进 `articles/`；`source=rss`，`meta={feed_name, author, published}`。
- [x] `schemas/article.schema.json` source 枚举含 `rss`；产出 article 过 `hooks/validate_json.py`（构造样例实测 exit 0）。
- [x] article 内容类型 category 由 LLM 判定为 3 枚举之一（复用 HN 路径，非法回退 article-or-news）。
- [x] 幂等：raw 按 id、article 按 url 去重；失败源/条目穷举记 `errors-{date}.json` 不中断。
- [x] 新增依赖仅 pyyaml；未改 model_client.py / .opencode/ / hooks/；GitHub/HN 路径零改动。
