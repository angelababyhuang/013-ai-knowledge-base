#!/usr/bin/env python3
"""Supervisor 监督模式：Worker 出报告、Supervisor 审核、不通过带反馈重做。

两个 LLM 角色：

- **Worker Agent**：接收任务（可附带审核反馈），输出 JSON 格式分析报告。
- **Supervisor Agent**：对 Worker 输出做质量审核，按准确性 / 深度 / 格式各打
  1-10 分，给出文字反馈。

审核循环（``supervisor``）：

- 通过（综合分 >= 7）→ 返回结果；
- 不通过 → 带反馈让 Worker 重做，最多 ``max_retries`` 轮；
- 超过 ``max_retries`` 仍未通过 → 强制返回最后一次结果 + 警告。

入口 ``supervisor(task, max_retries=3) -> dict``，返回::

    {
        "output": <Worker 最终 JSON 报告>,
        "attempts": <总尝试轮数>,
        "final_score": <最后一轮综合分 1-10>,
        "warning": <仅超限时出现>,
    }

LLM 调用复用 ``pipeline/model_client.py``：课程里的 ``chat() -> (text, usage)``
在本项目不存在，这里用 ``quick_chat(prompt) -> str``；课程的 ``chat_json`` 同样
不存在，由 ``_llm_json`` 用 ``quick_chat`` + ``json.loads`` 软实现，解析失败时
返回安全默认值。

用法::

    from patterns.supervisor import supervisor
    result = supervisor("分析 RAG 的三种主流检索策略")

也可直接运行自测::

    python patterns/supervisor.py
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

from pipeline.model_client import quick_chat  # noqa: E402

logger = logging.getLogger("supervisor")

PASS_THRESHOLD = 7

WORKER_SCHEMA_HINT = (
    '严格只输出如下 JSON（不要 markdown 围栏、不要多余文字）：\n'
    '{\n'
    '  "summary": "对该任务的中文分析摘要",\n'
    '  "key_points": ["关键点1", "关键点2", "关键点3"],\n'
    '  "conclusion": "结论"\n'
    '}'
)

SUPERVISOR_SCHEMA_HINT = (
    '严格只输出如下 JSON（不要 markdown 围栏、不要多余文字）：\n'
    '{\n'
    '  "accuracy": <1-10 整数，准确性>,\n'
    '  "depth": <1-10 整数，深度>,\n'
    '  "format": <1-10 整数，格式规范性>,\n'
    '  "feedback": "具体的改进建议，不通过时说清缺什么"\n'
    '}'
)


def _llm_json(prompt: str, fallback: Any) -> Any:
    """软 chat_json：让 LLM 只输出 JSON 并解析；失败返回 fallback。"""
    raw = quick_chat(prompt, temperature=0.0).strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].lstrip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("LLM JSON 解析失败，原始 %r，使用 fallback", raw)
        return fallback


# --------------------------------------------------------------------------- #
# Worker Agent
# --------------------------------------------------------------------------- #
def worker(task: str, feedback: str = "") -> Dict[str, Any]:
    """接收任务（可带审核反馈），输出 JSON 分析报告。

    解析失败时把原始文本包进 ``_raw`` 字段，交由 Supervisor 打低格式分，
    自然进入重做循环，而不是直接抛错中断流程。
    """
    prompt = f"你是一名技术分析 Worker。请完成以下任务并输出结构化报告。\n\n任务：{task}\n"
    if feedback:
        prompt += f"\n上一轮审核反馈（请针对性改进）：\n{feedback}\n"
    prompt += f"\n{WORKER_SCHEMA_HINT}"

    result = _llm_json(prompt, fallback=None)
    if isinstance(result, dict):
        return result
    return {"_raw": result, "summary": "", "key_points": [], "conclusion": ""}


# --------------------------------------------------------------------------- #
# Supervisor Agent
# --------------------------------------------------------------------------- #
def supervisor_review(task: str, worker_output: Dict[str, Any]) -> Dict[str, Any]:
    """对 Worker 输出做质量审核，返回含三维度分数与综合分的结果。

    综合分由代码计算（三维度均值），避免 LLM 自行聚合布尔值不可靠。
    """
    worker_text = json.dumps(worker_output, ensure_ascii=False)
    prompt = (
        "你是一名严格的 Supervisor。审核下面这份 Worker 报告的质量。\n\n"
        f"原始任务：{task}\n\n"
        f"Worker 报告：{worker_text}\n\n"
        "评分维度（各 1-10 整数）：准确性 / 深度 / 格式规范性。\n"
        f"{SUPERVISOR_SCHEMA_HINT}"
    )

    review = _llm_json(prompt, fallback={})
    if not isinstance(review, dict):
        review = {}

    def _clamp1to10(value: Any) -> int:
        try:
            v = int(round(float(value)))
        except (TypeError, ValueError):
            return 5
        return max(1, min(10, v))

    accuracy = _clamp1to10(review.get("accuracy"))
    depth = _clamp1to10(review.get("depth"))
    fmt = _clamp1to10(review.get("format"))
    score = round((accuracy + depth + fmt) / 3)

    return {
        "accuracy": accuracy,
        "depth": depth,
        "format": fmt,
        "score": score,
        "passed": score >= PASS_THRESHOLD,
        "feedback": review.get("feedback", "") or "",
    }


# --------------------------------------------------------------------------- #
# 监督循环
# --------------------------------------------------------------------------- #
def supervisor(task: str, max_retries: int = 3) -> Dict[str, Any]:
    """监督主循环：Worker 出报告 → Supervisor 审核 → 不通过带反馈重做。

    Args:
        task: 交给 Worker 完成的任务描述。
        max_retries: 最大尝试轮数（含首次）。

    Returns:
        ``{"output", "attempts", "final_score", "warning"(可选)}``。
    """
    task = (task or "").strip()
    if not task:
        return {"output": None, "attempts": 0, "final_score": 0,
                "warning": "空任务，未执行"}

    feedback = ""
    output: Dict[str, Any] = {}
    final_score = 0
    attempts = 0

    for attempt in range(1, max_retries + 1):
        attempts = attempt
        logger.info("[round %d/%d] Worker 执行任务...", attempt, max_retries)
        output = worker(task, feedback=feedback)

        logger.info("[round %d/%d] Supervisor 审核...", attempt, max_retries)
        review = supervisor_review(task, output)
        final_score = review["score"]

        logger.info(
            "[round %d/%d] 综合 %d（准确 %d / 深度 %d / 格式 %d）passed=%s",
            attempt, max_retries, final_score,
            review["accuracy"], review["depth"], review["format"],
            review["passed"],
        )

        if review["passed"]:
            return {"output": output, "attempts": attempts,
                    "final_score": final_score}

        feedback = review["feedback"]

    warning = (
        f"达到最大重试次数 {max_retries} 仍未通过审核（最后综合分 {final_score}），"
        "强制返回最后一次结果"
    )
    logger.warning(warning)
    return {"output": output, "attempts": attempts,
            "final_score": final_score, "warning": warning}


# --------------------------------------------------------------------------- #
# 自测入口
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    sample_task = "对比分析 RAG 中密集检索（dense retrieval）与稀疏检索（sparse retrieval）的优劣"
    print("=" * 70)
    print("Task:", sample_task)
    print("=" * 70)
    try:
        result = supervisor(sample_task, max_retries=3)
        print("\n=== 最终结果 ===")
        print(f"attempts     : {result['attempts']}")
        print(f"final_score  : {result['final_score']}")
        if "warning" in result:
            print(f"warning      : {result['warning']}")
        print("output       :")
        print(json.dumps(result["output"], ensure_ascii=False, indent=2))
    except Exception as exc:
        logger.error("监督流程异常: %s", exc)
        print(f"执行失败：{exc}")
