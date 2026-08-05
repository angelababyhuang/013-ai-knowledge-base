# 逆向梳理已实现功能并整理为基线 PRD

## Goal

对存量项目做**只读逆向梳理**，把当前已实现的功能、契约、代码、数据资产固化为一份**基线 PRD**，作为后续演进的单一现状参照。全程不重构、不修改任何现有代码与数据。

## User Value

- 为后续 agent 接手提供"项目现状到底实现了什么"的权威快照，避免凭 AGENTS.md 等 spec 文档（可能与实现漂移）误判。
- 沉淀 spec 与实现的漂移点（声明但缺失的功能），为下一轮规划提供输入。

## Confirmed Facts（已通过代码/文档扫描核实）

### 架构与编排
- 三层架构：主 Agent（编排器）→ Subagent（`@collector` / `@analyzer` / `@organizer`）→ Skill（procedure）。
- 三阶段**单向数据流**：collector → `knowledge/raw/` → analyzer → `knowledge/enriched/` → organizer → `knowledge/articles/`，目录边界互斥、不可反向回写。
- 角色与 procedure 分离：`agents/*.md` 管权限/目录边界/跨源约定；`skills/*/SKILL.md` 管具体采集/分析步骤（单一事实来源）。

### Collector 采集层（已实现）
- `github-hot-repos` skill：GitHub Search API，关键词 `AI/LLM/agent/large language model/RAG/MCP`，stars 降序 Top 20，`GITHUB_TOKEN` 认证，403/429 限流重试（≤3 次），按 `id` 幂等落盘 `knowledge/raw/github-hot-repos-{date}.json`。
- `hackernews-top` skill：HN Top Stories 前 50 → 逐条详情 → 关键词过滤（含语义剔除）→ 分层筛选（open-source 优先，不足 K 放宽到 paper-or-talk/article-or-news，默认 K=10）→ `category` 人工判定（3 枚举）→ URL 回填 → 幂等落盘。
- 错误产物：穷举式触发（网络层失败 / HTTP 非 2xx / 限流耗尽 / 解析失败 / 必填字段缺失），无自由裁量，写 `knowledge/raw/errors-{date}.json`。

### Analyzer 分析层（已实现）
- `tech-summary` skill：中文摘要 2-3 句（含信息增量，非 description 翻译）；英文 kebab-case tags 3-5 个。
- 五维加权评分：`tech_depth*0.25 + practical_value*0.30 + timeliness*0.20 + community_heat*0.15 + domain_match*0.10`，保留两位小数，产出 `score_breakdown` 审计底稿。
- category 维度上限：open-source 不限 / paper-or-talk `practical_value ≤ 0.5` / article-or-news `tech_depth ≤ 0.5 且 practical_value ≤ 0.3`；灰色地带用 `_override` 说明。
- 输出 `knowledge/enriched/{source}-{date}.enriched.json`，顶层 `analyzed_at`，原始字段不篡改，按 `id` 幂等覆盖。

### Organizer 整理层（已实现）
- 四规则质量门控：`relevance_score < 0.6` / `summary < 50 字` / `tags < 2` / url 异常，命中任一即丢弃。
- url 精确去重（跨天比对 articles/）+ 标题软相似判断。
- 格式化为 12 字段知识条目（10 核心 + `category` + `meta`），`meta` 跨源容器：HN(author/comments/time)、GitHub(stars/language/topics/pushed_at)。
- 落盘 `knowledge/articles/{date}-{source}-{slug}.json`，维护 `index.json`（9 字段，按 `organized_at` 降序），丢弃项记 `_filtered-{date}.json`。

