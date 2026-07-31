#!/usr/bin/env python3
"""统一 LLM 调用客户端。

封装 DeepSeek / Qwen / OpenAI 三家模型提供商，对外提供统一调用接口。
三家的 Chat Completions 接口均兼容 OpenAI 协议，因此底层复用同一个
``OpenAICompatibleProvider`` 实现，仅 ``base_url`` / 默认模型 / 计价不同，
后续新增 provider 只需在 ``PROVIDER_CONFIGS`` 增加一条配置。

provider 由环境变量 ``LLM_PROVIDER`` 切换（默认 ``deepseek``），
API key 优先读各 provider 专属变量（如 ``DEEPSEEK_API_KEY``），
缺失时回退到统一的 ``LLM_API_KEY``。

``PROVIDER_CONFIGS`` 中 ``pricing`` 的单位是「每 100 万 token 的 USD 单价」，
仅用于本地成本估算，可按官方最新调价自行更新。

典型用法::

    from pipeline.model_client import quick_chat
    answer = quick_chat("用一句话解释什么是 Agent")

    from pipeline.model_client import create_provider, chat_with_retry
    provider = create_provider()
    resp = chat_with_retry(provider, [{"role": "user", "content": "你好"}])
    logger.info("%s tokens=%d", resp.content, resp.usage.total_tokens)
"""

from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "deepseek"
DEFAULT_TIMEOUT = 60.0
MAX_RETRIES = 3
BACKOFF_BASE = 1.0

PROVIDER_CONFIGS: Dict[str, Dict[str, Any]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "api_key_env": "DEEPSEEK_API_KEY",
        "pricing": {"input": 0.27, "output": 1.10},
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
        "api_key_env": "QWEN_API_KEY",
        "pricing": {"input": 0.40, "output": 1.20},
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "api_key_env": "OPENAI_API_KEY",
        "pricing": {"input": 0.15, "output": 0.60},
    },
}


