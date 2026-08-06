# 执行计划：mcp_knowledge_server.py

## 交付物

- 新增：`mcp_knowledge_server.py`（项目根目录，纯标准库）。

## 前置确认

- 项目根目录；字段校验识别文章；读项目实际 12 字段 article。
- 纯标准库（json/sys/pathlib/collections）；无第三方依赖。
- 不改 knowledge/ / schemas/ / pipeline/ / hooks/ / .opencode/。

## 执行清单（按序）

- [ ] 1. 骨架：shebang、logging 走 stderr、项目根/knowledge 路径定位（`__file__`）。
- [ ] 2. 数据加载 `load_articles()`：扫 articles/*.json，字段校验（id/title/summary/source 非空），排除 index/_filtered/test，缓存内存。
- [ ] 3. 三工具实现：`search_articles`（title+summary 匹配、title 优先、relevance_score 降序、limit）、`get_article`（按 id 精确匹配，完整 12 字段 / 未找到提示）、`knowledge_stats`（total/by_source/top_tags/avg_relevance_score）。
- [ ] 4. JSON-RPC 层：stdio 逐行读 JSON → 路由 method → initialize/ping/tools/list/tools/call → result/error 封装；notification（无 id）不响应；未知 method -32601。
- [ ] 5. tools/list 的 3 个 inputSchema 定义；tools/call 结果包成 content[{type:text}]。
- [ ] 6. 自验：管道喂 JSON-RPC 消息断言 stdout；确认 stdout 仅协议 JSON。
- [ ] 7. 验收：三工具正确、错误码正确、无第三方依赖、未改其他文件。

## 验证命令

```bash
python -m py_compile mcp_knowledge_server.py
# 管道喂 JSON-RPC（initialize / tools/list / tools/call）
printf '%s\n' \
 '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
 '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
 '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"knowledge_stats","arguments":{}}}' \
 '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"search_articles","arguments":{"keyword":"agent","limit":3}}}' \
 '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"get_article","arguments":{"article_id":"mikehasa/agentacct"}}}' \
 | python3 mcp_knowledge_server.py
# 确认无第三方依赖
python3 -c "import ast,sys; t=ast.parse(open('mcp_knowledge_server.py').read()); print({n.names[0].name for n in ast.walk(t) if isinstance(n, ast.Import)})"
```

## 风险与回滚

- 风险：日志污染 stdout → 全部 print/logging 走 stderr，自验检查 stdout 可 json.loads。
- 风险：article id 含 `/`（GitHub full_name）→ 字符串精确匹配，无影响。
- 回滚：单文件，删除即可，无数据/契约影响。

## 完成前检查

- [ ] 仅用标准库（无 pip 依赖）。
- [ ] 三工具 + initialize/tools/list/tools/call 正确。
- [ ] stdout 仅协议 JSON；日志走 stderr。
- [ ] 未改 knowledge/ / schemas/ / pipeline/ / hooks/ / .opencode/。
- [ ] git status 仅新增 mcp_knowledge_server.py 与任务文件。
