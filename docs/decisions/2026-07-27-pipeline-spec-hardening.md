# PRD-0002: AI Knowledge Base 流水线规范硬化（第一轮）

- **日期**：2026-07-27
- **状态**：ready-for-agent（已落地、待回归 / 持续观察）
- **来源**：`sub-agent-test-log.md` 的 5 项调整建议 → `grill-me` 多轮决议 → 实际改动 + 复测
- **关联 ADR**：ADR-0001（2026-07-25，analyzer / organizer 课程对齐）

## Problem Statement

AI 知识库助手流水线的第一轮端到端测试发现 5 类规范问题，影响信号的可靠性与下游消费的便利度：

1. **Collector 错误记录不可靠**：测试中 collector 自行把扩展扫描批次（51-100 名）定义为"非核心、可选"，并据此豁免 errors 文件记录，导致失败未被审计。
2. **HN 数据源覆盖不足**：用户指令"Top 10 AI 开源项目"在 HN 实际生态中只能凑齐 1 条真·开源项目，agent 当时仅如实返回 6 条，交付量与期望落差大且定义模糊。
3. **Analyzer 评分未差异化**：HN 来源天然混合"开源仓库 / 论文演讲 / 资讯文章"三类，旧规范用一套权重评分会让 Stanford 报告与 GitHub 项目评分趋同，违背"知识库偏向技术资源"的定位。
4. **index.json 缺关键字段**：每条索引项只 7 字段，缺 `url` 与 `category`，下游需打开 article 单文件才能跳转或按类别过滤。
5. **源特有证据未沉淀**：HN 的 `author` / `comments` / `time`，GitHub 的 `stars` / `language` / `topics` / `pushed_at` 在 organizer 阶段被丢弃，下游想做"按 stars 排行"或"按作者聚合"必须重采。

## Solution

通过**规范层 4 个文档**（`collector.md` / `analyzer.md` / `organizer.md` / `AGENTS.md`）的精确调整，把 5 类问题固化为可执行契约：

- Collector 的错误记录改为"穷举触发 + 无自由裁量"
- HN 流程改为"分层筛选 + 放宽规则"且每条 item 强制带 `category`
- Analyzer 按 `category` 设维度上限，灰色地带用 `_override` 字段说明
- Organizer 输出 article 时透传 `category` + 沉淀 `meta` dict
- index.json 索引项扩展为 9 字段（含 `url` + `category`）

约束：
- **单向数据流**不变：collector → analyzer → organizer
- **目录边界**不变：每阶段只写自己的目录
- **质量门控**规则不变（`< 0.6` / 摘要 / tags / url 四规则）
- **历史数据不追溯**：本轮不补 `category` 给历史 raw（一次性验证标注除外）

## User Stories

1. As 主 Agent 编排器, I want 每个 sub-agent 只写自己的目录, so that 三阶段流水线边界清晰、可独立 dispatch 与调试。
2. As 开发者, I want collector 自动记录**所有** HTTP 失败（含核心与扩展批次）, so that 排查网络问题时不会因 agent 自作主张豁免而遗漏失败样本。
3. As 开发者, I want collector 的 errors 触发条件是**穷举清单**（网络层 / HTTP 非 2xx / 限流耗尽 / 解析失败 / 字段缺失）, so that agent 没有自由裁量空间、不会以"扩展扫描"等理由漏报。
4. As 开发者, I want HN 采集在开源项目不足 K 条时**自动放宽**到 AI 主题（含文章 / 演讲 / 政策）, so that 交付量稳定、不凑不齐就报零，但放宽行为有明确语义而非静默填补。
5. As analyzer, I want 知道每条 HN 数据的 `category`（`open-source` / `paper-or-talk` / `article-or-news`）, so that 按类别应用不同评分策略，避免"Stanford 报告"与"GitHub 项目"评分趋同。
6. As analyzer, I want 对不同 category 设定**维度上限**：
   - `open-source` 不限
   - `paper-or-talk` 的 `practical_value ≤ 0.5`
   - `article-or-news` 的 `tech_depth ≤ 0.5` 且 `practical_value ≤ 0.3`
   so that 仓库类项目的工程实用价值得到充分体现，资讯类不会被拔高到与代码项目同档。
