# PRD：LangGraph 课程 — workflows/reviewer.py 五维加权审核节点

## 背景

课程第四节。前三节产物：`workflows/state.py`（KBState）、`workflows/nodes.py` + `model_client.py`（5 节点）、`workflows/graph.py`（图组装）。
本节按课程新要求实现**审核 analyses**（organize 之前）的 `review_node`，放独立文件 `workflows/reviewer.py`。

## 需求（课程原文摘要）

1. 审核对象是 `state["analyses"]`（不是 articles）
2. 五维评分（1-10）：summary_quality 25% / technical_depth 25% / relevance 20% / originality 15% / formatting 15%
3. 加权总分**代码重算**（不信任模型算术）
4. 加权总分 >= 7.0 通过
5. 只审前 5 条 analyses（控 token）
6. temperature=0.1
7. LLM 调用失败自动通过（不阻塞流程）
8. 返回 `{review_passed, review_feedback, iteration, cost_tracker}`
9. 依赖：`chat_json(prompt, system=..., temperature=...)`、`accumulate_usage`、KBState 的 `plan/analyses/iteration/cost_tracker`

## 兼容性结论（已核实）

- `chat_json` 支持 temperature ✓；`accumulate_usage` 就绪 ✓
- KBState 缺 `plan` 字段 → 本任务补 `plan: str`，同步更新 graph.py / nodes.py 状态构造点
- `nodes.review_node`（审 articles）与本节 `reviewer.review_node`（审 analyses）同名不同物：
  **并存不动图**，graph.py 仍用 nodes.review_node，待课程接线节再切换

## 验收标准

1. `reviewer.review_node(state)` 按课程 8 条需求工作，加权分代码重算、>= 7.0 门控
2. KBState 新增 `plan` 字段后，`python workflows/graph.py` / `nodes.py` 冒烟与既有测试不破坏
3. LLM 失败/解析失败路径 fail-open（自动通过），不抛错
4. 真实验证：好/坏两组 analyses 的审核结果符合预期（坏条目被拒 + 反馈可执行）

## 非目标

- 不改 graph.py 的边/节点接线（课程后续内容）
- 不删除/改名 nodes.review_node
