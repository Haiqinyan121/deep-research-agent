"""工具定义 —— 笔记读写 + 搜索，用 LangChain 的 `@tool` 声明。

    @tool
    def save_note(title: str, content: str) -> str: ...

工具的 JSON Schema 由装饰器从函数签名自动生成，通过 API 的 `tools` 参数
传给模型，模型返回结构化的 `tool_calls`，由 `ToolNode` 执行 —— 走的是
**原生 function calling**，模型不需要在正文里写任何调用语法。

⚠️ 最容易踩的坑：**函数的 docstring 就是发给 LLM 的工具描述**。
   写得含糊，LLM 就不知道该在什么时候调它。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from langchain_core.tools import BaseTool, tool

from config import Configuration
from search import SearchClient

logger = logging.getLogger(__name__)


def _slugify(value: str) -> str:
    """把标题转成安全的文件名。"""

    slug = re.sub(r"[^\w一-鿿-]+", "-", value.strip()).strip("-")
    return slug[:60] or "note"


class NoteStore:
    """极简笔记存储：一个笔记 = 一个 markdown 文件。"""

    def __init__(self, workspace: str) -> None:
        self.workspace = Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)

    def save(self, title: str, content: str) -> str:
        note_id = _slugify(title)
        path = self.workspace / f"{note_id}.md"
        path.write_text(
            f"# {title}\n\n_更新于 {datetime.now():%Y-%m-%d %H:%M:%S}_\n\n{content}\n",
            encoding="utf-8",
        )
        return f"已保存笔记 ID: {note_id}\n路径: {path}"

    def read(self, note_id: str) -> str:
        path = self.workspace / f"{_slugify(note_id)}.md"
        if not path.exists():
            return f"未找到笔记：{note_id}"
        return path.read_text(encoding="utf-8")


# ----------------------------------------------------------------------
# 工具工厂
# ----------------------------------------------------------------------
def build_search_tool(search_client: SearchClient) -> BaseTool:
    """构造 `web_search` 工具。

    这是个**工厂函数**：因为 `@tool` 需要闭包捕获 `search_client`，
    直接写模块级函数就拿不到配置了。
    """

    @tool
    def web_search(query: str) -> str:
        """搜索互联网以获取某个主题的最新信息。

        当你需要事实、数据、最新进展，或任何你不确定的知识时使用它。
        输入应当是一句具体的检索式（推荐英文关键词），而不是一个宽泛的话题。

        Args:
            query: 检索式，例如 "Transformer self-attention mechanism explained"
        """
        payload, _notices, _answer, backend = search_client.search(query)

        results = payload.get("results") or []
        if not results:
            return "未搜索到相关结果，请尝试换一个检索式。"

        blocks = [f"[{backend}] 共 {len(results)} 条结果："]
        for index, item in enumerate(results, start=1):
            blocks.append(
                f"\n来源 {index}\n"
                f"标题：{item.get('title', '')}\n"
                f"URL：{item.get('url', '')}\n"
                f"内容：{item.get('content', '')}"
            )
        return "\n".join(blocks)

    return web_search


def build_note_tools(store: NoteStore) -> list[BaseTool]:
    """构造 `save_note` / `read_note` 两个笔记工具。"""

    @tool
    def save_note(title: str, content: str) -> str:
        """把一段研究结论保存为持久化的 markdown 笔记。

        在完成一个子任务的总结后调用，便于后续汇总报告时回溯。

        Args:
            title: 笔记标题，例如 "任务 1: Transformer 基本原理"
            content: 笔记正文，使用 Markdown 格式
        """
        return store.save(title, content)

    @tool
    def read_note(note_id: str) -> str:
        """读取之前保存过的笔记。

        Args:
            note_id: 笔记 ID（save_note 返回的那个）
        """
        return store.read(note_id)

    return [save_note, read_note]


def build_tools(config: Configuration, search_client: SearchClient) -> list[BaseTool]:
    """一次性构造全部工具。"""

    tools: list[BaseTool] = [build_search_tool(search_client)]

    if config.enable_notes:
        tools.extend(build_note_tools(NoteStore(config.notes_workspace)))

    return tools
