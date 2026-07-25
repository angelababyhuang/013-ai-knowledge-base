# ADR-0001: 对齐课程版 Analyzer / Organizer 设计

- **日期**：2026-07-25
- **状态**：已接受（Accepted）
- **来源**：一次 `/grilling` 会话的逐项决策

## 背景

项目已有自写的 collector / analyzer / organizer 三份 agent 定义（`.opencode/agents/*.md`），并经过上一轮 grilling 修正了 AGENTS.md 与 collector.md 之间的矛盾（评分当时定为 1-10、文件名加 `{source}` 段等）。

随后引入课程提供的 `analyzer.md` / `organizer.md` 范本，逐项比对后发现两类差异：

1. **架构级**：数据流模型（落盘 vs 对话中转）、ID 体系（源 id vs kb- 独立 id）
2. **工程细节**：评分维度、摘要规格、门控规则、去重、过滤日志、字段集

本 ADR 记录「哪些保留我们既有设计、哪些采纳课程做法、以及为什么」。

## 决策前提（锁定，不在本次讨论范围）

| 前提 | 说明 |
| --- | --- |
| enriched/ 落盘层保留 | analyzer 有 Write，物化到 `knowledge/enriched/`；organizer 读 `enriched/`。**不**采用课程「analyzer 禁 Write、主 Agent 对话中转」的模型 |
| 沿用源 id | article 的 id 直接用 collector 的源 id（GitHub `full_name` / HN 数字 id）。**不**引入课程 `kb-{date}-{seq}` 独立 id 与 `source_id` |

**理由**：架构落盘层已在上一轮 grilling 中确认；独立 id 体系对本阶段是过度抽象，源 id + slug 已满足跨源唯一性。

## 决策（9 条）

### D1. 评分：采纳课程 0-1 五维加权 + score_breakdown
- `relevance_score` 改为 0.00-1.00，五维加权平均：
  - 技术深度 0.25 / 实用价值 0.30 / 时效性 0.20 / 社区热度 0.15 / 领域匹配 0.10
- 新增 `score_breakdown` 字段（5 个维度明细）
- **回退**上一轮的 1-10 单值四档；连带 AGENTS.md 门控阈值 `<5` → `<0.6`
- **理由**：breakdown 让分数可解释、可审计；加权公式把「实用 > 技术深度 > 时效 > 热度 > 匹配」的优先级固化（契合「工程师视角、能不能用 > 有没有创新」）
- **取舍**：承认 LLM 对两位小数存在虚假精度；缓解——breakdown 的价值在相对比较与留痕，即使单个小数偏软也有用

### D2. 门控：采纳课程四规则（放 organizer）
四条命中任一即丢弃：
- `relevance_score < 0.6`
- `summary < 50 字`（地板线，非目标）
- `tags < 2`（地板线，目标仍 3-5）
- `url` 格式异常
- **理由**：organizer 作为最终守门人，多维校验 = defense in depth，兜住 analyzer 偶尔失手；契合「宁缺毋滥」

### D3. 摘要：采纳课程规格
- 100-200 字（中文字符计数）
- 四要素尽量涵盖：这是什么 / 为什么重要 / 关键技术点 / 适用场景
- 反模板开头（禁「本文介绍了」等套话）
- 技术术语保留英文原文
- 鼓励 WebFetch 取 README / 正文提升质量（失败则基于已有信息降级）
- **理由**：可衡量（对接 D2 的 `<50 字` 地板线）；多出的「关键技术点 / 适用场景」对工程师读者价值最高

### D4. 去重：url 精确 + 软标题判断
- 精确去重键由 `id` 改为 `url`（url 跨源更稳定，能抓跨源重复）
- 模糊标题**不设硬性 90% 阈值**（organizer 无 Bash，无法程序化算相似度），改为软原则：主观判断高度相似则跳过并记日志
- **理由**：拿到跨源去重好处，又不引入测不了的假精度阈值

### D5. 过滤日志：`articles/_filtered-{date}.json`
- organizer 每丢一条记 `{url, source, reason}`，幂等追加
- 缺字段（incomplete）并入 `reason`，不单独搞 status 机制
- 位置选 `articles/`（下划线前缀与正式条目区分），**不**选课程的 `raw/`——因为 organizer 目录边界是「只写 articles/，raw/enriched 只读」
- 与 collector 的 `raw/errors-{date}.json` 区分（采集错误 vs 归档过滤）

### D6. article 字段：8 → 10
- 新增 `analyzed_at`（analyzer 时间戳）、`organized_at`（organizer 时间戳）
- **不加**：`source_id`（沿用源 id，无 kb-id）、`status`（进 articles/ 即 published，单值冗余）、`score_breakdown`（留 enriched/ 作审计底稿，article 保持精简）
- 最终 10 字段：`id, title, source, url, collected_at, analyzed_at, organized_at, summary, tags, relevance_score`

### D7. index.json 结构
- 顶层：`updated_at` / `total_count`（原 `count`，明确是累计总数）/ `articles[]`
- entry 字段：`id, title, source, file, tags, relevance_score, organized_at`
- 按 `organized_at` **降序**（最新在前）
- **理由**：保留 `source` 便于 index 层按源过滤；`organized_at` 支持排序

### D8. enriched 中 analyzed_at 改 per-item
- 弃顶层 `analyzed_at`，改为每个 item 内
- **理由**：analyzer 支持幂等重跑（按 id 覆盖），per-item 时间戳能如实反映「哪几条是刚分析的」；顶层会谎报「全部刚分析」
- `collected_at` 维持上轮的 per-item + 顶层（顶层代表整批采集时刻，是真实批次属性）

### D9. 文件名保留 `{source}` 段
- `knowledge/articles/{YYYY-MM-DD}-{source}-{slug}.json`
- **理由**：双源（`github-hot-repos` / `hackernews-top`）下，同一天可能出现 slug 相同但 url 不同的条目；source 段作文件名级命名空间隔离，防撞车
- **不**跟课程的 `{date}-{slug}.json`

## 影响的文件

| 文件 | 改动依据 |
| --- | --- |
| `.opencode/agents/analyzer.md` | D1 / D3 / D8：评分五维加权 + breakdown、摘要规格、analyzed_at 移 per-item |
| `.opencode/agents/organizer.md` | D2 / D4 / D5 / D6 / D7：门控四规则、去重、过滤日志、article 10 字段、index 结构 |
| `AGENTS.md` | D1 / D6 级联：字段归属表 `relevance_score` 改 0-1、补 `analyzed_at`/`organized_at`；协作规则门控改 `<0.6` |

## 未采纳的课程做法（及原因）

| 课程做法 | 不采纳原因 |
| --- | --- |
| analyzer 禁 Write、主 Agent 对话中转 | 与已锁定的 enriched/ 落盘架构冲突；且课程自身此处有不自洽（analyzer 不写文件，organizer 却要读 raw 的 analyzed_at） |
| `kb-{date}-{seq}` 独立 id + `source_id` | 本阶段过度抽象；源 id + slug 已满足 |
| 模糊去重 title 相似度 > 90% | organizer 无 Bash，无法程序化测量 |
| 过滤日志放 `raw/` | 违反 organizer 只写 articles/ 的目录边界 |
| article 带 `status: "published"` | 进 articles/ 即 published，单值冗余 |
| article 带 `score_breakdown` | 留 enriched/ 作审计底稿，article 保持精简 |
