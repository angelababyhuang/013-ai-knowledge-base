# 技术设计：pipeline/pipeline.py 四步流水线

## 1. 总体形态

- **单文件** `pipeline/pipeline.py`（课程指定），内部按四步分区组织函数。
- 与 `pipeline/model_client.py` 同目录，`from model_client import create_provider, chat_with_retry`。
- 复用项目契约：产出严格对齐 `schemas/article.schema.json`（12 字段）与 organizer 的命名/门控/index 规则。
- 数据流（与现有三阶段架构一致）：

```
CLI args
  └─ Step1 Collect   按 --sources 采 github/hn ──▶ knowledge/raw/{source}-{date}.json
  └─ Step2 Analyze   每条 raw item 调 LLM      ──▶ knowledge/enriched/{source}-{date}.enriched.json
  └─ Step3 Organize  门控四规则 + url 去重      ──▶ 通过集 / 丢弃集
  └─ Step4 Save      12 字段格式化 + 索引       ──▶ knowledge/articles/{date}-{source}-{slug}.json
                                                   + index.json + _filtered-{date}.json
```

## 2. CLI 设计（argparse）

| 参数 | 取值 | 默认 | 说明 |
| --- | --- | --- | --- |
| `--sources` | 逗号分隔 `github` / `hn` | `github,hn` | 映射 `github→github-hot-repos`、`hn→hackernews-top` |
| `--limit` | int | GitHub 20 / HN 10 | 每源采集条数上限（GitHub→per_page；HN→分层筛选 K） |
| `--dry-run` | flag | False | 采集+分析照常，**不落任何文件**，仅打印将执行的操作与条目摘要 |
| `--verbose` | flag | False | DEBUG 级日志（默认 INFO） |

示例对齐课程：`--sources github,hn --limit 20` / `--sources github --limit 5` / `--sources hn --limit 10` / `--dry-run` / `--verbose`（课程里的 `rss` 替换为 `hn`）。

## 3. Step 1 Collect（httpx）

复刻两个采集 skill 的查询参数与字段提取表，翻译为 Python。

### 3.1 GitHub（github-hot-repos）
- `GET https://api.github.com/search/repositories?q=AI+OR+LLM+OR+agent+OR+"large+language+model"+OR+RAG+OR+MCP&sort=stars&order=desc&per_page={limit}`
- 请求头 `Accept: application/vnd.github.v3+json` + `Authorization: Bearer $GITHUB_TOKEN`（无 token 时警告，未认证限额 60/h）。
- 限流：403/429 读 `X-RateLimit-Reset` 等待重试，≤3 次。
- 字段映射：`id=full_name, title=name, source=github-hot-repos, collected_at, description, url=html_url, stars=stargazers_count, language, topics, created_at, updated_at=pushed_at`。`category` 不存（GitHub 隐含 open-source，Save 阶段补）。

### 3.2 HN（hackernews-top）
- `GET topstories.json` 取前 50 ID → 逐条 `GET item/{id}.json`。
- 关键词过滤（AI/LLM/Agent/GPT/Claude/model 等）。
- 分层筛选：open-source 优先（url 指向 github/gitlab/bitbucket），不足 `limit` 放宽到 AI 主题按 score 降序补足；放宽项标 paper-or-talk / article-or-news。
- URL 回填：`url` 为 null → `https://news.ycombinator.com/item?id={id}`。
- 字段映射：`id, title, source=hackernews-top, collected_at, url, score, comments=descendants, author=by, time, category`。

### 3.3 HN category 判定（设计决策 D1）
- 项目在 LLM 流程里是「agent 人工判定，不可仅凭 url 启发式」。Python 一体化 Pipeline 中，**category 移交 Step 2 由 LLM 判定**（连同摘要/评分/标签一次调用输出），比 url 启发式更准，且对齐「语义判定」精神。
- Step 1 仅做分层筛选的**初步归集**（open-source 候选 vs AI 主题候选），最终 category 以 LLM 判定为准；GitHub 恒 open-source。

### 3.4 幂等落盘
- 当天 raw 文件已存在：读取后按 `id` 去重追加，不覆盖。
- 顶层 `count` 与 `items` 长度一致。

## 4. Step 2 Analyze（model_client）

