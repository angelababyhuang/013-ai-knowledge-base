# 技术设计：mcp_knowledge_server.py

## 1. 总体形态

- **单文件** `mcp_knowledge_server.py`，放**项目根目录**（独立服务入口），纯 Python 标准库（`json` / `sys` / `pathlib` / `collections`），无第三方依赖。
- MCP Server：JSON-RPC 2.0 over stdio，AI 工具（如 Claude Desktop / opencode）通过 stdio 启动并调用。
- 数据源：`knowledge/articles/` 的 12 字段 article（项目实际格式，非课程 6 字段示例）。

## 2. 关键设计决策

### D1. stdio 帧格式：换行分隔 JSON
- MCP stdio 传输用 **newline-delimited JSON**（每条消息一行，非 LSP 的 Content-Length 帧）。
- 从 `sys.stdin` 逐行读，每行 `json.loads` 为一个 JSON-RPC 消息；响应写入 `sys.stdout` 一行一个 JSON + flush。
- 日志只写 `sys.stderr`（绝不污染 stdout 的协议流）。

### D2. 支持的 JSON-RPC 方法

| method | 处理 | 响应 |
| --- | --- | --- |
| `initialize` | 握手 | `result` = `{protocolVersion, serverInfo, capabilities:{tools:{}}}` |
| `notifications/initialized` | 客户端就绪通知（无 id） | 不响应（notification） |
| `ping` | 存活探测 | `result` = `{}` |
| `tools/list` | 列出工具 | `result` = `{tools: [3 个工具定义]}` |
| `tools/call` | 执行工具 | `result` = `{content:[{type:"text", text: ...}]}` |
| 其他 | 未知方法 | `error` = `{code:-32601, message:"Method not found"}` |

- 带 `id` 的是 request（须响应）；无 `id` 的是 notification（不响应）。
- JSON-RPC 错误码：-32700 parse error / -32600 invalid request / -32601 method not found / -32602 invalid params / -32603 internal error。

### D3. 数据加载与文章识别（字段校验）

- 启动时扫描 `knowledge/articles/*.json`（路径由 `__file__` 定位项目根，与 CWD 无关）。
- **字段校验识别真·文章**：读入后必须含非空 `id`、`title`、`summary`、`source` 四字段才收为文章；自动排除 `index.json` / `_filtered-*.json` / `test-good.json` / `hook-test.json`（它们不满足字段或结构）。
- 单文件解析失败（非 JSON / 非 dict）跳过，不中断。
- 加载到内存 `list[dict]` 缓存；提供 `reload` 内部函数（可选，暂不露为工具）。

### D4. 三个工具定义（tools/list 的 inputSchema）

1. **search_articles**
   - params：`keyword`(string, 必填)、`limit`(integer, 默认 5)
   - 逻辑：`keyword.lower()` 在 `title` 与 `summary` 中子串匹配；**title 命中优先**，同组内按 `relevance_score` 降序；取前 `limit` 条。
   - 返回：list of 精简 article `{id, title, source, url, summary, tags, relevance_score, category}`。

2. **get_article**
   - params：`article_id`(string, 必填)
   - 逻辑：按 `id` 精确匹配；命中返回**完整 12 字段**；未命中返回 `content` 含"未找到"提示文本（不抛 JSON-RPC error，属业务空结果）。

3. **knowledge_stats**
   - params：无
   - 返回：`{total, by_source, top_tags, avg_relevance_score}`：
     - `total`：文章总数
     - `by_source`：`{github-hot-repos: n, hackernews-top: n, rss: n}`（项目实际枚举）
     - `top_tags`：按出现次数降序的 top 10 `[{tag, count}]`
     - `avg_relevance_score`：平均相关性（两位小数）

### D5. tools/call 结果封装

- 工具返回值（dict/list）`json.dumps(..., ensure_ascii=False)` 后包成 MCP 标准：
  `result.content = [{"type":"text", "text": "<json 字符串>"}]`。
- 参数校验失败（缺 keyword/article_id、limit 非正）→ JSON-RPC `error -32602`。

## 3. 字段对齐（项目实际，非课程示例）

| 用途 | 项目字段 | 说明 |
| --- | --- | --- |
| 搜索文本 | `title` + `summary` | 课程同 |
| 评分 | `relevance_score`（0-1） | **非**课程 `score`(0-10)，保留原名原值 |
| 来源 | `source`（github-hot-repos/hackernews-top/rss） | **非**课程 `github` |
| id | GitHub=full_name / HN=数字 / RSS=guid | get 按实际 id 精确匹配 |
| 其余 | url/category/时间戳/meta | get_article 完整返回 |

## 4. 无依赖与边界

- 仅用标准库；**不引入** `mcp` SDK 或任何第三方包。
- 不改 `knowledge/`、`schemas/`、`pipeline/`、`hooks/`、`.opencode/`。
- 新增文件仅 `mcp_knowledge_server.py`（根目录）。

## 5. 验证方式（自验，不经真实 AI 工具）

- 用管道向进程 stdin 喂 JSON-RPC 消息，断言 stdout 响应：
  - `initialize` → 含 serverInfo/capabilities
  - `tools/list` → 3 个工具
  - `tools/call` search_articles（已知关键词）→ 命中且结构正确
  - `tools/call` get_article（已知 id）→ 完整 12 字段；未知 id → 未找到提示
  - `tools/call` knowledge_stats → total/by_source/top_tags 正确
  - 未知 method → -32601
- 确认 stdout 只有协议 JSON（无日志污染）。

## 6. 风险与缓解

- **stdout 污染**：所有 print/日志强制走 stderr；自验时检查 stdout 每行可 json.loads。
- **大目录性能**：54 个 article 全量读入内存，量级小无压力；不做过早优化。
- **id 含特殊字符**（GitHub full_name 含 `/`）：get_article 用字符串精确相等，不受影响。
