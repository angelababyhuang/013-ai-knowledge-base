# 统一 LLM 模型客户端

## Goal

封装 LLM API 调用，让后续 Pipeline 不关心底层用的是 DeepSeek 还是 Qwen。
这是「把 Week 1 手动操作变成自动化代码」的第一个模块，为后续采集/分析/整理 Python 流水线提供统一调用入口。

## Confirmed Facts（来自代码库）

- 语言：Python。现有风格参考 `hooks/validate_json.py`（`from __future__ import annotations`、dataclass、type hints、中文 docstring）
- 依赖管理：当前**无** `requirements.txt` / `pyproject.toml`，本任务需一并建立（新增 `httpx`）
- 现状：分析阶段目前靠 opencode + LLM agent 对话完成，**没有任何 Python 代码调用 LLM API**；本模块是从「agent 驱动」转向「Python pipeline 代码驱动」的第一步
- 调用方式：用户明确要求用 `httpx` 直连 OpenAI 兼容 API，**不依赖 openai SDK**

## Requirements

- 支持 DeepSeek / Qwen / OpenAI 三家（均走 OpenAI 兼容 `/chat/completions`）
- 环境变量切换：`LLM_PROVIDER`（默认 `deepseek`）+ 各 provider 专属 `*_API_KEY`
- 抽象基类 `LLMProvider` 定义接口，`OpenAICompatibleProvider` 统一实现
- 统一返回 `LLMResponse`（含 `content` + `Usage` 用量统计）
- `chat_with_retry()`：3 次重试、指数退避、60 秒超时
- Token 消耗估算 + USD 成本计算
- `quick_chat()` 便捷函数
- `if __name__ == "__main__"` 自测代码
- 编码规范：PEP 8、Google 风格 docstring、用 `logging` 不用 `print`

## Acceptance Criteria

- [x] `pipeline/model_client.py` 可 `py_compile` 通过
- [x] `create_provider("deepseek"|"qwen"|"openai")` 均可构造 provider（未知 provider 抛 ValueError，无 key 抛 RuntimeError）
- [x] `chat_with_retry` 在网络异常时重试 3 次并指数退避（1s/2s/4s），60s 超时生效
- [x] `estimate_cost` 对给定 Usage 能算出 USD 金额（1200/300 token：deepseek $0.000654 / qwen $0.00084 / openai $0.00036）
- [x] `quick_chat("xxx")` 一句话返回 content 字符串
- [x] 无 API key 时 `__main__` 不崩溃、降级为成本估算演示
- [x] 全程无 `print`，使用 `logging`

## Out of Scope

- 异步（async）调用——本期同步即可
- 流式（streaming）输出
- 多模态 / function calling
- 真实 API 集成测试（需 key，由用户后续验证）
