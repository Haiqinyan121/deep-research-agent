"""图的节点实现 —— plan / research / report 三个节点的具体逻辑。

    make_plan_node()     → 拆解主题为任务列表
    make_research_node() → 单个任务：搜索 → 摘要 → 落盘（N 个并行分支）
    make_report_node()   → 合并所有摘要生成最终报告

每个节点是一个**闭包函数**：`make_*_node(config, model, ...)` 接收依赖，
返回真正被图调用的 `node(state) -> dict`。这样依赖在构图时注入一次，
节点本身保持无状态，好测也好换。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Iterable

from langchain_core.messages import AIMessageChunk, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.config import get_stream_writer
from langgraph.prebuilt import create_react_agent

from config import Configuration
from prompts import (
    get_current_date,
    report_writer_instructions,
    task_summarizer_instructions,
    todo_planner_instructions,
    todo_planner_system_prompt,
)
from search import SearchClient, prepare_research_context
from state import ResearchState, TaskItem
from tools import NoteStore
from utils import strip_thinking_tokens

logger = logging.getLogger(__name__)

TOOL_CALL_PATTERN = re.compile(r"\[TOOL_CALL:(?P<tool>[^:]+):(?P<body>[^\]]+)\]", re.IGNORECASE)

# 每个节点的"步数"，前端用它来排序/分组。
PLAN_STEP = 0


# ----------------------------------------------------------------------
# 小工具
# ----------------------------------------------------------------------
def _writer() -> Callable[[dict[str, Any]], None]:
    """拿到 LangGraph 的 custom stream writer。

    ★ 这是本项目里**最值得说**的一个 LangGraph 特性：
      节点内部可以随时 `writer(payload)` 往外推送自定义事件，
      而不必把 `yield` 写进生成器 —— 那样编排逻辑会和 `yield` 语法纠缠在一起，
      节点也没法保持纯粹的"输入 state、输出 dict"。

    不在流式上下文里时（比如 `graph.invoke()`），退化成空操作。
    """

    try:
        return get_stream_writer()
    except Exception:  # pragma: no cover - 非流式调用场景
        return lambda _payload: None


def _chunk_text(chunk: Any) -> str:
    """从各种形态的流式分片里抽出纯文本。"""

    content = getattr(chunk, "content", chunk)

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)

    return ""


# ----------------------------------------------------------------------
# 节点 1：规划
# ----------------------------------------------------------------------
def make_plan_node(config: Configuration, model: Any) -> Callable[[ResearchState], dict]:
    """规划节点 —— 把主题拆解成可独立检索的任务列表。"""

    def plan_node(state: ResearchState) -> dict:
        writer = _writer()
        topic = state.get("topic", "")

        writer({"type": "status", "message": "初始化研究流程", "step": PLAN_STEP})
        writer({"type": "status", "message": "研究规划专家正在拆解主题", "step": PLAN_STEP})

        prompt = todo_planner_instructions.format(
            current_date=get_current_date(),
            research_topic=topic,
        )

        response = model.invoke(
            [
                SystemMessage(content=todo_planner_system_prompt.strip()),
                HumanMessage(content=prompt),
            ]
        )

        text = _chunk_text(response)
        if config.strip_thinking_tokens:
            text = strip_thinking_tokens(text)

        logger.info("规划专家原始输出（截断）：%s", text[:500])

        tasks = _parse_tasks(text, topic)
        if not tasks:
            logger.info("规划未产出任务，使用兜底任务")
            tasks = [_fallback_task(topic)]

        writer({"type": "todo_list", "tasks": tasks, "step": PLAN_STEP})
        return {"tasks": tasks}

    return plan_node


# ----------------------------------------------------------------------
# 节点 2：研究（会被 fan-out 并行调用 N 次）
# ----------------------------------------------------------------------
def make_research_node(
    config: Configuration,
    model: Any,
    search_client: SearchClient,
    agent_tools: list[BaseTool],
) -> Callable[[dict], dict]:
    """研究节点 —— 处理单个任务。

    每个任务内部两步：
        搜索  →  摘要（→ 顺带落盘一条笔记）

    这个节点会被 `Send` 出 N 份并行执行，各自返回自己的 `TaskItem`，
    由 reducer 合并回 `results`。
    """

    def research_node(state: dict) -> dict:
        writer = _writer()
        task: TaskItem = dict(state["task"])
        topic = state.get("topic", "")

        task_id = int(task["id"])
        step = task_id  # 每个任务独占一个 step，前端据此分栏展示

        writer(
            {
                "type": "task_status",
                "task_id": task_id,
                "status": "in_progress",
                "title": task.get("title", ""),
                "intent": task.get("intent", ""),
                "step": step,
            }
        )

        try:
            return _research_task(
                config, model, search_client, agent_tools, writer, task, topic, task_id, step
            )
        except Exception as exc:  # 单个任务失败不应拖垮整张图
            logger.exception("任务 %s 执行失败", task_id)
            task["status"] = "failed"
            task["summary"] = f"任务执行失败：{exc}"
            writer(
                {
                    "type": "task_status",
                    "task_id": task_id,
                    "status": "failed",
                    "detail": str(exc),
                    "title": task.get("title", ""),
                    "intent": task.get("intent", ""),
                    "step": step,
                }
            )
            return {"results": [task]}

    return research_node


def _research_task(
    config: Configuration,
    model: Any,
    search_client: SearchClient,
    agent_tools: list[BaseTool],
    writer: Callable[[dict[str, Any]], None],
    task: TaskItem,
    topic: str,
    task_id: int,
    step: int,
) -> dict:
    """单个任务的完整执行：搜索 → 摘要 → 落事件。"""

    # ---- 第一步：搜索 ----
    payload, notices, answer_text, backend = search_client.search(task.get("query", ""), 0)

    for notice in notices:
        if notice:
            writer({"type": "status", "message": notice, "task_id": task_id, "step": step})

    if not payload.get("results"):
        task["status"] = "skipped"
        writer(
            {
                "type": "task_status",
                "task_id": task_id,
                "status": "skipped",
                "title": task.get("title", ""),
                "intent": task.get("intent", ""),
                "step": step,
            }
        )
        return {"results": [task]}

    sources_summary, context = prepare_research_context(payload, answer_text, config)
    task["sources_summary"] = sources_summary

    writer(
        {
            "type": "sources",
            "task_id": task_id,
            "latest_sources": sources_summary,
            "raw_context": context,
            "backend": backend,
            "step": step,
        }
    )

    # ---- 第二步：摘要（流式）----
    prompt = _build_summarizer_prompt(topic, task, context)
    summary = _run_summarizer(config, model, agent_tools, prompt, task_id, step, writer)

    task["summary"] = summary.strip() if summary and summary.strip() else "暂无可用信息"
    task["status"] = "completed"

    writer(
        {
            "type": "task_status",
            "task_id": task_id,
            "status": "completed",
            "summary": task["summary"],
            "sources_summary": sources_summary,
            "step": step,
        }
    )
    return {"results": [task]}


def _run_summarizer(
    config: Configuration,
    model: Any,
    agent_tools: list[BaseTool],
    prompt: str,
    task_id: int,
    step: int,
    writer: Callable[[dict[str, Any]], None],
) -> str:
    """跑总结。两条路径，由 `use_tool_calling` 开关切换。

    路径 A（use_tool_calling=True）：真正的 ReAct Agent
        create_react_agent(model, tools=agent_tools)
        —— 模型自己决定要不要记笔记、要不要读旧笔记、要不要查本地知识库

    路径 B（默认）：纯 LLM 流式输出，**不做任何工具调用**
        —— 稳定、快、便宜，少一层不确定性

    ⚠️ 所以 `agent_tools` 里的工具（save_note / read_note /
       search_local_knowledge_base）**都只在路径 A 生效**。
       想看到 Agent 真的去查本地知识库，必须把 USE_TOOL_CALLING 设为 True。
    """

    buffer: list[str] = []

    def emit(text: str) -> None:
        buffer.append(text)
        writer(
            {
                "type": "task_summary_chunk",
                "task_id": task_id,
                "content": text,
                "step": step,
            }
        )

    if config.use_tool_calling and agent_tools:
        # ---- 路径 A：ReAct Agent ----
        agent = create_react_agent(
            model,
            tools=agent_tools,
            prompt=task_summarizer_instructions.strip(),
        )
        stream: Iterable = agent.stream(
            {"messages": [HumanMessage(content=prompt)]},
            stream_mode="messages",
        )
        for chunk, metadata in stream:
            # 工具节点的输出是 ToolMessage，不属于给用户看的总结正文
            if isinstance(chunk, ToolMessage):
                continue
            if not isinstance(chunk, AIMessageChunk):
                continue
            text = _chunk_text(chunk)
            if text:
                emit(text)
    else:
        # ---- 路径 B：纯 LLM ----
        for chunk in model.stream(
            [
                SystemMessage(content=task_summarizer_instructions.strip()),
                HumanMessage(content=prompt),
            ]
        ):
            text = _chunk_text(chunk)
            if text:
                emit(text)

    summary = "".join(buffer)
    if config.strip_thinking_tokens:
        summary = strip_thinking_tokens(summary)
    return summary


# ----------------------------------------------------------------------
# 节点 3：报告
# ----------------------------------------------------------------------
def make_report_node(
    config: Configuration,
    model: Any,
    note_store: NoteStore | None = None,
) -> Callable[[ResearchState], dict]:
    """报告节点 —— 合并所有任务摘要，生成最终 Markdown 报告。

    这个节点只在所有 research 分支结束后执行一次（barrier 之后），
    所以能确定地拿到完整的 `results` 列表。
    """

    def report_node(state: ResearchState) -> dict:
        writer = _writer()
        topic = state.get("topic", "")
        results: list[TaskItem] = list(state.get("results") or [])
        step = len(results) + 1

        writer({"type": "status", "message": "报告撰写专家正在整合研究结果", "step": step})

        # 按任务 id 排序，保证报告里的小节顺序稳定
        results.sort(key=lambda item: int(item.get("id", 0)))

        prompt = _build_report_prompt(topic, results)

        response = model.invoke(
            [
                SystemMessage(content=report_writer_instructions.strip()),
                HumanMessage(content=prompt),
            ]
        )

        report = _chunk_text(response)
        if config.strip_thinking_tokens:
            report = strip_thinking_tokens(report)
        report = report.strip() or "暂无可用信息"

        note_id = ""
        if note_store is not None:
            title = f"研究报告：{topic}".strip() or "研究报告"
            note_store.save(title, report)
            note_id = _slug(title)

        writer(
            {
                "type": "final_report",
                "report": report,
                "note_id": note_id,
                "step": step,
            }
        )

        return {"report": report, "report_note_id": note_id}

    return report_node


# ----------------------------------------------------------------------
# 纯函数辅助
# ----------------------------------------------------------------------
def _slug(value: str) -> str:
    from tools import _slugify  # 复用同一套命名规则

    return _slugify(value)


def _fallback_task(topic: str) -> TaskItem:
    """规划失败或解析不出任务时的兜底任务，保证流程不中断。"""

    return TaskItem(
        id=1,
        title="基础背景梳理",
        intent="收集主题的核心背景与最新动态",
        query=f"{topic} 最新进展" if topic else "基础背景梳理",
        status="pending",
    )


def _build_report_prompt(topic: str, results: list[TaskItem]) -> str:
    """构造报告 Prompt。

    ⚠️ **这里有个很容易漏掉的契约问题**：必须把 `sources_summary`（含 URL）也喂进去。

    `report_writer_instructions` 要求报告输出「参考来源：按任务列出关键来源条目（标题 + 链接）」，
    但报告节点如果只传 `task.summary`，报告专家**根本拿不到链接**，
    只能在末尾写"因原始链接未提供，无法给出可访问 URL"。实测跑出来确实如此 ——
    模型被要求写链接，却没有链接可写。

    补上来源后，报告才能真正列出可追溯的 URL。
    """

    blocks: list[str] = [f"研究主题：{topic}\n\n已完成的研究任务：\n"]

    for item in results:
        blocks.append(
            f"\n### 任务 {item.get('id')}：{item.get('title', '')}\n"
            f"{item.get('summary', '暂无可用信息')}\n"
        )
        sources = item.get("sources_summary")
        if sources:
            blocks.append(f"\n本任务的参考来源：\n{sources}\n")

    return "".join(blocks)


def _build_summarizer_prompt(topic: str, task: TaskItem, context: str) -> str:
    """构造单个任务的总结 Prompt。"""

    return (
        f"任务主题：{topic}\n"
        f"任务名称：{task.get('title', '')}\n"
        f"任务目标：{task.get('intent', '')}\n"
        f"检索查询：{task.get('query', '')}\n"
        f"任务上下文：\n{context}\n"
        "请返回一份面向用户的 Markdown 总结（遵循任务总结模板）。"
    )


def _parse_tasks(raw_text: str, topic: str) -> list[TaskItem]:
    """从规划专家的输出里解析任务列表。

    宽进宽出：模型输出带不带 markdown 代码块、前后带不带解释文字，
    都能把 JSON 数组抠出来。
    """

    text = raw_text.strip()
    payload = _extract_json_payload(text)

    candidates: list[dict[str, Any]] = []
    if isinstance(payload, dict) and isinstance(payload.get("tasks"), list):
        candidates = [item for item in payload["tasks"] if isinstance(item, dict)]
    elif isinstance(payload, list):
        candidates = [item for item in payload if isinstance(item, dict)]

    if not candidates:
        tool_payload = _extract_tool_payload(text)
        if tool_payload and isinstance(tool_payload.get("tasks"), list):
            candidates = [item for item in tool_payload["tasks"] if isinstance(item, dict)]

    tasks: list[TaskItem] = []
    for index, item in enumerate(candidates, start=1):
        query = str(item.get("query") or topic).strip() or topic
        tasks.append(
            TaskItem(
                id=index,
                title=str(item.get("title") or f"任务{index}").strip(),
                intent=str(item.get("intent") or "聚焦主题的关键问题").strip(),
                query=query,
                status="pending",
            )
        )

    return tasks


def _extract_json_payload(text: str) -> dict[str, Any] | list | None:
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    return None


def _extract_tool_payload(text: str) -> dict[str, Any] | None:
    match = TOOL_CALL_PATTERN.search(text)
    if not match:
        return None

    body = match.group("body")
    try:
        payload = json.loads(body)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass

    payload: dict[str, Any] = {}
    for part in (segment.strip() for segment in body.split(",")):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        payload[key.strip()] = value.strip().strip('"').strip("'")

    return payload or None
