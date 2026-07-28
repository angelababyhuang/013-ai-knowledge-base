# AGENTS.md

## 项目概述

AI 知识库助手：自动从 GitHub 热门仓库（github-hot-repos）和 Hacker News 采集 AI/LLM/Agent 领域技术动态，通过国产大模型分析、摘要、打标签后结构化存储为 JSON，并通过 Telegram / 飞书 Bot 多通道分发。

## 核心价值

- 每日自动采集 AI/LLM/Agent 领域的高质量技术文章与开源项目
- 通过 Agent 协作完成 采集 → 分析 → 整理 三阶段流水线
- 输出格式统一的 JSON 知识条目，便于下游应用消费

## 项目结构

```
013-ai-knowledge-base/
├── AGENTS.md                          # 项目记忆文件（本文件）
├── .env.example                       # 环境变量模板
├── README.md                          # 使用说明
├── .opencode/
│   ├── agents/                        # 角色 = 权限/目录边界/跨源约定（role harness）
│   │   ├── collector.md               # 采集 Agent — role harness + 数据源路由
│   │   ├── analyzer.md                # 分析 Agent — role harness + procedure 路由
│   │   └── organizer.md               # 整理 Agent 角色定义
│   └── skills/                        # procedure = 各源"怎么采/怎么分析"（被 subagent 触发）
│       ├── github-hot-repos/SKILL.md  # GitHub 热门仓库采集 procedure ✅
│       ├── hackernews-top/SKILL.md    # Hacker News 热门采集 procedure ✅
│       └── tech-summary/SKILL.md      # analyzer 摘要/打分 procedure ✅
└── knowledge/
    ├── raw/                           # 原始采集数据（JSON，collector 写、他人只读）
    ├── enriched/                      # 分析增强后的数据（JSON，analyzer 写）
    └── articles/                      # 整理后的知识条目（JSON，organizer 写）
```

## 编码规范

### 文件命名

- 原始数据：knowledge/raw/{source}-{YYYY-MM-DD}.json
  - 示例：knowledge/raw/github-hot-repos-2026-03-17.json
  - 示例：knowledge/raw/hackernews-top-2026-03-17.json
- 增强数据：knowledge/enriched/{source}-{YYYY-MM-DD}.enriched.json
  - 示例：knowledge/enriched/github-hot-repos-2026-03-17.enriched.json
- 错误记录：knowledge/raw/errors-{YYYY-MM-DD}.json
- 知识条目：knowledge/articles/{YYYY-MM-DD}-{source}-{slug}.json
  - 示例：knowledge/articles/2026-03-17-github-hot-repos-openai-agents-sdk.json
- 索引文件：knowledge/articles/index.json

### JSON 格式
- 使用 2 空格缩进
- 日期格式：ISO 8601（YYYY-MM-DDTHH:mm:ssZ）
- 字符编码：UTF-8

### 字段归属契约

最终知识条目（knowledge/articles/）必须包含以下 12 字段（10 核心 + 2 增强），由不同角色分阶段补齐：

| 字段 | 性质 | 归属角色 |
| --- | --- | --- |
| `id`, `title`, `url`, `category` | 来源元数据 | collector |
| `source`, `collected_at` | 溯源元数据（采集时即知） | collector |
| `summary` | 中文摘要（100-200 字） | analyzer |
| `tags` | 英文 kebab-case 标签 | analyzer |
| `relevance_score` | 相关性评分（0-1，五维加权） | analyzer |
| `analyzed_at` | 分析时间戳 | analyzer |
| `organized_at` | 归档时间戳 | organizer |
| `meta` | 跨源统一容器（HN: author/comments/time；GitHub: stars/language/topics/pushed_at） | organizer 透传 |

> 注：raw item 只需交付 collector 归属的字段；`summary/tags/relevance_score/score_breakdown/analyzed_at` 由 analyzer 在 enriched/ 阶段补齐，`organized_at` 与 `meta` 由 organizer 补齐。
> `score_breakdown` 留在 enriched/ 作审计底稿，不进 article。
> `category`（HN 必填，GitHub 隐含 `open-source`）与 `meta` 都不参与门控（门控只看 `relevance_score` / `summary` / `tags` / `url`），仅供下游消费。
> `id` 跨源唯一性与 article 文件名 slug 生成规则待 analyzer/organizer 阶段定义。

### 语言约定
- 代码、JSON 键名、文件名：英文
- 摘要、分析、注释：中文
- 标签（tags）：英文小写，用连字符分隔（如 large-language-model）

## 工作流规划
---

### 三阶段流水线

‘‘‘
[collector] ──采集──→ knowledge/raw/         （collector 写，他人只读）
                          │
[analyzer]  ──分析──→ knowledge/enriched/    （读 raw/，写 enriched/）
                          │
[organizer] ──整理──→ knowledge/articles/
’’’
### Agent 协作规则

1. 单向数据流：collector → analyzer → organizer，不可反向
2. 职责隔离：每个 Agent 只操作自己权限范围内的文件
3. 幂等性：重复运行同一天的采集不应产生重复条目
4. 质量门控：`relevance_score < 0.6`、或摘要<50字、或 tags<2、或 url 异常的条目，Organizer 应丢弃
5. 可追溯：每个条目保留 url、source 和 collected_at 用于溯源

### 三层架构：主 Agent → Subagent → Skill

角色（role，谁有权限/边界）与 procedure（怎么采/怎么分析）分离：

‘‘‘
主 Agent ──@collector──▶ Collector Subagent (角色：权限/目录边界/跨源约定)
  (编排器)                  │ 识别 "GitHub 数据源" → 触发
                           ▼
                     github-hot-repos Skill (procedure：怎么调 API/提取字段/落盘)
’’’

- **角色（agents/*.md）**：权限、目录边界、跨源约定（errors 策略/文件命名/JSON 格式/幂等）。
- **procedure（skills/*/SKILL.md）**：某数据源的采集/分析步骤，被对应 subagent 触发。`github-hot-repos` / `hackernews-top` 承载采集 procedure（查询参数、字段提取表、限流/筛选、输出 schema）；`tech-summary` 承载分析 procedure（摘要、五维评分、category 上限、`_override`）。各 skill 是其领域的单一事实来源。
- collector.md 内置**数据源路由**：识别到 "github-hot-repos" / "hackernews-top" 时转交对应 skill；analyzer.md 识别到分析任务时转交 `tech-summary` skill。

### Agent调用方式

在OpenCode中使用@语法调用特定Agent：
‘‘‘
@collector 采集今天的GitHub 热门仓库数据
@analyzer 分析 knowledge/raw/github-hot-repos-2026-03-17.json
@organizer 整理今天所有已分析的原始数据
’’’
也可以在对话中要求主Agent依次委派子Agent，实现流水线作业。`@collector` 收到 GitHub 采集指令后，会内部触发 `github-hot-repos` skill 执行实际采集。

# 错误处理

- 网络请求失败时，记录错误并跳过该条目，不中断整体流程
- API限流时，等待后重试，最多3次
- 数据格式异常时，写入 knowledge/raw/errors-{date}.json 供人工排查

## 技术栈

- 运行时：OpenCode + LLM(minimax)
- 数据源：GitHub API v3、 Hacker News API(firebase)
- 输出格式：JSON
- 版本管理：Git
