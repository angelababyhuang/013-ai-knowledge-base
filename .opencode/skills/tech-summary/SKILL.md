---
name: tech-summary
description: >
  tech-summary 分析 procedure：读取 knowledge/raw/ 的原始 item，撰写中文摘要、提炼
  英文 tags、按五维加权打 relevance_score（0.00-1.00），按 category 应用维度上限，
  灰色地带用 _override 说明，结果写入 knowledge/enriched/。Use when analyzing raw
  data into summaries/tags/scores, when analyzer needs the scoring procedure, or when
  "tech-summary" is named. Covers both GitHub and HN sources.
allowed-tools: Read Write WebFetch Grep Glob
---

# Skill: tech-summary — 技术摘要与相关性评分

本 skill 是 analyzer 的 **分析 procedure**：怎么写摘要、怎么打标签、怎么五维加权评分、怎么按 category 应用上限。

权限、目录边界、输入/输出路径约定（只写 `knowledge/enriched/`、raw 只读、不篡改 collector 字段、幂等）的权威在 `.opencode/agents/analyzer.md`；本 skill 只管"怎么分析"，不重述角色边界。

## 调用方

- **analyzer subagent** 收到 raw 文件分析指令时触发本 skill
- 主 Agent 也可直接 `@analyzer 分析 knowledge/raw/{source}-{date}.json`，analyzer 内部转交本 skill
- 跨源通用：GitHub 源（隐含 `open-source`）与 HN 源（自带 `category`）均用本 skill 评分

## 分析字段

对 raw 文件中**每个** item，补齐以下 4 个分析字段（collector 已交付的字段原样保留）：

| 字段 | 说明 |
| --- | --- |
| `summary` | 中文摘要，2-3 句，说清"它是什么、解决什么问题、为什么值得看"，不要照搬 description |
| `tags` | 英文 kebab-case 标签，3-5 个，如 `large-language-model`、`agent-framework` |
| `relevance_score` | 相关性评分（0.00-1.00，五维加权平均，保留两位小数），按下表 |
| `score_breakdown` | 五维评分明细，留作审计底稿（不进 article，由 organizer 剥离） |

## Steps

### 1. 读取 raw 文件

- 输入：`knowledge/raw/{source}-{YYYY-MM-DD}.json`
- 按需用 WebFetch 抓取 repo README / 文章原文辅助深度理解（可选）

**完成判据**：raw 文件已解析，items 列表已载入。

### 2. 撰写中文摘要（每条）

- 2-3 句，说清"它是什么、解决什么问题、为什么值得看"
- **不要照搬 description**，要有信息增量
- 语言：中文

**完成判据**：**每个** item 含非空中文 `summary`，且非 description 的翻译。

### 3. 提炼英文标签（每条）

- 3-5 个，全小写、连字符分隔（kebab-case），如 `large-language-model` / `agent-framework`
- 无中文、无空格

**完成判据**：**每个** item 含 3-5 个合法 `tags`。

### 4. 五维加权评分（每条）

按以下 5 个维度打分，每项 0.00-1.00，取加权平均：

| 维度 | 字段名 | 权重 | 评分标准 |
| --- | --- | --- | --- |
| 技术深度 | `tech_depth` | 0.25 | 是否涉及底层原理、架构设计、算法创新 |
| 实用价值 | `practical_value` | 0.30 | 工程师能否直接用于项目中 |
| 时效性 | `timeliness` | 0.20 | 是否反映最新趋势、近期发布 |
| 社区热度 | `community_heat` | 0.15 | Stars/Score/评论数是否突出 |
| 领域匹配 | `domain_match` | 0.10 | 与 AI/LLM/Agent 核心领域的匹配度 |

评分公式：

```
relevance_score = tech_depth * 0.25 + practical_value * 0.30 + timeliness * 0.20 + community_heat * 0.15 + domain_match * 0.10
```

- `relevance_score` 保留两位小数，范围 0.00-1.00
- 五维明细记入 `score_breakdown`，留作审计底稿
- **评分客观**：按五维逐项打分再加权，避免主观集中在某个区间；**跨条目横向比较后保证分布有梯度**

**完成判据**：**每个** item 含 5 维齐全的 `score_breakdown`，`relevance_score` 由公式加权得出且两位小数。

### 5. 按 category 应用维度上限

不同 category 在不同维度设有上限（硬约束）：

| category            | 维度上限                                                                       |
| ------------------- | ------------------------------------------------------------------------------ |
| `open-source`       | 不限（仓库类，代码可跑 + 文档齐全，`practical_value` 可达 1.0）                |
| `paper-or-talk`     | `practical_value` ≤ 0.5（论文/演讲为论述性内容，无可跑代码）                   |
| `article-or-news`   | `tech_depth` ≤ 0.5 且 `practical_value` ≤ 0.3（资讯类，技术深度低且不可直接用） |

- **HN 源**：item 自带 `category`，按上表检查对应维度上限。
- **GitHub 源**：隐含 `open-source`，不受上限约束。

