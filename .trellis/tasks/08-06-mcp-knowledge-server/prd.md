# 实现 MCP Server 搜索本地知识库

## Goal

实现 `mcp_knowledge_server.py`：一个 MCP Server，通过 JSON-RPC 2.0 over stdio 协议，让 AI 工具能搜索本地 `knowledge/articles/` 知识库（搜索 / 获取单条 / 统计）。仅用 Python 标准库，无第三方依赖。

## 课程要求原文

1. 读取 `knowledge/articles/` 下所有 JSON 文件。
2. 3 个 MCP 工具：`search_articles(keyword, limit=5)`（按关键词搜标题+摘要）、`get_article(article_id)`（按 ID 取完整内容）、`knowledge_stats()`（总数/来源分布/热门标签）。
3. JSON-RPC 2.0 over stdio。
4. 支持 MCP `initialize`、`tools/list`、`tools/call`。
5. 无第三方依赖，只用标准库。
6. 课程示例文章格式：`{id, title, source, summary, score, tags}`（score 0-10，source=github，id=github-20260326-001）。

## 兼容性比对（课程 vs 项目实际，已核查）

| 课程 | 项目实际 | 结论 |
| --- | --- | --- |
| 读 `knowledge/articles/` 所有 JSON | 目录存在，但含 8 个**非文章**文件：`index.json`、`_filtered-*.json`(5)、`test-good.json`、`hook-test.json` | ⚠️ 读取须排除非文章文件 |
| 文章格式 6 字段 `{id,title,source,summary,score,tags}` | **12 字段**契约（含 url/category/时间戳/meta），是课程超集 | ✅ 搜 title+summary 兼容 |
| `score: 7`（0-10 整数） | `relevance_score: 0.81`（0-1 float） | ⚠️ 用项目 `relevance_score`，不改名 |
| `source: "github"` | `github-hot-repos` / `hackernews-top` / `rss` | ⚠️ 用项目 source 枚举 |
| `id: "github-20260326-001"` | GitHub=`full_name`、HN=数字、RSS=guid/link | ✅ get 按实际 id 匹配 |
| JSON-RPC stdio / initialize / tools/list / tools/call / 无依赖 | 标准库 json+sys 可实现 | ✅ 完全兼容 |

**比对结论**：无阻碍性兼容问题。课程示例文章格式仅为「参考」，MCP Server 读取项目实际的 12 字段 article（其超集）。三个工具均可实现，仅需对齐项目实际字段：`relevance_score`（非 score）、source 枚举（非 github）、实际 id 格式，并在读取时排除非文章文件。

## Decided Scope

- 独立文件 `mcp_knowledge_server.py`，放**项目根目录**（用户定），纯标准库。
- 读取项目实际 12 字段 article；输出保留 `relevance_score` 与项目 source 枚举原值。
- **文章识别（用户定）**：字段校验——读入后须含非空 id/title/summary/source 才算文章，自动排除 index/_filtered/test/hook-test。

## Out of Scope

- 不改 knowledge/ 数据、不改 schema / pipeline.py / hooks。
- 不引入任何第三方依赖（不用 mcp SDK，纯手写 JSON-RPC）。
- 不实现 search/get/stats 之外的工具。

## Acceptance Criteria

- [x] 项目根目录新增 `mcp_knowledge_server.py`，纯标准库（AST 扫描仅 json/logging/sys/collections/pathlib，零第三方依赖）。
- [x] 支持 JSON-RPC 2.0 over stdio：`initialize` / `tools/list` / `tools/call` / `ping`；notification 不响应；未知 method -32601；缺参 -32602；非法 JSON -32700（管道实测全过）。
- [x] `search_articles(keyword, limit=5)`：搜 title+summary，title 命中优先、relevance_score 降序（实测 0.85→0.81）。
- [x] `get_article(article_id)`：按实际 id 精确匹配（兼容 full_name 含 `/`），返回完整 12 字段；未命中返回未找到提示。
- [x] `knowledge_stats()`：total=54 / by_source（github-hot-repos 29 / hackernews-top 16 / rss 9）/ top_tags top10 / avg_relevance_score=0.74。
- [x] 读取字段校验 + 文件名守卫识别文章，正确排除 index/_filtered/test/hook-test；加载 54 = index total_count 对账一致。
- [x] stdout 仅协议 JSON（日志走 stderr）；逐行 json.loads 成功。
- [x] 未改 knowledge/ / schemas/ / pipeline/ / hooks/ / .opencode/。
