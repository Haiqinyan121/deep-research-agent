"""图状态定义。

LangGraph 的核心机制之一：**字段级 reducer**。

    class ResearchState(TypedDict):
        results: Annotated[list[TaskItem], operator.add]

多个并行分支同时往 `results` 里写时，LangGraph 在合并阶段对每个分支的返回值
执行一次 `operator.add` —— 结果自动列表拼接，**全程不需要加锁**。

注意：没有声明 reducer 的字段（如 `tasks`、`report`）是**覆盖**语义。
如果不小心让多个分支同时写一个无 reducer 的字段，LangGraph 会直接抛
`InvalidUpdateError` —— 它要求你显式表态合并策略，不会替你猜。
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class TaskItem(TypedDict, total=False):
    """单个研究任务。"""

    id: int
    title: str
    intent: str
    query: str
    status: str  # pending / in_progress / completed / skipped / failed
    summary: str
    sources_summary: str
    notice: str


class ResearchState(TypedDict, total=False):
    """图的全局状态。

    字段的两种语义：
      * **无 reducer**（如 `tasks`、`report`）：节点返回值**覆盖**旧值
      * **有 reducer**（如 `results`）：节点返回值与旧值**按规则合并**
    """

    # 用户输入
    topic: str

    # plan 节点写入：规划出的任务列表（覆盖语义）
    tasks: list[TaskItem]

    # research 节点写入：每个任务的结果。
    # `Annotated[..., operator.add]` = 多个并行分支的返回值自动**列表拼接**。
    # 这正是 reducer 要解决的问题：并发写共享状态，但不需要锁。
    results: Annotated[list[TaskItem], operator.add]

    # report 节点写入
    report: str
    report_note_id: str


class ResearchTaskInput(TypedDict):
    """fan-out 时通过 `Send` 传给单个 research 节点的入参。"""

    topic: str
    task: TaskItem