7. As analyzer, I want 在 `score_breakdown` 中可加 `_override` 字段说明突破上限的理由, so that 灰色地带（article 含可运行代码、paper 偏应用）有合规的突破路径而不被上限误伤。
8. As 下游消费者, I want `index.json` 每条含 `url` + `category`, so that 可直接跳原文、按类别过滤，无需打开 article 单文件。
9. As 下游消费者, I want article 含 `meta` dict：
   - HN 源：`author` / `comments` / `time`
   - GitHub 源：`stars` / `language` / `topics` / `pushed_at`
   so that 社区热度证据（HN 评论数、GitHub stars）可在不重采的情况下查询。
10. As 开发者, I want `category` 与 `meta` **不参与门控**（门控只看 `relevance_score` / `summary` / `tags` / `url`）, so that 评分逻辑不被外围字段污染，过滤日志也只记核心门控原因。
11. As 开发者, I want **12 字段契约**（10 核心 + 2 增强：`category` 与 `meta`）固化在 `organizer.md` + `AGENTS.md`, so that 下游对接有稳定 schema，避免不同消费者对字段集理解不一致。
12. As 调试者, I want 验证 #1 错误记录时能用 mock 失败端点（5xx + DNS 不存在的域名）复测, so that 不依赖生产环境的真实失败、可重复触发。
13. As 维护者, I want GitHub 源隐含 `category = open-source` 而不显式存储, so that GitHub schema 不被多余字段污染。
14. As 维护者, I want GitHub 源 article 的 `meta` 为空 dict `{}` 而非省略字段, so that 字段位置统一（不是"有时有 meta，有时没有"），下游可一致地用 `meta.get(...)` 取值。
15. As 端到端流水线使用者, I want 一次 dispatch 即可验证所有契约（除 #1 外）, so that 主 Agent 编排流水线健康检查时不需要分多条 sub-task。
16. As 项目维护者, I want 本轮所有改动汇总在 PRD + 改动后的 .md 中, so that 后续 agent 接手时不会因 spec 演进而迷茫、且可按本 PRD 复现/回归。

## Implementation Decisions

### D1. 模块与文档改动（4 个 .md）
| 文件 | 依据 |
| --- | --- |
| `.opencode/agents/collector.md` | #1 错误产物节改"穷举式 + 无裁量"；#2 HN 流程加"分层筛选 + 放宽"；HN item 加 `category` 必填字段；输出格式加 HN 示例；质量清单加 category 与 errors 全量校验 |
| `.opencode/agents/analyzer.md` | #3 加 category-based 上限表 + `_override` 灰色地带机制；质量清单加 category 校验；注意事项加"按 category 应用上限" |
| `.opencode/agents/organizer.md` | #4 index 7 → 9 字段（加 `url` + `category`）；#5 article 10 → 12 字段（加 `category` + `meta` dict）；`meta` 跨源字段集；质量清单更新 |
| `AGENTS.md` | 字段归属表 10 → 12 字段契约（10 核心 + 2 增强），明示 `category` / `meta` 不参与门控 |

### D2. HN 原始 item 新增 `category` 字段（3 枚举）
```json
{
  "category": "open-source" | "paper-or-talk" | "article-or-news"
}
```
- 强制 agent 人工判定（不可从 url 启发式推断，避免"博客讲 GitHub 项目"边界错判）
- GitHub 源不显式存储 `category`（隐含 `open-source`），由 organizer 落盘时统一加 `category: "open-source"`

