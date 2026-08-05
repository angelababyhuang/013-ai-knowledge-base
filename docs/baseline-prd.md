# AI 知识库助手 —— 已实现功能基线 PRD

- **文档性质**：存量项目**逆向梳理**产物，固化"当前已实现什么"的现状基线。
- **生成方式**：只读扫描全部源码 / 配置 / 契约 / 数据资产后整理，未修改任何现有代码与数据。
- **覆盖范围**：架构编排、Collector 采集、Analyzer 分析、Organizer 整理、契约与校验、LLM 基础设施、决策与测试记录、数据资产；附录为差距与漂移清单。
- **层次**：业务流程 + 关键代码实现两层并行。

> 说明：本文描述的是"已实现的现状"，不是未来规划。附录中的差距清单仅记录"声明但未实现 / 与实现不符"的漂移点，不构成实现承诺。

---

## 1. 项目概述

AI 知识库助手：自动从 GitHub 热门仓库与 Hacker News 采集 AI/LLM/Agent 领域技术动态，经 LLM 分析（摘要 / 打标签 / 相关性评分）后结构化存储为 JSON 知识条目，供下游应用消费。

核心实现是一条**三阶段单向流水线**，由三层 Agent 架构驱动，产出统一 JSON 知识条目。

---

## 2. 架构与编排

**来源**：`AGENTS.md`、`.opencode/agents/{collector,analyzer,organizer}.md`

### 2.1 三层 Agent 架构

```
主 Agent（编排器）
   │  @collector / @analyzer / @organizer（@ 语法调用）
   ▼
Subagent（角色载体：权限 / 目录边界 / 跨源约定）
   │  识别数据源或分析任务 → 触发对应 skill
   ▼
Skill（procedure：具体怎么采 / 怎么分析）
```

- **角色（`.opencode/agents/*.md`）**：定义权限、目录边界、跨源约定（errors 策略 / 文件命名 / JSON 格式 / 幂等）。
- **procedure（`.opencode/skills/*/SKILL.md`）**：某数据源的采集步骤或分析步骤，是该领域的单一事实来源。
- 角色与 procedure **分离**：agent 文件不重述源细节，skill 文件不重述角色边界，避免 spec 多处抄写漂移。

### 2.2 三阶段单向数据流

```
[collector] ──采集──▶ knowledge/raw/        （collector 写，他人只读）
[analyzer]  ──分析──▶ knowledge/enriched/   （读 raw/，写 enriched/）
[organizer] ──整理──▶ knowledge/articles/   （读 enriched/，写 articles/）
```

**协作规则**（`AGENTS.md`）：
1. 单向数据流，不可反向回写。
2. 职责隔离，每个 Agent 只写自己的目录。
3. 幂等：同一天重复运行不产生重复条目。
4. 质量门控：`relevance_score < 0.6` / 摘要 < 50 字 / tags < 2 / url 异常的条目被 Organizer 丢弃。
5. 可追溯：每条保留 `url` / `source` / `collected_at`。

### 2.3 各角色权限边界

| 角色 | 允许工具 | 写目录 | 禁止 |
| --- | --- | --- | --- |
| collector | Read/Grep/Glob/WebFetch/Bash/Write | `knowledge/raw/` | 碰 enriched/、articles/ |
| analyzer | Read/Grep/Glob/WebFetch/Write | `knowledge/enriched/` | Edit、Bash；raw 只读、articles 不碰 |
| organizer | Read/Grep/Glob/Write/Edit | `knowledge/articles/` | WebFetch、Bash（纯本地加工）；raw/enriched 只读 |

---

## 3. Collector 采集层

**来源**：`.opencode/agents/collector.md`、`.opencode/skills/github-hot-repos/SKILL.md`、`.opencode/skills/hackernews-top/SKILL.md`

Collector 是跨源采集的角色载体；每个数据源的采集 procedure 由对应 skill 承载。collector.md 内置**数据源路由**：识别 `github-hot-repos` / `hackernews-top` 时转交对应 skill。

### 3.1 GitHub 热门仓库（github-hot-repos skill）

