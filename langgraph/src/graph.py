"""StateGraph 组装 —— 整个项目的编排核心。

用节点 + 边**声明**流程，并发、同步、状态合并全部交给 LangGraph：

    START → plan → (Send fan-out) → research ×N → report → END

三种边的分工：
  * `add_edge(START, "plan")`         —— 静态边，入口
  * `add_conditional_edges(...)`      —— 条件边，返回 `Send` 列表做动态 fan-out
  * `add_edge("research", "report")`  —— 静态边，隐含 barrier：等全部分支跑完才继续
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from config import Configuration
from llm import build_chat_model
from nodes import make_plan_node, make_report_node, make_research_node
from rag_tool import build_rag_tool
from search import SearchClient
from state import ResearchState
from tools import NoteStore, build_note_tools

logger = logging.getLogger(__name__)


def fan_out_research(state: ResearchState) -> list[Send]:
    """条件边：把任务列表**展开**成 N 个并行的 research 调用。

    ★ 这个函数只负责"说清楚要并行跑哪些"，**不负责启动和回收**。

    LangGraph 会自动并发执行、等全部分支完成（barrier），然后才触发下游的
    report 节点。所以这里不需要计数器、不需要 join、不需要异常清理 ——
    "还有几个任务没跑完"这个问题由图本身回答。
    """

    tasks = state.get("tasks") or []
    return [
        Send("research", {"topic": state.get("topic", ""), "task": task}) for task in tasks
    ]


def build_graph(
    config: Configuration | None = None,
    *,
    use_memory: bool = True,
) -> Any:
    """构造并编译研究图。

    Args:
        config: 运行时配置，默认从环境变量读取。
        use_memory: 是否挂 checkpointer（演示 LangGraph 的会话记忆能力）。

    Returns:
        编译好的 LangGraph 图，支持 `.invoke()` / `.stream()` / `.astream()`。
    """

    config = config or Configuration.from_env()

    model = build_chat_model(config)
    search_client = SearchClient(config)

    note_store = NoteStore(config.notes_workspace) if config.enable_notes else None
    agent_tools: list[BaseTool] = build_note_tools(note_store) if note_store is not None else []

    # 本地知识库工具与 web_search 并列，由模型自己决定查哪个。
    # ⚠️ 这些工具只在 `use_tool_calling=True` 时才会被 Agent 调用。
    if config.enable_rag:
        rag_tool = build_rag_tool(config)
        if rag_tool is not None:
            agent_tools.append(rag_tool)

    builder = StateGraph(ResearchState)

    builder.add_node("plan", make_plan_node(config, model))
    builder.add_node("research", make_research_node(config, model, search_client, agent_tools))
    builder.add_node("report", make_report_node(config, model, note_store))

    builder.add_edge(START, "plan")
    # 条件边返回 Send 列表 → 动态 fan-out 出 N 个 research 分支
    builder.add_conditional_edges("plan", fan_out_research, ["research"])
    # 静态边 → 等所有 research 分支都结束后才执行 report
    builder.add_edge("research", "report")
    builder.add_edge("report", END)

    checkpointer = MemorySaver() if use_memory else None
    graph = builder.compile(checkpointer=checkpointer)

    logger.info(
        "研究图已编译：nodes=plan/research/report, memory=%s, tool_calling=%s",
        use_memory,
        config.use_tool_calling,
    )
    return graph