### D3. Collector 错误记录规则（穷举式）
触发条件（任一即记入 `raw/errors-{date}.json`）：
- 网络层失败（DNS / TCP / TLS / 超时）
- HTTP 非 2xx（4xx / 5xx）
- 限流耗尽（重试 3 次仍 403/429）
- 响应解析失败
- 必填字段缺失（`id` / `title` / `url`）

**不允许 agent 以"非核心批次 / 扩展扫描"等理由豁免**——此条为硬规则，无解释空间。

### D4. Analyzer 维度上限（按 category）
```text
open-source:       不限
paper-or-talk:     practical_value ≤ 0.5
article-or-news:   tech_depth ≤ 0.5 且 practical_value ≤ 0.3
```

`_override` 机制（灰色地带）：
```json
{
  "tech_depth": 0.45,
  "practical_value": 0.85,
  "timeliness": 0.7,
  "community_heat": 0.4,
  "domain_match": 0.9,
  "_override": {
    "practical_value": "内含 GitHub repo + Colab notebook，按 open-source 类实际可跑"
  }
}
```
- `_override` 只记录"哪一维突破 + 理由"
- 实际分数仍按突破后的值参与 `relevance_score` 加权
- 不写 `_override` 的维度视为遵守上限

### D5. article 字段契约（12 字段 = 10 核心 + 2 增强）
| 字段             | 来源                  |
| ---------------- | --------------------- |
| `id`             | collector             |
| `title`          | collector             |
| `source`         | collector             |
| `url`            | collector             |
| `category`       | collector（HN 必填）/ 透传（GitHub 一律 `open-source`） |
| `collected_at`   | collector             |
| `analyzed_at`    | analyzer              |
| `organized_at`   | organizer             |
| `summary`        | analyzer              |
| `tags`           | analyzer              |
| `relevance_score`| analyzer              |
| `meta`           | organizer 透传（始终为 dict，可空 `{}`）|

`meta` 字段集（跨源统一容器）：
- HN：`author` / `comments` / `time`
- GitHub：`stars` / `language` / `topics` / `pushed_at`

### D6. index.json 索引项（9 字段）
```json
{
  "id": "...",
  "title": "...",
  "source": "...",
  "url": "...",
  "category": "...",
  "file": "...",
  "tags": [...],
  "relevance_score": 0.81,
  "organized_at": "..."
}
```
- `articles[]` 按 `organized_at` 降序
- `total_count` 与实际 article 文件数一致

### D7. 门控与"非门控字段"边界
- 门控只看：`relevance_score` / `summary` / `tags` / `url`
- 不参与门控：`category` / `meta`（即使缺值也不丢）
- 过滤日志 `articles/_filtered-{date}.json` 的 `reason` 仍取 `relevance_score < 0.6` 等核心门控原因

### D8. 历史数据策略（不回填）
- 不为历史 raw 补 `category`（用户明确选择"going forward"）
- 唯一例外：验证性标注——为复测 #2-#5 一次性给 `hackernews-top-2026-07-27.json` 的 6 条 item 标 `category`
- 验证后该 raw 文件保留（既有 6 条带 category），与"不回填"原则不冲突（这是同一批次内的标注，不是历史回填）

## Testing Decisions

### Seam A：端到端流水线（覆盖 #2-#5）
- **路径**：`raw/hackernews-top-2026-07-27.json` → `enriched/hackernews-top-2026-07-27.enriched.json` → `articles/{YYYY-MM-DD}-{source}-{slug}.json` + `articles/index.json` + `articles/_filtered-2026-07-27.json`
- **触发**：dispatch analyzer + organizer subagent 各一次
- **断言**：
  - 6 条 item 含 `category`，analyzer 按上限打出的分数梯度合理
  - 3 条 article 落盘且 12 字段齐全（`category` 透传、`meta` 含 HN 字段）
  - 3 条 `< 0.6` 落过滤日志
  - index.json 9 字段齐全、按 `organized_at` 降序
  - raw / enriched 仅被读、未被改

