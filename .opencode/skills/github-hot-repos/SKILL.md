---
name: github-hot-repos
description: >
  采集 github-hot-repos 数据源：调用 GitHub Search API 按 stars 降序拉取
  AI/LLM/Agent 领域仓库，提取标准字段并幂等写入 knowledge/raw/github-hot-repos-{date}.json。
  Use when collecting GitHub trending/hot repos, when collector needs the GitHub
  data-source procedure, or when "github-hot-repos" is named. Not for Hacker News
  or other sources.
allowed-tools: Read Write Bash WebFetch Grep Glob
---

# Skill: github-hot-repos — GitHub 热门仓库采集

本 skill 是 collector 的 **GitHub 数据源 procedure**：怎么调 GitHub Search API、提取哪些字段、怎么幂等落盘。

权限、目录边界、跨源约定（errors 穷举式策略 / 文件命名 / JSON 格式 / 幂等）的权威在 `.opencode/agents/collector.md`；本 skill 只管"采 GitHub 这一路"，不重述跨源规则。

## 调用方

- **collector subagent** 识别"GitHub 数据源 / github-hot-repos"时触发本 skill
- 主 Agent 也可直接 `@collector 采集 GitHub 热门仓库`，collector 内部转交本 skill
- 单向数据流：本 skill 只写 `knowledge/raw/`，不碰 `enriched/` 与 `articles/`

## Steps

### 1. 构建搜索查询

- 端点：`https://api.github.com/search/repositories`
- 关键词：`AI OR LLM OR agent OR "large language model" OR RAG OR MCP`
- 排序：`sort=stars`，`order=desc`
- 时间窗口：过去 7 天内创建或更新
- 每次采集：Top 20（`per_page=20`）

完整请求示例：
```
GET https://api.github.com/search/repositories?q=AI+OR+LLM+OR+agent+OR+"large+language+model"+OR+RAG+OR+MCP&sort=stars&order=desc&per_page=20
```

**完成判据**：查询串已按上述参数拼好，含 `q` / `sort` / `order` / `per_page`。

### 2. 发起认证请求

- 请求头必须带：
  - `Accept: application/vnd.github.v3+json`
  - `Authorization: Bearer $GITHUB_TOKEN`（环境变量）
- 未认证限额 60 次/小时；认证后 5000 次/小时 —— **必须带 token**
- 编码：响应文本保持 UTF-8，不转义中文

**完成判据**：拿到 HTTP 响应；`2xx` 且 body 可解析为含 `items[]` 的 JSON 视为成功，转入 Step 4；任何失败转入 Step 6（**无静默跳过**）。

### 3. 限流处理（HTTP 403 / 429）

- 收到 403 或 429 时，读取响应头 `X-RateLimit-Reset`，等待至该时刻
- 最多重试 3 次
- 仍失败则记入 errors（见 Step 6）

**完成判据**：要么某次重试成功转入 Step 4，要么 3 次耗尽后转入 Step 6。

### 4. 提取字段

把响应 `items[]` 中每个 repo 映射为 raw item：

| 字段          | 来源               | 说明                             |
| ------------- | ------------------ | -------------------------------- |
| `id`          | `full_name`        | 仓库全名，如 `openai/agents-sdk` |
| `title`       | `name`             | 仓库名                           |
| `source`      | 固定值             | `github-hot-repos`               |
| `collected_at`| 采集时刻           | ISO 8601，条目级时间戳           |
| `description` | `description`      | 仓库描述                         |
| `url`         | `html_url`         | 仓库链接                         |
| `stars`       | `stargazers_count` | Star 数                          |
| `language`    | `language`         | 主要编程语言                     |
| `topics`      | `topics`           | 仓库标签列表                     |
| `created_at`  | `created_at`       | 创建时间                         |
| `updated_at`  | `pushed_at`        | 最近推送时间                     |

> GitHub 源**隐含** `category="open-source"`：不在 raw 存储，由 organizer 落盘 article 时统一补。

**完成判据**：响应中**每个** repo 都已映射；`id` / `title` / `url` / `source` / `collected_at` 非空，`stars` 为数字。任何必填字段缺失即记入 errors，**不留半成品条目**。

### 5. 幂等落盘

- 文件：`knowledge/raw/github-hot-repos-{YYYY-MM-DD}.json`
- 若文件已存在：读取后按 `id` 去重追加，**不覆盖**已有数据
- 格式：2 空格缩进、UTF-8、中文不转义、日期 ISO 8601

**完成判据**：文件可通过 `JSON.parse`；顶层 `count` 与 `items` 长度一致；无重复 `id`；文件名含当天日期。

### 6. 失败审计（穷举式，无自由裁量）

凡当次运行发起过的 HTTP 请求失败，**一律**追加写入 `knowledge/raw/errors-{YYYY-MM-DD}.json`。触发条件与记录格式的权威定义见 collector.md「错误产物」节（网络层失败 / HTTP 非 2xx / 限流耗尽 / 响应解析失败 / 必填字段缺失，任一即记入，不论核心或扩展批次）。

文件已存在则读取后追加，幂等不覆盖。

**完成判据**：当次运行中**所有**失败请求均已落盘 errors；errors 文件可 `JSON.parse`；未发生静默跳过。

## Reference

### 输出 schema（github-hot-repos raw 文件）

```json
{
  "source": "github-hot-repos",
  "collected_at": "2026-03-17T10:30:00Z",
  "query": "AI OR LLM OR agent, past 7 days, sorted by stars",
  "count": 20,
  "items": [
    {
      "id": "openai/agents-sdk",
      "title": "agents-sdk",
      "source": "github-hot-repos",
      "collected_at": "2026-03-17T10:30:00Z",
      "description": "OpenAI Agents SDK for building agentic AI applications",
      "url": "https://github.com/openai/agents-sdk",
      "stars": 15200,
      "language": "Python",
      "topics": ["ai", "agents", "openai", "llm"],
      "created_at": "2026-03-10T08:00:00Z",
      "updated_at": "2026-03-17T06:30:00Z"
    }
  ]
}
```

### 质量自检

- [ ] 每个条目含非空 `id` / `title` / `url` / `source`
- [ ] 每个条目含条目级 `collected_at`（ISO 8601）
- [ ] `url` 以 `https://` 开头
- [ ] `stars` 为数字类型
- [ ] 无重复 `id`
- [ ] JSON 2 空格缩进、UTF-8、可通过 `JSON.parse` 校验
- [ ] 文件名含当天日期
- [ ] 当次**所有** HTTP 失败均已追加写入 `errors-{YYYY-MM-DD}.json`，无静默跳过

## 注意事项

1. **请求头**：GitHub API 必须带 `Accept: application/vnd.github.v3+json`。
2. **认证**：使用环境变量 `GITHUB_TOKEN` 提高限额。
3. **限流**：收到 403/429 时读 `X-RateLimit-Reset` 头并等待。
4. **幂等**：当天文件已存在则读取后追加去重，不覆盖。
5. **errors 权威**：错误触发清单与记录格式以 collector.md「错误产物」节为准，本 skill 不重述。
