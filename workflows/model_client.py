#!/usr/bin/env python3
"""workflows/model_client.py — 课程签名到项目 LLM 基建的薄适配层。

课程（LangGraph 阶段）要求节点通过本模块调用 LLM：

- ``chat(prompt, system=...) -> (text, usage)``
- ``chat_json(prompt, system=...) -> (parsed_json, usage)``
- ``accumulate_usage(tracker, usage)``

项目已有 ``pipeline/model_client.py`` 提供 provider 基建（DeepSeek/Qwen/
OpenAI 多 provider 切换、指数退避重试、token 计价），但只暴露
``quick_chat() -> str``——**丢弃了 usage**，无法支撑 KBState.cost_tracker。
本模块不重复造 HTTP 轮子：底层复用 ``create_provider`` + ``chat_with_retry``，
对外补齐课程要求的三签名（含 system 消息支持与 JSON 软解析）。

与 ``patterns/*`` 里各自内联 ``_llm_json`` 的做法相比，这里把
「带 usage 的调用 + JSON 解析」收口为共享实现，避免第三份拷贝。

成本估算口径：``accumulate_usage`` 未显式传 provider 时按环境变量
``LLM_PROVIDER``（默认 deepseek）的计价表估算，与实际调用方一致。

用法::

    from workflows.model_client import chat, chat_json, accumulate_usage

    text, usage = chat("你好", system="你是知识库助手")
    data, usage2 = chat_json('返回 {"ok": true}')
    tracker = {"total_tokens": 0, "total_cost": 0.0, "calls": 0, "by_node": {}}
    accumulate_usage(tracker, usage, node="analyze")

也可直接运行本模块做自测::

    python workflows/model_client.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from pipeline.model_client import (  # noqa: E402
    DEFAULT_PROVIDER,
    Usage,
    chat_with_retry,
    create_provider,
    estimate_cost,
)

logger = logging.getLogger("workflows.model_client")

# chat_json 解析失败时的最大尝试次数（首次 + 严格重试）
JSON_MAX_ATTEMPTS = 2


def _build_messages(prompt: str, system: Optional[str]) -> list[Dict[str, str]]:
    """组装 OpenAI 格式消息：system（可选）+ user。"""
    messages: list[Dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return messages


def chat(
    prompt: str,
    system: Optional[str] = None,
    temperature: float = 0.7,
    **kwargs: Any,
) -> Tuple[str, Usage]:
    """带 usage 的单轮调用，返回 ``(模型文本, token 用量)``。

    Args:
        prompt: 用户提示词。
        system: 可选 system 消息（角色设定 / 输出格式约束）。
        temperature: 采样温度。
        **kwargs: 透传给 provider（如 model、max_tokens）。

    Returns:
        ``(text, usage)`` 二元组，usage 为 pipeline.model_client.Usage。
    """
    provider = create_provider()
    resp = chat_with_retry(
        provider,
        _build_messages(prompt, system),
        temperature=temperature,
        **kwargs,
    )
    return resp.content, resp.usage


def _strip_code_fence(raw: str) -> str:
    """剥离 `````json ... ``` `` 代码围栏，返回可解析的 JSON 文本。"""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    return text.strip()


def chat_json(
    prompt: str,
    system: Optional[str] = None,
    temperature: float = 0.3,
    **kwargs: Any,
) -> Tuple[Optional[Any], Usage]:
    """要求 LLM 只输出 JSON 并解析，返回 ``(解析结果, token 用量)``。

    解析失败时带「只输出 JSON」的严格提示重试一次；仍失败则返回
    ``(None, usage)``，由调用方决定兜底策略（如按低分门控丢弃），
    不在图节点里抛异常中断工作流。

    Args:
        prompt: 用户提示词（应包含期望的 JSON 结构说明）。
        system: 可选 system 消息。
        temperature: 低温（默认 0.3）利于稳定输出 JSON。
        **kwargs: 透传给 provider。

    Returns:
        ``(parsed_json 或 None, usage)``。
    """
    last_usage = Usage()
    current_prompt = prompt
    for attempt in range(1, JSON_MAX_ATTEMPTS + 1):
        raw, last_usage = chat(
            current_prompt, system=system, temperature=temperature, **kwargs
        )
        try:
            return json.loads(_strip_code_fence(raw)), last_usage
        except json.JSONDecodeError:
            logger.warning(
                "chat_json 第 %d/%d 次解析失败，原始 %r", attempt,
                JSON_MAX_ATTEMPTS, raw[:120],
            )
            current_prompt = (
                prompt + "\n\n注意：上一次输出不是合法 JSON，"
                "这次严格只输出 JSON 本体，不要 markdown 围栏和任何解释文字。"
            )
    return None, last_usage


def accumulate_usage(
    tracker: dict,
    usage: Usage,
    node: str = "unknown",
    provider: Optional[str] = None,
) -> dict:
    """把一次调用的 usage 累加进 cost_tracker，返回更新后的 tracker。

    tracker 形状（对齐 workflows/state.py 的 cost_tracker 契约）::

        {
            "total_tokens": int,      # 累计 token
            "total_cost": float,      # 累计估算成本（USD）
            "calls": int,             # 累计调用次数
            "by_node": {节点名: int},  # 按节点聚合的 token 数
        }

    Args:
        tracker: 状态里的 cost_tracker（可传入后丢弃，函数返回新字典）。
        usage: 单次调用的 Usage。
        node: 发起调用的节点名，用于 by_node 聚合。
        provider: 计价 provider；缺省按 LLM_PROVIDER 环境变量解析。

    Returns:
        更新后的 tracker（浅拷贝，不原地修改入参）。
    """
    updated = {
        "total_tokens": tracker.get("total_tokens", 0) + usage.total_tokens,
        "total_cost": round(
            tracker.get("total_cost", 0.0)
            + estimate_cost(
                usage, provider or os.getenv("LLM_PROVIDER", DEFAULT_PROVIDER)
            ),
            6,
        ),
        "calls": tracker.get("calls", 0) + 1,
        "by_node": {
            **tracker.get("by_node", {}),
            node: tracker.get("by_node", {}).get(node, 0) + usage.total_tokens,
        },
    }
    return updated


# --------------------------------------------------------------------------- #
# 自测入口
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    tracker: dict = {"total_tokens": 0, "total_cost": 0.0, "calls": 0, "by_node": {}}

    # 1) 离线部分：accumulate_usage 纯函数自测
    fake = Usage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
    tracker = accumulate_usage(tracker, fake, node="test")
    tracker = accumulate_usage(tracker, fake, node="test")
    assert tracker["total_tokens"] == 300 and tracker["calls"] == 2
    assert tracker["by_node"]["test"] == 300
    logger.info("accumulate_usage 自测通过: %s", tracker)

    # 2) 在线部分：chat / chat_json（未配 key 时跳过）
    try:
        text, usage = chat("用一句话解释什么是 LangGraph")
        tracker = accumulate_usage(tracker, usage, node="chat")
        logger.info("chat 返回 %d 字，usage=%s", len(text), usage)

        data, usage2 = chat_json(
            '只输出 JSON：{"ok": true, "n": 42}',
            system="你是只输出 JSON 的助手",
        )
        tracker = accumulate_usage(tracker, usage2, node="chat_json")
        logger.info("chat_json 返回 %r", data)
        assert data == {"ok": True, "n": 42}, f"解析结果不符: {data}"
        logger.info("cost_tracker 汇总: %s", tracker)
    except RuntimeError as exc:
        logger.warning("跳过在线自测（未配置 API key）: %s", exc)