### Seam B：Collector 错误边界（覆盖 #1）
- **路径**：collector HTTP 调用 → `raw/errors-{YYYY-MM-DD}-verify.json` + `raw/{source}-{YYYY-MM-DD}-verify.json`
- **触发**：dispatch collector subagent，注入 3 个调用（1 成功 + 1 5xx + 1 DNS 失败）
- **断言**：
  - errors 文件**全部**含 2 条失败记录（无任何豁免）
  - 成功结果独立写到 verify 后的 raw 文件
  - 未触碰既有 raw / enriched / articles
  - 未执行额外 HTTP 请求、未重试

### 验证产物（已留作证据）
- `raw/errors-2026-07-27-verify.json`（#1 证据）
- `raw/hackernews-top-2026-07-27-verify.json`（#1 成功路径证据）
- `articles/index.json`（9 字段契约已生效）
- 9 条 article（含 6 条 GitHub 也被自动补 `category: "open-source"` + `meta: {}`）

### 后续回归
- 任何对 4 个 .md 的再修改必须重跑 Seam A 与 Seam B
- 新增 source 时必须扩展 D5 的 `meta` 字段集与 D2 的 `category` 枚举（或新建并行字段集）

## Out of Scope

- **历史 raw 数据的 `category` 回填**——用户决策"going forward 不回填"
- **多源混排的兜底源**（如 GitHub Trending daily、TLDR AI、Ben's Bites）——可作为下一轮 PRD 单独讨论
- **基于 LLM-as-judge 的 relevance 评分**——当前仍是加权公式 + breakdown 的人工/规则可解释方案
- **Telegram / 飞书 Bot 多通道分发**——`AGENTS.md` 项目概述中有提及，但本 PRD 只覆盖数据流水线硬化，不涉及分发层
- **`category` 枚举再细分**（如 `article-or-news` 拆为 `ai-article` / `ai-news` / `ai-policy`）——本次选择 3 枚举够用；细分留待下游有需求时再做
- **跨天去重策略升级**（如 LLM 模糊匹配标题）——当前仅 url 精确去重 + 软原则判断
- **`_override` 字段的审计落盘**——目前 `_override` 只在 `score_breakdown` 中随 enriched 保留；未单独抽到 article；留待下游审计需求

## Further Notes

### 与 ADR-0001 的关系
ADR-0001 已锁定：
- enriched/ 落盘层（本轮保留，未改）
- 源 id 体系（本轮保留，category 不替代 id）
- 10 字段 article 契约 → 本轮扩为 12 字段（ADR-0001 的 D6 演进）

建议下一轮新立 **ADR-0002**，标题候选：《Pipeline 规范硬化第一轮：errors / category / meta》。

### 下一轮候选改进
1. HN 兜底源引入（如 GitHub Trending daily），与 HN 共用一个 source type 或新增 `github-trending-daily`
2. Analyzer `_override` 字段的频率统计与可视化（在 enriched/ 派生统计文件）
3. `category` 在 6 字段（id / title / source / url / category）层做聚类展示（如按 `category` 在 index 中分组）
4. GitHub 源的 `category` 隐含值的明确化：是否要把"GitHub = open-source"写入 `collector.md` GitHub 源提取字段表
5. `_filtered-{date}.json` 的历史聚合（按周 / 月）

### 风险与缓解
- **风险**：`_override` 可能被滥用，导致 agent 频繁突破上限拉高分数
  - **缓解**：analyzer 质量清单已要求 `_override` 必含理由；下一轮可在 index 中加 `_override_count` 字段做异常监控
- **风险**：`meta` 字段集扩张失控（每加 source 多一套字段）
  - **缓解**：D5 约束"meta 始终为 dict"，新 source 按相同模式扩展，AGENTS.md 同步更新
- **风险**：collector 的"分层筛选"在用户未指明 K 时默认 10，可能与用户期望不一致
  - **缓解**：collector.md 已写明"K 由用户指令给定；默认 10"，agent 接到非显式 K 的指令时会优先看用户原话