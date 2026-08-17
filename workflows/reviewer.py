#!/usr/bin/env python3
"""workflows/reviewer.py — 五维加权审核节点（审核 analyses，organize 之前）。

与 ``workflows/nodes.py`` 里既有 ``review_node`` 的关系（并存约定）：

- ``nodes.review_node``    审 **articles**（organize 之后，四维 LLM 评分）
- ``reviewer.review_node`` 审 **analyses**（organize 之前，本文件，五维
  加权评分，对照 state["plan"]）

二者同名不同物：本文件是课程第四节的新语义，图接线（review 提前到
organize 之前、条件边改挂本节点）属课程后续「组装」节内容，在此之前
``graph.py`` 继续使用 ``nodes.review_node``，互不影响。

课程需求要点：

- 五维评分（各 1-10 整数）与权重：summary_quality 25% / technical_depth
  25% / relevance 20% / originality 15% / formatting 15%
- **加权总分由代码重算**（不信任模型算术，先例 patterns/supervisor.py）
- 加权总分 >= 7.0 通过
- 只审前 ``MAX_REVIEW_ITEMS``(5) 条 analyses（控 token 消耗）
- ``temperature=0.1``（评分一致性）
- LLM 调用失败自动通过（fail-open，不阻塞流程）
- 返回 ``{review_passed, review_feedback, iteration, cost_tracker}``

LLM 调用走 ``workflows/model_client.py`` 的 ``chat_json`` / 
``accumulate_usage``（底层复用 pipeline 基建）。

用法::

    from workflows.reviewer import review_node
    update = review_node(state)   # state 需含 plan/analyses/iteration/cost_tracker

直接运行自测（需 ``.env``；好/坏两组 analyses 真实送审）::

    set -a && . ./.env && set +a && python workflows/reviewer.py
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from workflows.model_client import accumulate_usage, chat_json  # noqa: E402
from workflows.state import KBState, MAX_REVIEW_ITERATIONS  # noqa: E402

logger = logging.getLogger("workflows.reviewer")

# --------------------------------------------------------------------------- #
# 审核契约常量（课程需求的单一事实来源）
# --------------------------------------------------------------------------- #
# 五维评分及权重（合计 1.0）
REVIEW_DIMENSIONS: Dict[str, float] = {
    "summary_quality": 0.25,   # 摘要质量
    "technical_depth": 0.25,   # 技术深度
    "relevance": 0.20,         # 相关性
    "originality": 0.15,       # 原创性
    "formatting": 0.15,        # 格式规范
}

PASS_SCORE = 7.0          # 加权总分通过线
MAX_REVIEW_ITEMS = 5      # 只审前 N 条 analyses（控 token）
REVIEW_TEMPERATURE = 0.1  # 低温求评分一致性

_REVIEW_SYSTEM = "你是知识库质量审核员，只输出 JSON。"

_REVIEW_PROMPT = """对照任务计划，审核以下 AI 知识库的分析条目（organize 前的质量关口）。

任务计划：
{plan}

评分维度（各 1-10 整数）：
- summary_quality  摘要质量（准确、信息密度、100-200 字中文）
- technical_depth  技术深度（是否讲清技术机制而非营销话术）
- relevance        相关性（与 AI/LLM/Agent 领域及任务计划的匹配度）
- originality      原创性（信息是否独有，而非同质化转述）
- formatting       格式规范（summary/tags 结构、kebab-case 标签）

严格只输出如下 JSON（不要 markdown 围栏、不要自己算总分）：
{{
  "scores": {{"summary_quality": 0, "technical_depth": 0, "relevance": 0, "originality": 0, "formatting": 0}},
  "feedback": "整体改进建议；每条问题条目指明 id 与具体缺陷"
}}

