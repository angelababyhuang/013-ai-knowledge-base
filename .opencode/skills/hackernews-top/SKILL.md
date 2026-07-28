---
name: hackernews-top
description: >
  采集 hackernews-top 数据源：拉取 Hacker News Top Stories，按 AI/LLM/Agent
  关键词过滤并分层筛选（open-source 优先，不足放宽到 AI 主题），每条人工判定 category，
  提取标准字段幂等写入 knowledge/raw/hackernews-top-{date}.json。Use when collecting
  Hacker News top stories, when collector needs the HN data-source procedure, or when
  "hackernews-top" is named. Not for GitHub or other sources.
allowed-tools: Read Write Bash WebFetch Grep Glob
---

# Skill: hackernews-top — Hacker News 热门采集

本 skill 是 collector 的 **Hacker News 数据源 procedure**：怎么拉 Top Stories、怎么过滤、怎么分层筛选、怎么判 category、怎么幂等落盘。

权限、目录边界、跨源约定（errors 穷举式策略 / 文件命名 / JSON 格式 / 幂等）的权威在 `.opencode/agents/collector.md`；本 skill 只管"采 HN 这一路"，不重述跨源规则。

## 调用方

- **collector subagent** 识别"Hacker News / hackernews-top"时触发本 skill
- 主 Agent 也可直接 `@collector 采集 Hacker News`，collector 内部转交本 skill
- 单向数据流：本 skill 只写 `knowledge/raw/`，不碰 `enriched/` 与 `articles/`

## Steps

### 1. 获取 Top Stories ID 列表

- 端点：`https://hacker-news.firebaseio.com/v0/topstories.json`
- 取前 50 个 ID

**完成判据**：拿到一个 ID 数组（最多 50 个）；失败转入 Step 8。

### 2. 逐条获取详情

- 端点：`https://hacker-news.firebaseio.com/v0/item/{id}.json`
- 对每个 ID 请求详情

**完成判据**：**每个** ID 都已尝试请求；成功的进入 Step 3，失败的转入 Step 8（无静默跳过）。

### 3. 关键词过滤

仅保留标题包含 AI / LLM / Agent / GPT / Claude / model 等关键词的条目。主动剔除语义不相关命中（如 MRI 硬件、pre-ai 词汇误命中）。

**完成判据**：保留集**每条**标题均含 AI 主题关键词，且已剔除语义误命中。

### 4. 分层筛选

- **首轮**：仅保留 `open-source` 类（`url` 指向 github.com / gitlab.com / bitbucket.org 等代码托管平台）。
- 若首轮结果数 < K（**K 由用户指令给定；默认 10**），**放宽范围**到 AI 主题，按 `score` 降序补足 K 条。
- 放宽部分按内容性质归入：
  - `paper-or-talk`（含 pdf / 学术演讲 / 论文）
  - `article-or-news`（资讯 / 评论 / 政策）

> 若放宽后仍不足 K 条，如实交付实际数量，**不伪造、不凑数**。

**完成判据**：open-source 类已全部纳入；若不足 K 已按 score 降序放宽；最终集每条均已判定 `category`。

### 5. URL 回填

若 `url` 为 null（Ask HN / 纯文本帖），回填 `https://news.ycombinator.com/item?id={id}`。

**完成判据**：保留集中**每条** `url` 非空且以 `https://` 开头。

### 6. 提取字段

把每个 item 映射为 raw item：

| 字段          | 来源          | 说明                                                                 |
| ------------- | ------------- | -------------------------------------------------------------------- |
| `id`          | `id`          | HN 文章 ID                                                           |
| `title`       | `title`       | 文章标题                                                             |
| `source`      | 固定值        | `hackernews-top`                                                     |
| `collected_at`| 采集时刻      | ISO 8601，条目级时间戳                                               |
| `url`         | `url`         | 原文链接；若为 null 回填 `https://news.ycombinator.com/item?id={id}` |
| `score`       | `score`       | HN 得分                                                              |
| `comments`    | `descendants` | 评论数                                                               |
| `author`      | `by`          | 作者                                                                 |
| `time`        | `time`        | Unix 时间戳                                                          |
| `category`    | agent 判定    | **必填**，3 枚举：`open-source` / `paper-or-talk` / `article-or-news` |

