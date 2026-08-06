# 技术设计：RSS 数据源（rss_sources.yaml + 采集逻辑）

## 1. 总体形态

为 pipeline 新增 RSS 数据源：新增 `pipeline/rss_sources.yaml` 声明数据源，`pipeline/pipeline.py` 增加 RSS 采集路径，产出走**完整四步**进 `articles/`。与现有 GitHub / HN 同架构，复用 Analyze / Organize / Save。

```
rss_sources.yaml (enabled 源)
  └─ Collect   读 yaml → httpx 抓 feed → 解析 RSS/Atom → 取最新 limit 条 ──▶ knowledge/raw/rss-{date}.json
  └─ Analyze   复用现有 LLM 分析（summary/tags/五维/category 判定）          ──▶ knowledge/enriched/rss-{date}.enriched.json
  └─ Organize  复用四规则门控 + url 去重
  └─ Save      12 字段 article + index.json + _filtered                       ──▶ knowledge/articles/
```

## 2. 关键设计决策

### D1. source 命名：统一 `rss`
- 所有 RSS 源的条目 `source` 字段统一为 `"rss"`；schema `source` 枚举只加一个值，改动最小、可扩展。
- 具体源名（openai-blog 等）放入 `meta.feed_name`，下游可按源聚合。
- 理由：若每源一个 source 值，schema 枚举随源膨胀，违背「单一事实来源」的可维护性。

### D2. category 双维度解耦
- yaml 的 `category`（来源分组：general-tech / ai-research / company-blog / chinese-community）**仅作采集侧组织**，用英文 slug 以贴合项目 kebab-case 风格，**不写入 article**。
- article 的内容类型 `category`（open-source/paper-or-talk/article-or-news）由 **LLM 在 Analyze 阶段判定**（复用现有 HN 的 D1 模式）：RSS 内容多为文章/论文，通常判 `article-or-news` 或 `paper-or-talk`。

### D3. meta 字段集（RSS）
- `source=rss` 时 `meta` = `{feed_name, author, published}`：
  - `feed_name`：yaml 中的源 name（如 openai-blog）
  - `author`：条目作者（可为空字符串）
  - `published`：条目发布时间（ISO 8601 或原始串）
- 扩展 `schemas/article.schema.json` 的 meta 说明与 organizer 的 meta 字段集表。

### D4. RSS 解析用 stdlib ElementTree（非正则）
- 课程上一节提「简易正则解析」，但 RSS 2.0 与 Atom 两种格式 + XML 命名空间用正则脆弱；改用 stdlib `xml.etree.ElementTree`（**零新增解析依赖**），兼容 RSS `<item>` 与 Atom `<entry>`。

### D5. yaml 解析依赖 PyYAML
- 项目 `requirements.txt` 现仅 httpx，无 yaml 解析器。读 `rss_sources.yaml` 需 **新增 `pyyaml` 依赖**（标准、可靠，优于手写简易 yaml 解析）。

### D6. 限量策略
- RSS 采集对每个 enabled 源取**最新 limit 条**（默认 10，可被 `--limit` 覆盖）。arXiv 量大的前 10 需求由此统一满足，无需 per-source limit 字段（避免过度设计）。

## 3. rss_sources.yaml 结构（7 源，URL 来自实测研究）

字段：`name` / `url` / `category` / `enabled` + 可选 `note`（可用性备注，对课程 4 字段的合理扩展）。

```yaml
sources:
  - name: lobsters-ai
    url: https://lobste.rs/t/ai.rss
    category: general-tech
    enabled: true
    note: 官方 tag feed，实测可用；ml tag 是 OCaml 勿用
  - name: arxiv-cs-ai
    url: https://rss.arxiv.org/rss/cs.AI
    category: ai-research
    enabled: true
    note: 量大（单快照 400+ 条），采集截取最新 limit 条
  - name: openai-blog
    url: https://openai.com/blog/rss.xml
    category: company-blog
    enabled: true
    note: 官方，实测可用
  - name: anthropic-research
    url: https://rsshub.rssforever.com/anthropic/news
    category: company-blog
    enabled: false
    note: 官方无 RSS，依赖 RSSHub 公共实例稳定性
  - name: huggingface-blog
    url: https://huggingface.co/blog/feed.xml
    category: company-blog
    enabled: false
    note: 公认官方路径，本环境未实测连通，待部署环境验证
  - name: jiqizhixin
    url: ""
    category: chinese-community
    enabled: false
    note: 未找到可用官方 RSS（/rss 已失效为 SPA）
  - name: qbitai
    url: https://www.qbitai.com/feed
    category: chinese-community
    enabled: false
    note: 官方 WordPress feed 实测可用；遵循课程默认 disabled，可按需开
```