业务流程：
1. **构建查询**：`GET https://api.github.com/search/repositories`，关键词 `AI OR LLM OR agent OR "large language model" OR RAG OR MCP`，`sort=stars&order=desc&per_page=20`，时间窗口过去 7 天。
2. **认证请求**：请求头 `Accept: application/vnd.github.v3+json` + `Authorization: Bearer $GITHUB_TOKEN`（未认证 60 次/小时，认证 5000 次/小时，必须带 token）。
3. **限流处理**：403/429 时读 `X-RateLimit-Reset` 等待，最多重试 3 次。
4. **字段提取**：`id=full_name`、`title=name`、`source=github-hot-repos`、`collected_at`、`description`、`url=html_url`、`stars=stargazers_count`、`language`、`topics`、`created_at`、`updated_at=pushed_at`。GitHub 源**隐含** `category=open-source`（不存 raw，organizer 落盘时统一补）。
5. **幂等落盘**：`knowledge/raw/github-hot-repos-{date}.json`，按 `id` 去重追加，不覆盖。

### 3.2 Hacker News 热门（hackernews-top skill）

业务流程：
1. **取 Top Stories ID**：`https://hacker-news.firebaseio.com/v0/topstories.json`，前 50 个。
2. **逐条取详情**：`.../item/{id}.json`。
3. **关键词过滤**：保留标题含 AI/LLM/Agent/GPT/Claude/model 等关键词，并主动剔除语义误命中（如 MRI 硬件、pre-ai 词汇）。
4. **分层筛选**：首轮仅留 `open-source` 类（url 指向 github/gitlab/bitbucket）；若不足 K（用户指令给定，默认 10），放宽到 AI 主题按 `score` 降序补足；放宽部分按内容归入 `paper-or-talk` / `article-or-news`。仍不足则如实交付，不凑数。
5. **URL 回填**：`url` 为 null（Ask HN / 纯文本帖）时回填 `https://news.ycombinator.com/item?id={id}`。
6. **字段提取**：`id`、`title`、`source=hackernews-top`、`collected_at`、`url`、`score`、`comments=descendants`、`author=by`、`time`、`category`（agent 人工判定，3 枚举，不可仅凭 url 启发式推断）。
7. **幂等落盘**：`knowledge/raw/hackernews-top-{date}.json`，按 `id` 去重追加。

### 3.3 错误产物（穷举式，无自由裁量）

凡 agent 发起的 HTTP 请求失败，一律跳过该条目并把失败记录追加写入 `knowledge/raw/errors-{date}.json`。**触发条件（任一即记入，不论核心/扩展批次）**：
- 网络层失败（DNS / TCP / TLS / 超时）
- HTTP 非 2xx（4xx 含 401/403/404/429、5xx）
- 限流耗尽（重试 3 次仍 403/429）
- 响应解析失败
- 必填字段缺失（`id` / `title` / `url`）

记录格式：`{source, url, error, timestamp}`，文件已存在则读取后追加（幂等不覆盖）。

---

## 4. Analyzer 分析层

**来源**：`.opencode/agents/analyzer.md`、`.opencode/skills/tech-summary/SKILL.md`

Analyzer 是跨源分析的角色载体；分析 procedure 由 `tech-summary` skill 承载（GitHub 与 HN 源通用）。输入 `knowledge/raw/{source}-{date}.json`，输出 `knowledge/enriched/{source}-{date}.enriched.json`。

### 4.1 分析字段（每个 item 补 4 个）

| 字段 | 说明 |
| --- | --- |
| `summary` | 中文摘要，2-3 句，说清"是什么 / 解决什么问题 / 为什么值得看"，不照搬 description，含信息增量 |
| `tags` | 英文 kebab-case 标签，3-5 个（全小写、连字符、无中文无空格） |
| `relevance_score` | 相关性评分 0.00-1.00，五维加权平均，两位小数 |
| `score_breakdown` | 五维评分明细，留作审计底稿（不进 article） |

### 4.2 五维加权评分

