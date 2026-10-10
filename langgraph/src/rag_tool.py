"""本地知识库 RAG 工具 —— 让 Agent 能查私有资料。

对外提供两个函数：

    build_embeddings(config)   —— 构造 embedding 模型（建索引与检索共用同一个）
    build_rag_tool(config)     —— 返回 LangChain `@tool`：`search_local_knowledge_base`

设计上的三个要点：

1. **工厂函数 + 闭包**：和 `tools.py` 里的 `web_search` / `save_note` 一样，
   用闭包捕获 `vectorstore`，而不是写成模块级函数 —— 否则拿不到配置。

2. **索引不存在时返回 `None`**，由调用方跳过，而不是抛异常。
   没建索引不该让整张研究图挂掉。

3. **建索引和检索必须用同一个 embedding 模型**。这是 RAG 最常见的坑之一：
   两次用了不同的模型，向量落在不同的空间里，检索结果会毫无意义，
   而且**不会报错**，只是效果莫名其妙地差。
"""

from __future__ import annotations

import logging
from typing import Optional

from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings
from langchain_core.tools import BaseTool, tool

from config import Configuration

logger = logging.getLogger(__name__)


def build_embeddings(config: Configuration) -> Embeddings:
    """按配置构造 embedding 模型。

    两种模式，由 `embedding_provider` 切换：

    * `local`（默认）—— 本地 sentence-transformers 模型，**完全离线、不需要 API key**。
      默认 `BAAI/bge-small-zh-v1.5`（约 100MB，中文效果不错）。
      代价是要装 torch，首次 `uv sync` 会多下载 1~2GB。

    * `openai` —— 任何 OpenAI 兼容的 embeddings 接口（硅基流动 / 阿里 DashScope 等）。
      ⚠️ 注意 **DeepSeek 没有 embeddings 接口**，不能直接复用 `LLM_BASE_URL`，
      需要单独配 `EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY`。
    """

    provider = (config.embedding_provider or "local").strip().lower()

    if provider == "openai":
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(
            model=config.embedding_model,
            api_key=config.embedding_api_key,
            base_url=config.embedding_base_url,
        )

    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(
        model_name=config.embedding_model,
        # 归一化之后的向量可以直接用点积/余弦比较，是中文 embedding 的常见配置
        encode_kwargs={"normalize_embeddings": True},
    )


def build_rag_tool(config: Configuration) -> Optional[BaseTool]:
    """构造 `search_local_knowledge_base` 工具。

    向量库不存在时返回 `None`（并打一条警告），调用方应当跳过它 ——
    这样"还没建索引"不会阻断整个研究流程。
    """

    persist_dir = config.resolved_vector_store_dir()
    if not persist_dir.exists():
        logger.warning(
            "本地知识库尚未建立（%s 不存在），本次不加载 RAG 工具。"
            "先运行：python knowledge_indexer.py",
            persist_dir,
        )
        return None

    vectorstore = Chroma(
        collection_name=config.rag_collection,
        persist_directory=str(persist_dir),
        embedding_function=build_embeddings(config),
    )

    @tool
    def search_local_knowledge_base(query: str) -> str:
        """检索**本地私有知识库**（内部文档、研究报告、产品手册、已归档资料）。

        当问题涉及**非公开资料**时用它：
          - 公司内部文档、私有报告、项目文档
          - 已经放进 ./data/docs/ 并建好索引的资料
          - 需要精确引用本地原文出处时

        ⚠️ 它**只**能检索本地已建索引的文档，**查不到互联网上的实时信息**。
        需要最新动态、公开事实，或不确定该去哪查时，请改用 `web_search`。

        Args:
            query: 检索式，用自然语言描述你要找的内容，
                   例如 "2024 年 Q3 营收构成" 或 "Transformer 注意力机制原理"
        """

        try:
            # 返回 [(Document, distance)]，distance **越小越相关**
            hits = vectorstore.similarity_search_with_score(query, k=config.rag_top_k)
        except Exception as exc:  # 检索失败不该让节点崩掉
            logger.exception("本地知识库检索失败")
            return f"本地知识库检索失败：{exc}"

        if not hits:
            return "本地知识库中没有找到相关内容，可以改用 web_search 试试。"

        blocks = [f"本地知识库命中 {len(hits)} 个片段："]
        for index, (doc, distance) in enumerate(hits, start=1):
            source = doc.metadata.get("source", "未知来源")
            blocks.append(
                f"\n[片段 {index}] 来源：{source}（距离 {distance:.3f}，越小越相关）\n"
                f"{doc.page_content.strip()}"
            )
        return "\n".join(blocks)

    return search_local_knowledge_base