> `category` 由 agent **人工判定**（不可仅凭 url 启发式推断，避免"博客讲 GitHub 项目"边界错判）。

**完成判据**：保留集中**每个** item 已映射；`id` / `title` / `url` / `source` / `collected_at` / `category` 非空，`score` 为数字。缺字段即记 errors，不留半成品。

### 7. 幂等落盘

- 文件：`knowledge/raw/hackernews-top-{YYYY-MM-DD}.json`
- 若文件已存在：读取后按 `id` 去重追加，**不覆盖**已有数据
- 格式：2 空格缩进、UTF-8、中文不转义、日期 ISO 8601

**完成判据**：文件可通过 `JSON.parse`；顶层 `count` 与 `items` 长度一致；无重复 `id`；文件名含当天日期。

### 8. 失败审计（穷举式，无自由裁量）

凡当次运行发起过的 HTTP 请求失败，**一律**追加写入 `knowledge/raw/errors-{YYYY-MM-DD}.json`。触发条件与记录格式的权威定义见 collector.md「错误产物」节（网络层失败 / HTTP 非 2xx / 限流耗尽 / 响应解析失败 / 必填字段缺失，任一即记入）。

文件已存在则读取后追加，幂等不覆盖。

**完成判据**：当次运行中**所有**失败请求均已落盘 errors；errors 文件可 `JSON.parse`；未发生静默跳过。

## Reference

### 输出 schema（hackernews-top raw 文件）

```json
{
  "source": "hackernews-top",
  "collected_at": "2026-07-27T02:53:29Z",
  "count": 6,
  "items": [
    {
      "id": "49063397",
      "title": "Wattage: A token-spend profiler and cost-regression gate for AI agents",
      "source": "hackernews-top",
      "collected_at": "2026-07-27T02:53:29Z",
      "url": "https://github.com/faizannraza/wattage",
      "score": 4,
      "comments": 0,
      "author": "faizanraza03",
      "time": 1785108455,
      "category": "open-source"
    },
    {
      "id": "49056620",
      "title": "Terence Tao: Mathematics in the Age of AI [pdf]",
      "source": "hackernews-top",
      "collected_at": "2026-07-27T02:53:29Z",
      "url": "https://teorth.github.io/tao-web/slides/age-of-ai-icm-2026.pdf",
      "score": 107,
      "comments": 46,
      "author": "Anon84",
      "time": 1785061955,
      "category": "paper-or-talk"
    }
  ]
}
```

### 质量自检

- [ ] 每个条目含非空 `id` / `title` / `url` / `source`
- [ ] 每个条目含条目级 `collected_at`（ISO 8601）
- [ ] `url` 以 `https://` 开头；API 返回 null 已回填 HN 讨论页
- [ ] `score` 为数字类型
- [ ] 每个条目含 `category`，且为 3 枚举之一（`open-source` / `paper-or-talk` / `article-or-news`）
- [ ] 无重复 `id`
- [ ] JSON 2 空格缩进、UTF-8、可通过 `JSON.parse` 校验
- [ ] 文件名含当天日期
- [ ] 当次**所有** HTTP 失败均已追加写入 `errors-{YYYY-MM-DD}.json`，无静默跳过

## 注意事项

1. **category 必填**：HN 每条必须由 agent 判定 `category`（3 枚举之一）。
2. **分层筛选**：open-source 优先；不足 K 条（默认 10）才放宽到 AI 主题，按 score 降序补足。
3. **URL 回填**：Ask HN / 纯文本帖 url 为 null，必须回填 HN 讨论页。
4. **幂等**：当天文件已存在则读取后追加去重，不覆盖。
5. **errors 权威**：错误触发清单与记录格式以 collector.md「错误产物」节为准，本 skill 不重述。
