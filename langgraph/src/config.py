"""配置加载。

配置项名称与 `.env.example` 一一对应，`Configuration.from_env()` 从环境变量读取，
缺省时回退到 `Field(default=...)`。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

# `langgraph/` 目录。用它锚定相对路径，这样无论从 `langgraph/` 还是
# `langgraph/src/` 执行脚本，`./data/docs` 都指向同一个地方。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _anchor(path: str) -> Path:
    """相对路径锚定到 langgraph/，绝对路径原样返回。"""

    candidate = Path(path)
    return candidate if candidate.is_absolute() else (_PROJECT_ROOT / candidate).resolve()


class Configuration(BaseModel):
    """深度研究助手的运行时配置。"""

    # ---- 研究行为 ----
    max_web_research_loops: int = Field(default=3, description="研究迭代次数")
    fetch_full_page: bool = Field(default=True, description="是否抓取网页全文")

    # ---- LLM ----
    llm_provider: str = Field(default="ollama", description="ollama / lmstudio / custom / deepseek")
    local_llm: str = Field(default="llama3.2", description="本地模型名")
    llm_model_id: Optional[str] = Field(default=None, description="模型 ID")
    llm_api_key: Optional[str] = Field(default=None, description="API Key")
    llm_base_url: Optional[str] = Field(default=None, description="OpenAI 兼容 base_url")
    llm_timeout: float = Field(default=60.0, description="请求超时（秒）")
    ollama_base_url: str = Field(default="http://localhost:11434")
    lmstudio_base_url: str = Field(default="http://localhost:1234/v1")

    # ---- 搜索 ----
    # 搜索后端固定为 Tavily，没有可切换的开关（理由见 search.py）。
    tavily_api_key: Optional[str] = Field(default=None)

    # ---- 笔记 ----
    enable_notes: bool = Field(default=True, description="是否启用笔记工具")
    notes_workspace: str = Field(default="./notes", description="笔记落盘目录")

    # ---- 本地知识库 RAG ----
    enable_rag: bool = Field(default=False, description="是否启用本地知识库检索工具")
    knowledge_base_dir: str = Field(default="./data/docs", description="待索引的原始文档目录")
    vector_store_dir: str = Field(default="./data/chroma", description="Chroma 持久化目录")
    rag_collection: str = Field(default="local_knowledge", description="Chroma collection 名")
    rag_top_k: int = Field(default=3, description="检索返回的片段数")
    rag_chunk_size: int = Field(default=800, description="切片长度（字符）")
    rag_chunk_overlap: int = Field(default=120, description="切片重叠长度（字符）")
    embedding_provider: str = Field(default="local", description="local / openai")
    embedding_model: str = Field(default="BAAI/bge-small-zh-v1.5", description="embedding 模型名")
    embedding_api_key: Optional[str] = Field(default=None, description="openai 模式下的 key")
    embedding_base_url: Optional[str] = Field(default=None, description="openai 模式下的地址")

    # ---- Agent 行为 ----
    use_tool_calling: bool = Field(
        default=False,
        description="总结阶段是否使用 ReAct Agent（create_react_agent）而非纯 LLM",
    )
    strip_thinking_tokens: bool = Field(default=True, description="是否剥离 <think> 段")

    @classmethod
    def from_env(cls, overrides: Optional[dict[str, Any]] = None) -> "Configuration":
        """从环境变量构建配置，overrides 优先级最高。"""

        raw_values: dict[str, Any] = {}

        for field_name in cls.model_fields:
            env_key = field_name.upper()
            if env_key in os.environ:
                raw_values[field_name] = os.environ[env_key]

        # 兼容 .env 里的小写别名写法
        for key in (
            "llm_provider",
            "llm_model_id",
            "llm_api_key",
            "llm_base_url",
            "local_llm",
            "enable_notes",
            "notes_workspace",
            "max_web_research_loops",
            "fetch_full_page",
            "strip_thinking_tokens",
            "use_tool_calling",
            "ollama_base_url",
            "lmstudio_base_url",
            "tavily_api_key",
            "enable_rag",
            "knowledge_base_dir",
            "vector_store_dir",
            "rag_collection",
            "rag_top_k",
            "rag_chunk_size",
            "rag_chunk_overlap",
            "embedding_provider",
            "embedding_model",
            "embedding_api_key",
            "embedding_base_url",
        ):
            value = os.getenv(key.upper()) or os.getenv(key)
            if value is not None:
                raw_values.setdefault(key, value)

        if overrides:
            raw_values.update({k: v for k, v in overrides.items() if v is not None})

        return cls(**raw_values)

    def sanitized_ollama_url(self) -> str:
        """Ollama 的 OpenAI 兼容端点需要 /v1 后缀。"""

        base = self.ollama_base_url.rstrip("/")
        return base if base.endswith("/v1") else f"{base}/v1"

    def resolved_base_url(self) -> Optional[str]:
        """按 provider 解析出实际要用的 base_url。"""

        provider = (self.llm_provider or "").strip().lower()

        if provider == "ollama":
            return self.sanitized_ollama_url()
        if provider == "lmstudio":
            return self.lmstudio_base_url
        return self.llm_base_url

    def resolved_api_key(self) -> Optional[str]:
        """按 provider 解析出实际要用的 API Key。"""

        provider = (self.llm_provider or "").strip().lower()
        return self.llm_api_key or {"ollama": "ollama", "lmstudio": "lm-studio"}.get(provider)

    def resolved_model(self) -> Optional[str]:
        """解析模型 ID。"""

        return self.llm_model_id or self.local_llm

    def resolved_knowledge_base_dir(self) -> Path:
        """原始文档目录（锚定到 langgraph/）。"""

        return _anchor(self.knowledge_base_dir)

    def resolved_vector_store_dir(self) -> Path:
        """Chroma 持久化目录（锚定到 langgraph/）。"""

        return _anchor(self.vector_store_dir)
