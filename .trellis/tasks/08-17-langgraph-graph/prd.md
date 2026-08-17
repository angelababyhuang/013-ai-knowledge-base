# PRD：LangGraph 课程 — 组装 workflows/graph.py 工作流图

## 背景

课程第三节（前两节已完成 `workflows/state.py`、`workflows/nodes.py` + `workflows/model_client.py`）。
本节把 5 个节点组装成真正的 LangGraph 图，接入审核循环的条件分支。

## 需求（课程原文）

1. 使用 `langgraph.graph` 的 `StateGraph`, `END`
2. 导入 `workflows/nodes.py` 的 5 个节点函数
3. 导入 `workflows/state.py` 的 `KBState`
4. 线性边：collect → analyze → organize → review
5. 条件边：review 之后按 `review_passed` 分支
   - True → save → END
   - False → organize（回到整理节点修正）
6. 入口点：collect
7. `build_graph()` 返回编译后的 app
8. `if __name__ == "__main__"` 流式执行并打印每个节点的关键输出

课程指定的真实 LangGraph API：`StateGraph(KBState)` / `add_node` / `add_edge` /
`add_conditional_edges(source, router_fn, {"key": "target"})` / `set_entry_point` /
`add_edge("save", END)` / `compile()`。

## 兼容性结论（已核实）

- langgraph 1.2.11 的 `add_conditional_edges` 签名与课程 path_map 形式一致 ✓
- `app.stream()` 默认 updates 模式，逐节点 yield `{节点名: 部分更新}` ✓
- 审核循环图深 ≤ 9 步 < 默认 recursion_limit 25 ✓
- 节点/状态契约已在 nodes.py、state.py 落地，本任务只做接线

## 验收标准

1. `build_graph()` 返回可 invoke/stream 的编译图，节点名与边符合 4-6 条
2. `python workflows/graph.py`（需 `.env`，建议 `WORKFLOWS_DRY_RUN=1`）流式跑通
   全流程，每个节点打印关键输出
3. 审核不通过时走 review → organize 修正回路；iteration 上限语义不变
   （review_node 内 `iteration >= 2` 强制通过，图无死循环）
4. 不改动 state.py / nodes.py / model_client.py 的既有契约

## 非目标

- checkpointer 持久化、并行 Send、子图（后续课程内容）
- 真实落盘（默认 DRY_RUN；真实写盘沿用 save_node 既有幂等逻辑）