> 设计意图：HN 来源常混合"开源仓库 / 论文演讲 / 资讯文章"三类，不差异化会让"Stanford 报告"与"GitHub 项目"评分趋同，违背"知识库偏向技术资源"定位。

**完成判据**：**每个** HN item 已按其 `category` 检查维度上限；GitHub item 视为 `open-source` 未受约束。

### 6. 灰色地带处理（`_override`）

当遇到"灰色地带"（如一篇 `article-or-news` 实际含可运行代码 + GitHub 仓库链接），可在 `score_breakdown` 中增加可选字段 `_override` 说明突破上限的理由：

```json
{
  "tech_depth": 0.45,
  "practical_value": 0.85,
  "timeliness": 0.7,
  "community_heat": 0.4,
  "domain_match": 0.9,
  "_override": {
    "practical_value": "内含 GitHub repo + Colab notebook，按 open-source 类实际可跑",
    "tech_depth": "仍按 article 上限 0.5，未突破"
  }
}
```

- `_override` 只记录"哪一维突破 + 理由"
- 实际分数仍按突破后的值参与 `relevance_score` 加权
- 未写 `_override` 的维度视为遵守上限

**完成判据**：任何突破上限的维度均在 `_override` 中说明理由；未突破的维度无 `_override` 条目。

### 7. 落盘 enriched

- 文件：`knowledge/enriched/{source}-{YYYY-MM-DD}.enriched.json`
- 结构 = raw 文件结构 + 每个 item 增补 `summary` / `tags` / `relevance_score` / `score_breakdown`
- 顶层新增 `analyzed_at`（ISO 8601）
- collector 原始字段**原样保留，不可篡改**
- 幂等：若当天 enriched 文件已存在，按 `id` 覆盖对应 item 的分析字段，不重复追加
- 格式：2 空格缩进、UTF-8、中文不转义

> 质量门控：`relevance_score < 0.6` 的条目，organizer 将丢弃，不进入 `knowledge/articles/`。analyzer 仍保留其分析结果（含低分与 score_breakdown），由 organizer 决定是否丢弃。

**完成判据**：文件可通过 `JSON.parse`；**每个** item 含 4 个分析字段；`analyzed_at` 为当前时间；collector 原始字段逐字段未被篡改。

## Reference

### 输出 schema（enriched 文件）

```json
{
  "source": "github-hot-repos",
  "collected_at": "2026-03-17T10:30:00Z",
  "analyzed_at": "2026-03-17T11:00:00Z",
  "count": 20,
  "items": [
    {
      "id": "openai/agents-sdk",
      "title": "agents-sdk",
      "source": "github-hot-repos",
      "collected_at": "2026-03-17T10:30:00Z",
      "url": "https://github.com/openai/agents-sdk",
      "summary": "OpenAI 官方的 Agent 构建框架，提供多 Agent 协作、工具调用、交接等原语，与 OpenAI 模型深度集成，适合快速搭建生产级 agentic 应用。",
      "tags": ["agent-framework", "openai", "multi-agent", "tool-use"],
      "relevance_score": 0.87,
      "score_breakdown": {
        "tech_depth": 0.80,
        "practical_value": 0.95,
        "timeliness": 0.90,
        "community_heat": 0.85,
        "domain_match": 0.95
      }
    }
  ]
}
```

> collector 的其余原始字段（stars/language/topics 等）原样保留；`score_breakdown` 留作审计底稿，不进 article。

### 质量自检

- [ ] **每个** item 含非空 `summary`（中文）、`tags`（3-5 个英文 kebab-case）、`relevance_score`（0.00-1.00 两位小数）、`score_breakdown`（含全部 5 维）
- [ ] collector 原始字段（id/title/source/url/collected_at/category 等）**逐字段未被篡改**
- [ ] `tags` 全小写、连字符分隔，无中文、无空格
- [ ] `summary` 有信息增量，不是 description 的翻译
- [ ] `relevance_score` 由五维加权计算得出，`score_breakdown` 明细完整
- [ ] HN 源 item 已按 `category` 应用维度上限；如有突破则在 `score_breakdown._override` 中说明理由
- [ ] 评分分布有梯度（跨条目横向比较，未挤堆在同一区间）
- [ ] `analyzed_at` 为当前时间，ISO 8601
- [ ] 输出落盘到 `knowledge/enriched/`，文件名带 `.enriched.json` 后缀

## 注意事项

1. **幂等**：若当天 enriched 文件已存在，按 `id` 覆盖对应 item 的分析字段，不重复追加。
2. **语言**：摘要中文，标签英文。
3. **不篡改 raw**：原始数据只读，分析结果一律写 enriched/。
4. **评分客观**：按五维逐项打分再加权，避免主观集中在某个区间；跨条目横向比较后保证分布有梯度。
5. **按 category 应用上限**：HN 源 item 自带 `category`，必须据此检查维度上限；GitHub 源隐含 `open-source`，不受上限约束。灰色地带用 `_override` 说明。
