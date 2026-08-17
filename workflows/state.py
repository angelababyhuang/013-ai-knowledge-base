#!/usr/bin/env python3
"""workflows/state.py — LangGraph 知识库工作流的共享状态定义。

用 ``TypedDict`` 定义 ``KBState``，作为整个 LangGraph 图中所有节点
（采集 → 分析 → 整理 → 审核 → 归档）读写的唯一状态载体，取代
节点间传裸 dict / 靠文件中转的松散通信方式。

与本项目既有实现的对应关系：

- ``sources``      ← pipeline/pipeline.py Step1 产出（knowledge/raw/）
- ``analyses``     ← Step2 产出（knowledge/enriched/）
- ``articles``     ← Step3 门控去重后的通过集（knowledge/articles/）
- ``review_feedback`` / ``review_passed`` / ``iteration``
                  ← patterns/supervisor.py「Worker 出报告、Supervisor
                     带反馈重做」循环的状态化（PASS_THRESHOLD=7、
                     max_retries=3，即 iteration 上限 3）
- ``cost_tracker`` ← model_client.py 各次 LLM 调用的 token 用量汇总

「报告式通信」原则：每个字段存的是**结构化摘要**（带 id/url/score 的
精简条目），不是网页原文、完整 RSS XML 之类的原始数据；节点间只交换
下游真正需要的结论性信息，控制状态体积。

LangGraph 语义说明：普通 TypedDict 字段在图中是「最后写入覆盖」语义
（last-write-wins）；若后续课程节点需要跨节点累加 list，应改写为
``Annotated[list[dict], operator.add]``。本文件遵循课程要求先使用
普通 TypedDict。

用法::

    from workflows.state import KBState, MAX_REVIEW_ITERATIONS

    state: KBState = {
        "plan": "",
        "sources": [], "analyses": [], "articles": [],
        "review_feedback": "", "review_passed": False,
        "iteration": 0, "cost_tracker": {},
    }

也可直接运行本模块做自测::

    python workflows/state.py
"""

from typing import TypedDict

# 审核循环上限，与 patterns/supervisor.py 的 max_retries=3 对齐
MAX_REVIEW_ITERATIONS = 3


class KBState(TypedDict):
    """LangGraph 知识库工作流的共享状态（报告式通信契约）。"""

    # 本次运行的任务计划文案：描述采集主题 / 整理目标 / 质量期望，
    # 供 reviewer 等节点对照审核（"计划是什么"），空字符串表示无约束
    plan: str

    # 采集到的原始数据摘要列表；元素对齐 knowledge/raw/ 的 item 结构：
    # {id, title, url, source, collected_at, ...来源特有字段}
    sources: list[dict]

    # LLM 分析后的结构化结果；元素对齐 knowledge/enriched/ 的 item 结构：
    # 在 sources 元素基础上补 {summary, tags, relevance_score, analyzed_at}
    analyses: list[dict]

    # 格式化、去重后通过门控的知识条目；元素对齐 schemas/article.schema.json
    # 的 12 字段契约（id/title/url/category/source/collected_at/summary/
    # tags/relevance_score/analyzed_at/organized_at/meta）
    articles: list[dict]

    # 审核反馈意见：Supervisor 审核不通过时写给上游节点的改进建议文本，
    # 空字符串表示尚无反馈或已通过
    review_feedback: str

    # 审核是否通过：True 时工作流走向归档节点，False 时带反馈重做
    review_passed: bool

    # 当前审核循环次数，从 0 起计，达到 MAX_REVIEW_ITERATIONS(3) 后
    # 强制放行，防止无限循环
    iteration: int

    # Token 用量追踪：{"total_tokens": int, "total_cost": float,
    # "calls": int, "by_node": {节点名: token 数}} 形状的汇总字典
    cost_tracker: dict


# --------------------------------------------------------------------------- #
# 自测入口
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    state: KBState = {
        "plan": "",
        "sources": [],
        "analyses": [],
        "articles": [],
        "review_feedback": "",
        "review_passed": False,
        "iteration": 0,
        "cost_tracker": {},
    }

    print("KBState 字段：")
    for key in KBState.__annotations__:
        print(f"  {key:<16} -> {state[key]!r}")

    from langgraph.graph import StateGraph

    graph = StateGraph(KBState)
    print(f"\nLangGraph StateGraph(KBState) 构建成功（langgraph 兼容 ✓）")
    print(f"审核循环上限：MAX_REVIEW_ITERATIONS = {MAX_REVIEW_ITERATIONS}")