### 契约与校验（已实现）
- `schemas/article.schema.json`：12 字段 JSON Schema（单一事实来源），`additionalProperties: false`。
- `schemas/quality-rubric.json`：5 维质量评分契约（摘要质量 25 / 技术深度 25 / 格式规范 20 / 标签精度 15 / 空洞词 15，满分 100，A≥80 / B≥60 / C<60）。
- `hooks/validate_json.py`：schema 驱动结构校验 + 业务规则（source↔id 对应、score≥0.6 门控），零第三方依赖，exit 0/1/2。
- `hooks/check_quality.py`：rubric 驱动 5 维质量评分，存在 C 级 → exit 1。

### LLM 基础设施（已实现）
- `pipeline/model_client.py`：统一 LLM 客户端，OpenAI 兼容协议封装 DeepSeek / Qwen / OpenAI 三家；`LLM_PROVIDER` 切换（默认 deepseek），api key 回退（专属变量 → `LLM_API_KEY`），指数退避重试（≤3 次），token 用量统计与成本估算。依赖仅 `httpx>=0.27`。

### 决策与测试记录（已实现）
- `docs/decisions/2026-07-25-analyzer-organizer-course-alignment.md`（ADR-0001：课程对齐）。
- `docs/decisions/2026-07-27-pipeline-spec-hardening.md`（PRD-0002：errors 穷举 / category / meta / 分层筛选）。
- `sub-agent-test-log.md`：端到端三阶段流水线测试验证。

### 数据资产（已实现）
- `knowledge/raw/`：github + hn 多日 raw + errors；`knowledge/enriched/`：多日 enriched；`knowledge/articles/`：数十条知识条目 + `index.json` + `_filtered-{date}.json`。

## Decided Scope

1. **范围（已决）**：主体写"已实现"功能全景；附录写"声明但未实现"的漂移/差距清单（Telegram/飞书分发未实现、README.md/.env.example 缺失、AGENTS.md 技术栈写 minimax 与 model_client 实际的 DeepSeek/Qwen/OpenAI 不符）。

2. **落点（已决）**：产出文件放 `docs/` 下作为项目长期文档（`docs/baseline-prd.md`），与 `docs/decisions/` 平级，便于后续 agent 查阅；任务目录保留对该文件的引用。

3. **深度（已决）**：业务流程 + 代码实现两层——既写清三阶段数据流与角色/职责/契约，也覆盖关键代码实现（schema 字段契约、hooks 校验逻辑、pipeline/model_client provider 抽象）。

## Requirements

- R1：逆向梳理并固化已实现功能全景，覆盖 8 个板块：架构与编排 / Collector 采集 / Analyzer 分析 / Organizer 整理 / 契约与校验 / LLM 基础设施 / 决策与测试记录 / 数据资产。
- R2：业务流程与代码实现两层并行——既写数据流与角色契约，也写关键代码的实现要点。
- R3：每个功能板块标注来源文件路径（`file_path`），便于定位与核对。
- R4：附录含"差距与漂移清单"，列出声明但未实现 / 与实现不符的项。
- R5：只读梳理，不重构、不修改任何现有代码与数据。

## Out of Scope

- 不重构、不修改任何现有代码与数据。
- 不补写缺失的 README.md / .env.example（除非用户另行要求）。
- 不规划未来功能（差距清单仅记录现状漂移，不等于承诺实现）。

## Acceptance Criteria

- [x] 产出文件为 `docs/baseline-prd.md`。
- [x] 覆盖 R1 的 8 个板块，无遗漏。
- [x] 每个板块含来源文件路径（file_path），可定位。
- [x] 业务流程与代码实现两层均体现（R2）。
- [x] 附录含差距与漂移清单：Telegram/飞书分发未实现、README.md/.env.example 缺失、AGENTS.md 技术栈 minimax 与 model_client 实际 DeepSeek/Qwen/OpenAI 不符。
- [x] 内容与代码扫描结果一致，无虚构/夸大功能（交叉核对通过：五维权重 / 门控 0.6 / minLength 20 / grade 边界 / per_page=20）。
- [x] 全程只读，未改动任何现有代码与数据文件（git status 仅新增 docs/baseline-prd.md 与任务文件）。
