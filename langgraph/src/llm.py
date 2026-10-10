"""LLM 工厂 —— 统一构造 LangChain 的 `ChatOpenAI`。

DeepSeek / Qwen / Ollama / LMStudio 全都提供 **OpenAI 兼容接口**，
所以统一用 `ChatOpenAI` + 不同的 `base_url` 就能全部覆盖，
不需要为每个厂商单独写适配层。
"""

from __future__ import annotations

from functools import lru_cache

from langchain_openai import ChatOpenAI

from config import Configuration


def build_chat_model(config: Configuration, *, temperature: float = 0.0) -> ChatOpenAI:
    """按配置构造 ChatOpenAI。

    DeepSeek / Ollama / LMStudio 全都提供 OpenAI 兼容接口，
    所以统一用 `ChatOpenAI` + 不同的 `base_url` 就能覆盖。
    """

    model = config.resolved_model() or "gpt-4o-mini"
    base_url = config.resolved_base_url()
    api_key = config.resolved_api_key()

    kwargs: dict = {
        "model": model,
        "temperature": temperature,
        "timeout": config.llm_timeout,
        # 失败自动重试，避免单次网络抖动打断整个研究流程
        "max_retries": 2,
    }
    if base_url:
        kwargs["base_url"] = base_url
    if api_key:
        kwargs["api_key"] = api_key

    return ChatOpenAI(**kwargs)


@lru_cache(maxsize=1)
def _cached_default_model() -> ChatOpenAI:
    """进程内复用一个 model 实例，避免每个节点重复建连。"""

    return build_chat_model(Configuration.from_env())


def get_default_model() -> ChatOpenAI:
    """获取默认 model 实例。"""

    return _cached_default_model()