@dataclass
class Usage:
    """单次调用的 token 用量统计。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    """LLM 调用的统一返回结构。

    Attributes:
        content: 模型生成的文本内容。
        usage: 本次调用的 token 用量。
        model: 实际使用的模型名。
        provider: 实际使用的 provider 名（deepseek / qwen / openai）。
    """

    content: str
    usage: Usage
    model: str = ""
    provider: str = ""


class LLMProvider(ABC):
    """模型 provider 的抽象接口。"""

    @abstractmethod
    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        """发起一次 chat completion 调用。

        Args:
            messages: OpenAI 格式的消息列表。
            model: 模型名，为空时使用 provider 默认模型。
            temperature: 采样温度。
            **kwargs: 透传给底层 API 的额外参数（如 max_tokens、top_p）。

        Returns:
            统一的 LLMResponse。
        """
        raise NotImplementedError


class OpenAICompatibleProvider(LLMProvider):
    """OpenAI 兼容协议的统一实现。

    适用于所有暴露 ``POST {base_url}/chat/completions``、
    且请求/响应遵循 OpenAI 格式的 provider。

    Attributes:
        provider: provider 标识名。
        api_key: API 密钥。
        base_url: OpenAI 兼容 API 根地址。
        default_model: 未显式指定 model 时使用的默认模型。
        timeout: 单次请求超时秒数。
    """

    def __init__(
        self,
        provider: str,
        api_key: str,
        base_url: str,
        default_model: str,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.timeout = timeout

    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        """见 LLMProvider.chat。"""
        used_model = model or self.default_model
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": used_model,
            "messages": messages,
            "temperature": temperature,
            **kwargs,
        }
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        usage_raw = data.get("usage") or {}
        usage = Usage(
            prompt_tokens=int(usage_raw.get("prompt_tokens", 0)),
            completion_tokens=int(usage_raw.get("completion_tokens", 0)),
            total_tokens=int(usage_raw.get("total_tokens", 0)),
        )
        if usage.total_tokens == 0:
            usage.total_tokens = usage.prompt_tokens + usage.completion_tokens
        logger.debug(
            "provider=%s model=%s prompt=%d completion=%d",
            self.provider,
            used_model,
            usage.prompt_tokens,
            usage.completion_tokens,
        )
        return LLMResponse(content=content, usage=usage, model=used_model, provider=self.provider)


def create_provider(
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> LLMProvider:
    """按环境变量或参数构造一个 provider 实例。

    Args:
        provider: provider 名；为空时读环境变量 ``LLM_PROVIDER``，再为空取默认。
        api_key: 显式传入的密钥；为空时先读 provider 专属变量（如
            ``DEEPSEEK_API_KEY``），再回退到统一的 ``LLM_API_KEY``。
        timeout: 单次请求超时秒数。

    Returns:
        构造好的 LLMProvider 实例。

    Raises:
        ValueError: provider 名不在 ``PROVIDER_CONFIGS`` 中。
        RuntimeError: 未找到任何可用 API key。
    """
    provider_name = (provider or os.getenv("LLM_PROVIDER", DEFAULT_PROVIDER)).lower()
    if provider_name not in PROVIDER_CONFIGS:
        raise ValueError(
            f"未知的 provider: {provider_name!r}，可选: {sorted(PROVIDER_CONFIGS)}"
        )
    config = PROVIDER_CONFIGS[provider_name]
    if api_key is None:
        api_key = os.getenv(config["api_key_env"]) or os.getenv("LLM_API_KEY")
    if not api_key:
        raise RuntimeError(
            f"未配置 API key：请设置 {config['api_key_env']}（或 LLM_API_KEY）"
        )
    return OpenAICompatibleProvider(
        provider=provider_name,
        api_key=api_key,
        base_url=config["base_url"],
        default_model=config["default_model"],
        timeout=timeout,
    )


def chat_with_retry(
    provider: LLMProvider,
    messages: List[Dict[str, str]],
    retries: int = MAX_RETRIES,
    **kwargs: Any,
) -> LLMResponse:
    """带重试的 chat 调用。

    遇到可重试的网络/HTTP 异常（连接错误、超时、429、5xx）时，
    按 ``BACKOFF_BASE * 2**attempt`` 指数退避后重试，最多 ``retries`` 次。

    Args:
        provider: 已构造的 provider 实例。
        messages: OpenAI 格式消息列表。
        retries: 最大尝试次数（含首次）。
        **kwargs: 透传给 provider.chat 的参数（model、temperature 等）。

    Returns:
        统一的 LLMResponse。

    Raises:
        最后一次重试仍失败时，抛出最后一次捕获的异常。
    """
    last_exc: Optional[Exception] = None
    for attempt in range(retries):
        try:
            return provider.chat(messages, **kwargs)
        except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.RequestError) as exc:
            last_exc = exc
            logger.warning(
                "LLM 调用失败 (attempt %d/%d): %s", attempt + 1, retries, exc
            )
            if attempt == retries - 1:
                break
            wait = BACKOFF_BASE * (2 ** attempt)
            logger.info("等待 %.1fs 后重试...", wait)
            time.sleep(wait)
    assert last_exc is not None
    raise last_exc


def estimate_cost(usage: Usage, provider: str = DEFAULT_PROVIDER) -> float:
    """按 provider 计价估算单次调用的成本（USD）。

    Args:
        usage: token 用量统计。
        provider: provider 名，用于查 ``PROVIDER_CONFIGS`` 的计价表。

    Returns:
        估算成本（美元），精度到 6 位小数。
    """
    config = PROVIDER_CONFIGS.get(provider.lower(), PROVIDER_CONFIGS[DEFAULT_PROVIDER])
    pricing = config["pricing"]
    cost = (
        usage.prompt_tokens * pricing["input"]
        + usage.completion_tokens * pricing["output"]
    ) / 1_000_000
    return round(cost, 6)


def quick_chat(
    prompt: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.7,
    **kwargs: Any,
) -> str:
    """一句话便捷调用，直接返回模型文本内容。

    内部依次完成：构造 provider → 组装单轮消息 → 带重试调用 → 返回 content。

    Args:
        prompt: 用户提示词。
        provider: provider 名，为空时按环境变量 / 默认值解析。
        model: 模型名，为空时用 provider 默认模型。
        temperature: 采样温度。
        **kwargs: 透传给底层 API 的额外参数。

    Returns:
        模型生成的文本。
    """
    client = create_provider(provider)
    resp = chat_with_retry(
        client,
        [{"role": "user", "content": prompt}],
        model=model,
        temperature=temperature,
        **kwargs,
    )
    return resp.content


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    sample_usage = Usage(prompt_tokens=1200, completion_tokens=300, total_tokens=1500)
    logger.info("成本估算示例（输入 1200 / 输出 300 token）:")
    for name in PROVIDER_CONFIGS:
        cost = estimate_cost(sample_usage, name)
        logger.info("  %-9s $%.6f", name, cost)

    current_provider = os.getenv("LLM_PROVIDER", DEFAULT_PROVIDER)
    logger.info("当前 provider: %s", current_provider)

    try:
        answer = quick_chat("用一句话解释什么是 LLM Agent")
        logger.info("LLM 回答: %s", answer)
    except RuntimeError as exc:
        logger.warning("跳过真实调用（未配置 API key）: %s", exc)
    except Exception as exc:
        logger.error("真实调用失败: %s", exc)