## 4. RSS 采集逻辑（pipeline.py 新增）

1. **读 yaml**：`yaml.safe_load` 载入 `rss_sources.yaml`，过滤 `enabled: true` 且 `url` 非空的源。
2. **逐源抓取**：httpx GET feed url，失败记 `errors-{date}.json`（网络/HTTP 非 2xx/解析失败，穷举式）。
3. **解析**：ElementTree 解析；RSS 2.0 取 `channel/item`，Atom 取 `{ns}entry`；按发布时间降序取前 `limit` 条。
4. **字段提取**（raw item）：

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `id` | `guid` 或 `link` | 源内唯一；兜底用 link |
| `title` | `title` | |
| `source` | 固定 `rss` | |
| `collected_at` | 采集时刻 | ISO 8601 |
| `url` | `link` | |
| `feed_name` | yaml name | 供 meta |
| `author` | `author`/`{dc}creator` | 可空 |
| `published` | `pubDate`/`{ns}published` | 可空 |
| `summary_raw` | `description`/`summary` | 供 LLM 分析参考 |

5. **幂等落盘**：`knowledge/raw/rss-{date}.json`，按 `id` 去重追加。

## 5. Analyze / Organize / Save 复用与适配

- **Analyze**：复用现有 LLM 分析；prompt 输入用 `title` + `summary_raw`（RSS 无 description 字段名统一，用 summary_raw）；`category` 由 LLM 判定为 3 枚举之一；GitHub 恒 open-source 的逻辑不受影响。
- **Organize**：四规则门控 + url 去重完全复用。
- **Save**：`build_article` 适配 `source=rss` → `meta={feed_name, author, published}`；article category 用 LLM 判定值；slug / index / _filtered 复用。

## 6. CLI

- `--sources` 增加 `rss` 取值：`--sources github,hn,rss`；`rss` 触发 RSS 采集路径（读取 yaml 的 enabled 源）。
- `--limit` 对 RSS 源表示每 feed 取最新 N 条（默认 10）。

## 7. schema 契约变更（schemas/article.schema.json）

- `source` 枚举：`["github-hot-repos", "hackernews-top"]` → 加 `"rss"`。
- `meta` description 补充 RSS 字段集说明。
- 注意：改 schema 会影响 `hooks/validate_json.py` 的校验基准（schema 是单一事实来源，改这里即生效，无需改校验代码）。

## 8. 错误处理 / 幂等 / 门控

- 复用穷举式 errors：feed 抓取失败 / XML 解析失败 / 必填字段缺失（id/title/url）均记 `errors-{date}.json`，单源/单条失败跳过不中断。
- raw 按 `id` 去重；article 按 `url` 去重（RSS 条目的 link 与 GitHub/HN 不冲突）。
- 门控四规则不变。

## 9. 依赖与兼容

- 新增依赖：`pyyaml`（加入 `requirements.txt`）。
- 不改 `model_client.py`；不改现有 GitHub/HN 采集路径；不改 `.opencode/`。
- 新增文件：`pipeline/rss_sources.yaml`；修改文件：`pipeline/pipeline.py`、`schemas/article.schema.json`、`requirements.txt`。

## 10. 风险与缓解

- **机器之心无可用 RSS**：url 留空 + enabled:false + note 注明，采集时跳过空 url 源。
- **Anthropic/HuggingFace 依赖第三方或未实测**：默认 enabled:false，采集逻辑对失败源记 errors 不中断。
- **RSS 时间格式不一**（RFC 822 vs ISO）：published 保留原始串，解析失败留空不阻断。
- **Atom 命名空间**：ElementTree 用通配命名空间 `{*}entry` 兼容。