| 维度 | 字段 | 权重 | 评分标准 |
| --- | --- | --- | --- |
| 技术深度 | `tech_depth` | 0.25 | 底层原理 / 架构设计 / 算法创新 |
| 实用价值 | `practical_value` | 0.30 | 工程师能否直接用于项目 |
| 时效性 | `timeliness` | 0.20 | 是否最新趋势 / 近期发布 |
| 社区热度 | `community_heat` | 0.15 | Stars / Score / 评论数 |
| 领域匹配 | `domain_match` | 0.10 | 与 AI/LLM/Agent 核心领域匹配度 |

公式：`relevance_score = tech_depth*0.25 + practical_value*0.30 + timeliness*0.20 + community_heat*0.15 + domain_match*0.10`。要求评分客观、跨条目横向比较有梯度。

### 4.3 category 维度上限（硬约束）

| category | 维度上限 |
| --- | --- |
| `open-source` | 不限 |
| `paper-or-talk` | `practical_value ≤ 0.5` |
| `article-or-news` | `tech_depth ≤ 0.5 且 practical_value ≤ 0.3` |

- HN 源按自带 `category` 检查；GitHub 源隐含 `open-source` 不受约束。
- 设计意图：避免"Stanford 报告"与"GitHub 项目"评分趋同，契合"知识库偏向技术资源"定位。

### 4.4 灰色地带 `_override`

遇到灰色地带（如 article 实际含可运行代码 + repo 链接），可在 `score_breakdown._override` 中说明突破上限的维度与理由；实际分数按突破后的值参与加权，未写 `_override` 的维度视为遵守上限。

### 4.5 落盘与幂等

enriched 结构 = raw 结构 + 每 item 增补 4 分析字段，顶层 `analyzed_at`；collector 原始字段逐字段不篡改；当天文件已存在按 `id` 覆盖分析字段，不重复追加。`relevance_score < 0.6` 的条目仍保留分析结果，由 organizer 决定是否丢弃。

---

## 5. Organizer 整理层

**来源**：`.opencode/agents/organizer.md`

Organizer 读 enriched/，执行门控与去重，格式化为标准知识条目，分类存盘并维护索引。纯本地加工（禁 WebFetch / Bash）。

### 5.1 四规则质量门控（命中任一即丢弃）

| 规则 | 动作 |
| --- | --- |
| `relevance_score < 0.6` | 丢弃 |
| `summary` 少于 50 字 | 丢弃 |
| `tags` 少于 2 个 | 丢弃 |
| `url` 格式异常 | 丢弃 |

`category` 与 `meta` **不参与门控**（门控只看 relevance_score / summary / tags / url）。

### 5.2 去重

- 精确去重以 `url` 为键，跨天比对 articles/ 已有条目。
- 标题高度相似（同项目不同表述 / 镜像 / fork）时软判断跳过并记日志（无 Bash，不设程序化相似度阈值）。

### 5.3 标准知识条目（12 字段 = 10 核心 + 2 增强）

| 字段 | 来源 |
| --- | --- |
| `id` | collector（GitHub 用 full_name，HN 用数字 id） |
| `title` / `source` / `url` / `collected_at` | collector |
| `category` | collector（HN 必填）/ organizer 补（GitHub 一律 open-source） |
| `analyzed_at` / `summary` / `tags` / `relevance_score` | analyzer |
| `organized_at` | organizer |
| `meta` | organizer 透传（始终为 dict，可空 `{}`） |

`meta` 跨源字段集：HN=`author`/`comments`/`time`；GitHub=`stars`/`language`/`topics`/`pushed_at`。`score_breakdown` 不进 article，留 enriched/ 作审计底稿。

### 5.4 落盘 / 索引 / 过滤日志

- 单条：`knowledge/articles/{YYYY-MM-DD}-{source}-{slug}.json`（slug 由 title 小写化、空格与 `/` 转连字符、去停用词；source 段作命名空间防撞车）。
- 索引：`knowledge/articles/index.json`，顶层 `updated_at` / `total_count` / `articles[]`（9 字段含 url + category，按 `organized_at` 降序）。
- 过滤日志：`knowledge/articles/_filtered-{date}.json`（下划线前缀区分正式条目），记录 `{url, source, reason, ...}`；`reason` 取值含 `relevance_score < 0.6` / `summary too short` / `tags too few` / `url invalid` / `duplicate url` / `duplicate title (similar)` / `incomplete: missing field <字段>`。