待审核条目（前 {n} 条）：
{items_json}"""


# --------------------------------------------------------------------------- #
# 工具：分数钳位与加权重算
# --------------------------------------------------------------------------- #
def _clamp1to10(value: Any) -> int:
    """把模型输出的分数钳位到 1-10 整数；非法值回退中性分 5。

    先例：patterns/supervisor.py 的 _clamp1to10。
    """
    try:
        v = int(round(float(value)))
    except (TypeError, ValueError):
        return 5
    return max(1, min(10, v))


def compute_weighted_score(scores: Dict[str, Any]) -> float:
    """按 REVIEW_DIMENSIONS 权重代码重算加权总分（1-10 制，两位小数）。

    不信任模型算术：模型只给各维原始分，聚合永远在本函数做。
    缺失维度按中性分 5 计入，避免模型漏项导致总分虚低。
    """
    total = sum(
        _clamp1to10(scores.get(dim)) * weight
        for dim, weight in REVIEW_DIMENSIONS.items()
    )
    return round(total, 2)


def _build_feedback(parsed: Dict[str, Any], weighted: float,
                    clamped: Dict[str, int]) -> str:
    """合成不通过时的反馈：模型建议 + 代码算出的分维明细（可执行）。"""
    parts = [f"加权总分 {weighted:.2f}（通过线 {PASS_SCORE}），各维度："]
    parts += [f"  {dim} = {score} 分（权重 {weight:.0%}）"
              for dim, score, weight in
              ((d, clamped[d], w) for d, w in REVIEW_DIMENSIONS.items())]
    model_feedback = str(parsed.get("feedback") or "").strip()
    if model_feedback:
        parts.append(f"审核意见：{model_feedback}")
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# 审核节点
# --------------------------------------------------------------------------- #
def review_node(state: KBState) -> dict:
    """五维加权审核 state["analyses"]（前 5 条），返回部分状态更新。

    课程需求 8 条的实现对应：

    1. 审核对象 analyses（organize 之前，articles 此时不存在）
    2/3. 五维原始分由 LLM 给出，加权总分 ``compute_weighted_score``
       代码重算
    4. ``weighted >= PASS_SCORE(7.0)`` 才通过
    5. 只送审 ``analyses[:MAX_REVIEW_ITEMS]``
    6. ``temperature=REVIEW_TEMPERATURE(0.1)``
    7. LLM 调用失败 / 解析失败 / 空列表 → 一律自动通过（fail-open，
       不阻塞流程；iteration 仍 +1 保持循环语义完整）
    8. 返回 ``{review_passed, review_feedback, iteration, cost_tracker}``
    """
    analyses = state.get("analyses") or []
    plan = (state.get("plan") or "").strip() or "（无明确计划，按 AI/LLM/Agent 领域通用标准）"
    iteration = state.get("iteration", 0)
    tracker = dict(state.get("cost_tracker") or {})
    logger.info(
        "[ReviewerNode] 第 %d 轮审核 analyses（共 %d 条，送审前 %d 条）",
        iteration + 1, len(analyses), min(len(analyses), MAX_REVIEW_ITEMS),
    )

    def _pass(reason: str) -> dict:
        logger.warning("[ReviewerNode] %s，自动通过（fail-open）", reason)
        return {
            "review_passed": True,
            "review_feedback": "",
            "iteration": iteration + 1,
            "cost_tracker": tracker,
        }

    # 空列表：无东西可审；达到轮次上限：强制放行（与 nodes.review_node
    # 的 iteration >= 2 强制通过语义一致，防死循环）
    if not analyses:
        return _pass("analyses 为空")
    if iteration >= MAX_REVIEW_ITERATIONS - 1:
        return _pass(f"iteration={iteration} 达到上限，强制通过")

    # 报告式通信：只送审需要的字段，且只送前 5 条（控 token）
    sample = [
        {k: a.get(k) for k in ("id", "title", "summary", "tags", "relevance_score")}
        for a in analyses[:MAX_REVIEW_ITEMS]
    ]
    prompt = _REVIEW_PROMPT.format(
        plan=plan,
        n=len(sample),
        items_json=json.dumps(sample, ensure_ascii=False, indent=2),
    )

    try:
        parsed, usage = chat_json(
            prompt, system=_REVIEW_SYSTEM, temperature=REVIEW_TEMPERATURE
        )
        tracker = accumulate_usage(tracker, usage, node="reviewer_node")
    except Exception as exc:  # provider 重试耗尽 / 网络异常等
        logger.error("[ReviewerNode] LLM 调用失败: %s", exc)
        return _pass(f"LLM 调用失败（{exc}）")

    if not (isinstance(parsed, dict) and isinstance(parsed.get("scores"), dict)):
        return _pass("审核结果解析失败")

    clamped = {
        dim: _clamp1to10(parsed["scores"].get(dim))
        for dim in REVIEW_DIMENSIONS
    }
    weighted = compute_weighted_score(parsed["scores"])
    passed = weighted >= PASS_SCORE

    logger.info(
        "[ReviewerNode] 加权 %.2f（%s）passed=%s",
        weighted, clamped, passed,
    )
    return {
        "review_passed": passed,
        "review_feedback": (
            _build_feedback(parsed, weighted, clamped) if not passed else ""
        ),
        "iteration": iteration + 1,
        "cost_tracker": tracker,
    }


# --------------------------------------------------------------------------- #
# 自测入口：好 / 坏两组 analyses 真实送审 + 离线单测
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # 1) 离线：加权重算纯函数
    assert compute_weighted_score({}) == round(5 * 1.0, 2)  # 全缺失 → 中性 5.00
    assert compute_weighted_score(
        {"summary_quality": 10, "technical_depth": 10,
         "relevance": 10, "originality": 10, "formatting": 10}
    ) == 10.0
    assert compute_weighted_score(
        {"summary_quality": 2, "technical_depth": 2,
         "relevance": 2, "originality": 2, "formatting": 2}
    ) == 2.0
    # 越界/非法值被钳位：99 → 10，"abc" → 5
    assert compute_weighted_score(
        {"summary_quality": 99, "technical_depth": "abc",
         "relevance": 7, "originality": 7, "formatting": 7}
    ) == round(10 * 0.25 + 5 * 0.25 + 7 * 0.5, 2)
    logger.info("compute_weighted_score 离线单测 ✓")

    # 2) 离线：fail-open（chat_json 抛异常时自动通过）
    import workflows.reviewer as rv
    orig = rv.chat_json
    rv.chat_json = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("模拟断网"))
    try:
        update = rv.review_node({
            "plan": "测试", "sources": [], "articles": [],
            "analyses": [{"id": "x", "title": "t", "summary": "s",
                          "tags": ["a"], "relevance_score": 0.9}],
            "review_feedback": "", "review_passed": False,
            "iteration": 0, "cost_tracker": {},
        })
        assert update["review_passed"] is True
        logger.info("fail-open 单测 ✓（异常被吞、自动通过）")
    finally:
        rv.chat_json = orig

    # 3) 在线：好 / 坏两组 analyses 真实送审
    try:
        good_state: KBState = {
            "plan": "采集 LangGraph / Agent 工作流方向的高质量项目",
            "sources": [], "articles": [],
            "analyses": [{
                "id": "langgenius/dify", "title": "Dify",
                "summary": "Dify 是开源 LLM 应用开发平台，提供可视化编排、"
                           "RAG 管道、Agent 工具调用与模型托管，把 Agent "
                           "工作流的搭建从写代码降为拖拽配置，核心卖点是"
                           "对 LangChain 等框架的工程化封装与企业级权限。",
                "tags": ["llm-platform", "agent-workflow", "rag", "open-source"],
                "relevance_score": 0.92,
            }],
            "review_feedback": "", "review_passed": False,
            "iteration": 0, "cost_tracker": {},
        }
        bad_state: KBState = {
            "plan": "采集 LangGraph / Agent 工作流方向的高质量项目",
            "sources": [], "articles": [],
            "analyses": [{
                "id": "some/random-repo", "title": "random-repo",
                "summary": "一个不错的项目，很好用，大家快来看。",
                "tags": ["good"], "relevance_score": 0.3,
            }],
            "review_feedback": "", "review_passed": False,
            "iteration": 0, "cost_tracker": {},
        }
        print("\n=== 好条目审核 ===")
        good_update = review_node(good_state)
        print(f"passed={good_update['review_passed']}")
        print(f"feedback={good_update['review_feedback'] or '(空)'}")

        print("\n=== 坏条目审核 ===")
        bad_update = review_node(bad_state)
        print(f"passed={bad_update['review_passed']}")
        print(f"feedback=\n{bad_update['review_feedback'] or '(空)'}")
        print(f"\ncost_tracker={json.dumps(good_update['cost_tracker'] | bad_update['cost_tracker'], ensure_ascii=False)}")
    except RuntimeError as exc:
        logger.warning("跳过在线自测（未配置 API key）: %s", exc)
