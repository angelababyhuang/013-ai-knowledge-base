#!/usr/bin/env python3
"""workflows/graph.py — 把 5 个节点组装成 LangGraph 知识库工作流图。

图结构（课程第四节接线：review 切换到 workflows/reviewer.py，审 analyses）::

                        ┌──────────────────────────────┐
                        │      （审核不通过，带反馈）      │
                        ▼                              │
     collect → analyze → review ──passed──→ organize → save → END
     (入口)             │                        ▲
                       └─ review_passed=False ────┘
                          时回到 analyze 重分析

- 线性边：``collect → analyze → review``、``organize → save``
- 条件边：``review`` 之后由 ``_route_after_review`` 读 ``review_passed``
  分支：True → ``organize``（整理通过审核的 analyses）；False → ``analyze``
  （带 feedback 重新分析——reviewer 审的是 analyses，反馈作用到源头）
- review 语义：``workflows/reviewer.py`` 的五维加权审核（25/25/20/15/15，
  加权总分代码重算，>= 7.0 通过，只审前 5 条，temperature=0.1，
  LLM 失败 fail-open 自动通过）。旧版 nodes.review_node（审 articles）
  保留在 nodes.py 但不再接线
- 循环安全：reviewer 内 ``iteration >= 2 强制通过``（业务级刹车）+
  LangGraph 默认 recursion_limit=25（图级急刹车），双层防死循环

使用真实 LangGraph API（1.2.11）::

    from langgraph.graph import StateGraph, END
    graph = StateGraph(KBState)
    graph.add_node("collect", collect_node)
    graph.add_edge("organize", "review")
    graph.add_conditional_edges("review", _route_after_review,
                                {"save": "save", "revise": "organize"})
    graph.set_entry_point("collect")
    graph.add_edge("save", END)
    app = graph.compile()

流式执行：``app.stream()`` 默认 updates 模式，每个节点执行完 yield
``{节点名: 部分状态更新}``，主程序据此打印每个节点的关键输出。

用法::

    from workflows.graph import build_graph
    app = build_graph()
    for chunk in app.stream(initial_state):
        print(chunk)

直接运行（需 ``.env`` 提供 LLM key；建议 ``WORKFLOWS_DRY_RUN=1`` 防止
污染 knowledge/articles/）::

    set -a && . ./.env && set +a && WORKFLOWS_DRY_RUN=1 \\
        python workflows/graph.py --limit 2
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Literal

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from langgraph.graph import END, StateGraph  # noqa: E402

from workflows.nodes import (  # noqa: E402
    analyze_node,
    collect_node,
    organize_node,
    save_node,
)
from workflows.reviewer import review_node  # noqa: E402
from workflows.state import KBState  # noqa: E402

logger = logging.getLogger("workflows.graph")


# --------------------------------------------------------------------------- #
# 条件边路由函数
# --------------------------------------------------------------------------- #
def _route_after_review(state: KBState) -> Literal["organize", "revise"]:
    """review 出口的路由：读 review_passed 决定整理归档还是带反馈重分析。

    reviewer 审的是 analyses（organize 之前），所以未通过时反馈要作用到
    源头 analyze——返回 "revise" 映射回 analyze；通过则进入 organize。

    返回值是 path_map 的键（"organize" / "revise"），由 add_conditional_edges
    映射到目标节点（organize / analyze）。
    """
    if state.get("review_passed"):
        return "organize"
    logger.info(
        "[Route] 审核未通过（iteration=%d），回到 analyze 按反馈重分析",
        state.get("iteration", 0),
    )
    return "revise"


# --------------------------------------------------------------------------- #
# 组装与编译
# --------------------------------------------------------------------------- #
def build_graph():
    """组装并编译知识库工作流图，返回可 invoke / stream 的 app。"""
    graph = StateGraph(KBState)

    # 节点注册
    graph.add_node("collect", collect_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("organize", organize_node)
    graph.add_node("review", review_node)
    graph.add_node("save", save_node)

    # 线性边：collect → analyze → review；organize → save
    graph.set_entry_point("collect")
    graph.add_edge("collect", "analyze")
    graph.add_edge("analyze", "review")

    # 条件边：review 之后按 review_passed 分支
    graph.add_conditional_edges(
        "review",
        _route_after_review,
        {"organize": "organize", "revise": "analyze"},
    )

    # 收尾：organize → save → END
    graph.add_edge("organize", "save")
    graph.add_edge("save", END)

    return graph.compile()


# --------------------------------------------------------------------------- #
# 流式执行：打印每个节点的关键输出
# --------------------------------------------------------------------------- #
def _print_update(node: str, update: dict) -> None:
    """从节点的部分状态更新里提取关键信息打印（updates 流式模式）。"""
    if node == "collect":
        sources = update.get("sources") or []
        print(f"  [collect] 采集 {len(sources)} 条")
        for s in sources[:3]:
            print(f"    - {s.get('title')} (★{s.get('stars')})")
    elif node == "analyze":
        analyses = update.get("analyses") or []
        scores = [a.get("relevance_score") for a in analyses]
        print(f"  [analyze] 分析 {len(analyses)} 条，评分 {scores}")
    elif node == "organize":
        articles = update.get("articles") or []
        print(f"  [organize] 通过门控+去重 {len(articles)} 条")
    elif node == "review":
        print(
            f"  [review] passed={update.get('review_passed')} "
            f"iteration={update.get('iteration')}"
        )
        if update.get("review_feedback"):
            print(f"    feedback: {update['review_feedback'][:80]}…")
    elif node == "save":
        print(f"  [save] 完成（详见日志）")


def run(limit: int) -> KBState:
    """流式执行整个工作流，逐节点打印关键输出，返回最终状态。"""
    app = build_graph()

    initial_state: KBState = {
        "plan": "",
        "sources": [],
        "analyses": [],
        "articles": [],
        "review_feedback": "",
        "review_passed": False,
        "iteration": 0,
        "cost_tracker": {},
    }

    import workflows.nodes as nodes_mod

    nodes_mod.DEFAULT_LIMIT = limit  # --limit 覆盖采集量

    final_state: KBState = dict(initial_state)  # type: ignore[assignment]
    print("=== 工作流开始（流式） ===")
    for chunk in app.stream(initial_state):
        for node, update in chunk.items():
            _print_update(node, update or {})
            if isinstance(update, dict):
                final_state.update(update)  # type: ignore[arg-type]

    print("=== 工作流结束 ===")
    print(f"最终：articles={len(final_state['articles'])}，"
          f"iteration={final_state['iteration']}，"
          f"cost={json.dumps(final_state['cost_tracker'], ensure_ascii=False)}")
    return final_state


# --------------------------------------------------------------------------- #
# 自测入口
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="LangGraph 知识库工作流")
    parser.add_argument("--limit", type=int, default=2, help="采集条数（默认 2，控成本）")
    args = parser.parse_args()

    run(args.limit)