---

## 6. 契约与校验

**来源**：`schemas/article.schema.json`、`schemas/quality-rubric.json`、`hooks/validate_json.py`、`hooks/check_quality.py`

### 6.1 字段契约（article.schema.json）

12 字段知识条目的**单一事实来源**（标准 JSON Schema draft 2020-12）。`additionalProperties: false`（拒绝未声明字段，防 score_breakdown 泄漏）。关键约束：
- `source` 枚举：`github-hot-repos` / `hackernews-top`
- `category` 枚举：`open-source` / `paper-or-talk` / `article-or-news`
- `url` 必须 `^https://`
- `tags` 元素 `^[a-z0-9]+(-[a-z0-9]+)*$`（kebab-case）
- `relevance_score` ∈ [0,1]，number 不接受 bool
- `summary` minLength 20（格式下限；门控实际要求 50）

字段增删只改此 schema，校验器据此加载，代码不重抄（避免漂移）。

### 6.2 结构校验器（validate_json.py）

- **schema 驱动**：内置零第三方依赖的 JSON Schema 子集解释器（type/enum/pattern/minLength/minItems/items/minimum/maximum/required/properties/additionalProperties），加载 article.schema.json 校验。
- **业务规则（代码层，schema 无法表达的跨字段约束）**：`source↔id` 对应（GitHub 须 `owner/repo`、HN 须纯数字）；`relevance_score ≥ 0.6` 门控（articles/ 不应出现低分条目）。
- 兼容单条 / items[] / 数组三种形态；退出码 0（全过）/ 1（有错误）/ 2（用法或 schema 加载错误）。

### 6.3 质量评分契约（quality-rubric.json）

5 维质量评分的**单一事实来源**，满分 100，等级 A≥80 / B≥60 / C<60：
- 摘要质量（25）：按长度分档 + 中英文技术关键词命中加成
- 技术深度（25）：`relevance_score × 25` 线性映射
- 格式规范（20）：5 字段各 4 分（id/title/source 非空、url 须 https、category 非空）
- 标签精度（15）：标准词表命中（数据驱动，取项目出现≥2 次高频标签）+ 格式加成
- 空洞词检测（15）：中英文黑名单（赋能/抓手/闭环、groundbreaking/revolutionary 等）命中扣分

### 6.4 质量评分器（check_quality.py）

- **rubric 驱动**：加载 quality-rubric.json，代码不硬编码阈值/词表/权重；按维度 type 分派到 5 个评分函数。
- 兼容单条 / items[] / 数组；可视化输出（进度条 + 明细）；存在 C 级条目或评分失败 → exit 1。

> validate_json.py 是**结构契约**校验，check_quality.py 是 organizer 行为门控的**事后确定性复核**，二者互补。

---

## 7. LLM 基础设施

**来源**：`pipeline/model_client.py`、`pipeline/__init__.py`、`requirements.txt`

统一 LLM 调用客户端，封装 DeepSeek / Qwen / OpenAI 三家（均兼容 OpenAI Chat Completions 协议），底层复用同一 `OpenAICompatibleProvider`，仅 base_url / 默认模型 / 计价不同；新增 provider 只需在 `PROVIDER_CONFIGS` 加一条配置。

实现要点：
- **provider 抽象**：`LLMProvider` 抽象基类（`chat()`）+ `OpenAICompatibleProvider` 实现；`create_provider()` 工厂按 `LLM_PROVIDER`（默认 `deepseek`）构造。
- **API key 回退**：先读 provider 专属变量（`DEEPSEEK_API_KEY` / `QWEN_API_KEY` / `OPENAI_API_KEY`），缺失回退统一 `LLM_API_KEY`，都没有则 `RuntimeError`。
- **重试**：`chat_with_retry()` 对连接错误 / 超时 / 429 / 5xx 按 `BACKOFF_BASE * 2**attempt` 指数退避，最多 3 次。
- **用量与成本**：`Usage` dataclass 统计 token；`estimate_cost()` 按 provider 计价表（每百万 token USD 单价）估算成本。
- **便捷入口**：`quick_chat(prompt)` 一句话调用返回文本。
- 依赖：`httpx>=0.27`（唯一第三方依赖）。