### 4.1 LLM 调用
- `provider = create_provider()`（读 `LLM_PROVIDER`，默认 deepseek；key 回退 `LLM_API_KEY`）。
- 对每个 raw item 调 `chat_with_retry(provider, messages)`。
- prompt 要求 LLM **只返回一个 JSON 对象**，字段：
  ```json
  {
    "summary": "中文摘要 2-3 句（100-200 字，含信息增量）",
    "tags": ["kebab-case", "3-5 个"],
    "category": "open-source | paper-or-talk | article-or-news（仅 HN；GitHub 可省略）",
    "tech_depth": 0.0, "practical_value": 0.0, "timeliness": 0.0,
    "community_heat": 0.0, "domain_match": 0.0
  }
  ```
- 输入上下文：title / description(GitHub) 或 title+url(HN) / stars|score / topics 等 raw 字段。

### 4.2 解析与评分
- 从 LLM 返回文本提取 JSON（容忍 ```json 代码块包裹），`json.loads`。
- 计算 `relevance_score = tech_depth*0.25 + practical_value*0.30 + timeliness*0.20 + community_heat*0.15 + domain_match*0.10`，round 两位。
- **category 上限**：paper-or-talk → practical_value≤0.5；article-or-news → tech_depth≤0.5 且 practical_value≤0.3；超限截断并记 `score_breakdown._override` 说明。
- 产出 `score_breakdown`（五维明细 + 可选 `_override`）。

### 4.3 落盘 enriched
- 结构 = raw 结构 + 每 item 增补 `summary/tags/relevance_score/score_breakdown/category`，顶层 `analyzed_at`。
- collector 原始字段不篡改；当天已存在按 `id` 覆盖分析字段。

## 5. Step 3 Organize（门控 + 去重）

- **四规则门控**（命中任一即丢弃）：`relevance_score<0.6` / `summary<50字` / `tags<2` / url 非 `https://` 开头。`category`/`meta` 不参与门控。
- **去重**：以 `url` 为键，比对 `knowledge/articles/` 存量（经 index.json 或扫描）；重复丢弃并记 `duplicate url`。

## 6. Step 4 Save

- **12 字段 article**：collector 字段 + analyzer 字段 + `organized_at` + `category`（GitHub 补 open-source；HN 用 LLM 判定值）+ `meta`（GitHub: stars/language/topics/pushed_at；HN: author/comments/time）。
- **slug**：title 小写、空格与 `/` 转连字符、去停用词。
- 落盘 `knowledge/articles/{date}-{source}-{slug}.json`。
- **index.json**：9 字段（id/title/source/url/category/file/tags/relevance_score/organized_at），按 organized_at 降序，`total_count` 与实际一致。
- **_filtered-{date}.json**：记录丢弃项 `{url, source, reason, ...}`。
- **errors-{date}.json**：采集/分析/解析任一失败穷举记录。

## 7. 校验（设计决策 D2）

- Save 完成后（非 dry-run），用 `subprocess` 调 `python hooks/validate_json.py <当日新 article...>` 做事后结构校验；失败打印警告但不中断（审计提示）。
- 可选 `--no-validate` 跳过。

## 8. dry-run 语义（设计决策 D3）

- 采集照常（需网络 + token），分析照常（需 LLM key），**全程不写任何文件**。
- 结尾打印：采集到 N 条、分析后 M 条过门控、将写入的文件名清单。
- 理由：让用户在消耗 LLM 配额前预览产出质量，又不污染 knowledge/。

## 9. 错误处理（穷举，对齐 collector 契约）

任一即记 `errors-{date}.json`：网络层失败 / HTTP 非 2xx / 限流耗尽 / 响应解析失败 / 必填字段缺失 / LLM 调用或返回 JSON 解析失败。单条失败跳过，不中断整体。

## 10. 关键取舍

- **单文件 vs 包**：遵课程用单文件；若后续超 ~600 行可再拆 `pipeline/` 子模块。
- **category 由 LLM 判定（D1）**：牺牲一次 LLM 调用换判定准确性，对齐项目「语义判定」要求；比 url 启发式更不易误判「博客讲 GitHub 项目」边界。
- **校验用 subprocess 调 hooks（D2）**：hooks 不在 pipeline/ 包内，subprocess 解耦，避免复制 schema 逻辑造成漂移。

## 11. 兼容 / 迁移

- 不改 `model_client.py`、不改 `.opencode/`、不改 schemas/hooks。
- 新增文件仅 `pipeline/pipeline.py`；产出写入现有 knowledge/ 目录，与既有数据资产同构。