---

## 8. 决策与测试记录

**来源**：`docs/decisions/2026-07-25-analyzer-organizer-course-alignment.md`、`docs/decisions/2026-07-27-pipeline-spec-hardening.md`、`sub-agent-test-log.md`

### 8.1 ADR-0001（2026-07-25，课程对齐）

对齐课程版 analyzer/organizer 设计的 9 条决策：评分改 0-1 五维加权 + score_breakdown；门控四规则放 organizer；摘要 100-200 字规格；去重改 url 精确 + 软标题判断；过滤日志放 articles/；article 8→10 字段；index.json 结构；analyzed_at 改 per-item；文件名保留 `{source}` 段。锁定前提：enriched/ 落盘层保留、沿用源 id（不引入 kb-id）。

### 8.2 PRD-0002（2026-07-27，流水线规范硬化）

第一轮端到端测试发现 5 类问题的固化：collector 错误记录改穷举式无裁量；HN 流程加分层筛选 + 放宽且强制 category；analyzer 按 category 设维度上限 + `_override`；index.json 7→9 字段（加 url + category）；article 10→12 字段（加 category + meta）。含 Testing Decisions（Seam A 端到端 / Seam B 错误边界）与历史数据不回填策略。

### 8.3 sub-agent-test-log.md（2026-07-27）

完整三阶段流水线端到端测试（HN 源）：collector 采集 6 条、analyzer 评分梯度 0.30-0.81、organizer 门控丢 3 条 < 0.6。验证了角色边界、字段契约、质量门控、幂等均生效；其 5 项调整建议已通过 PRD-0002 落地。

---

## 9. 数据资产

**来源**：`knowledge/raw/`、`knowledge/enriched/`、`knowledge/articles/`

- **raw/**：github-hot-repos 与 hackernews-top 多日原始数据（07-25 ~ 07-30），含 `errors-{date}.json` 错误记录与 `-verify` 验证产物。
- **enriched/**：github 与 hn 多日 `.enriched.json`（含 summary/tags/relevance_score/score_breakdown）。
- **articles/**：数十条标准知识条目（12 字段，含 category + meta），`index.json` 索引，`_filtered-{date}.json` 过滤日志。

文件命名遵循契约：raw=`{source}-{date}.json`、enriched=`{source}-{date}.enriched.json`、article=`{date}-{source}-{slug}.json`、索引=`index.json`。

---

## 附录 A：差距与漂移清单（声明但未实现 / 与实现不符）

> 本节仅记录现状漂移，不构成实现承诺。

| # | 项 | AGENTS.md / spec 声明 | 实际现状 |
| --- | --- | --- | --- |
| A1 | Telegram / 飞书 Bot 多通道分发 | 项目概述提及"通过 Telegram / 飞书 Bot 多通道分发" | **完全未实现**：无对应代码 / 配置 / skill / 文档 |
| A2 | README.md | 项目结构列出 `README.md 使用说明` | **文件不存在** |
| A3 | .env.example | 项目结构列出 `.env.example 环境变量模板` | **文件不存在**（.gitignore 已忽略 `.env`，但无模板） |
| A4 | 大模型提供方 | 技术栈写"LLM(minimax)" | `pipeline/model_client.py` 实际配置 **DeepSeek / Qwen / OpenAI**，无 minimax |
| A5 | "国产大模型" | 核心价值提"通过国产大模型分析" | model_client 含国产（DeepSeek/Qwen）**及** OpenAI，与"国产"表述不完全一致 |

### 备注

- A1（分发层）在 PRD-0002 的 Out of Scope 中已明确"本 PRD 只覆盖数据流水线硬化，不涉及分发层"，属已知未实现项。
- A2 / A3 为 spec 文档与文件系统的漂移，建议补写或从 AGENTS.md 项目结构中移除。
- A4 / A5 为 AGENTS.md 技术栈描述与 pipeline 实际 provider 的不一致，建议统一表述。

---

*本基线 PRD 由只读逆向梳理生成，反映当前已实现现状。后续功能演进请以本文为基线对照。*
