r"""命令行冒烟测试 —— 不用起前端就能验证整张图能跑通。

用法（在 `langgraph/src` 目录下）：
    ..\.venv\Scripts\python.exe cli.py "Transformer 模型"
"""

from __future__ import annotations

import sys
import uuid

from config import Configuration
from graph import build_graph


def main() -> int:
    # 控制台编码可能是 GBK，而 notices 里带 ✅ / ⚠️ 这类字符 —— 直接 print 会抛
    # UnicodeEncodeError 把冒烟测试打断。这里让编不出来的字符降级成 "?"，而不是报错。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    topic = " ".join(sys.argv[1:]).strip() or "Transformer 模型"

    config = Configuration.from_env()
    print(f"模型: {config.resolved_model()}  搜索后端: Tavily")
    print(f"研究主题: {topic}\n")

    graph = build_graph(config)

    for mode, chunk in graph.stream(
        {"topic": topic},
        config={"configurable": {"thread_id": str(uuid.uuid4())}},
        stream_mode=["custom", "updates"],
    ):
        if mode != "custom":
            continue

        event_type = chunk.get("type")

        if event_type == "task_summary_chunk":
            print(chunk.get("content", ""), end="", flush=True)
        elif event_type == "final_report":
            print("\n\n" + "=" * 60)
            print("最终报告")
            print("=" * 60 + "\n")
            print(chunk.get("report", ""))
        elif event_type == "todo_list":
            print("\n[规划完成]")
            for task in chunk.get("tasks", []):
                print(f"  {task['id']}. {task['title']}  ← {task['query']}")
        elif event_type == "sources":
            print(f"\n[任务 {chunk.get('task_id')} 检索到来源，后端={chunk.get('backend')}]")
        elif event_type == "task_status":
            print(f"\n[任务 {chunk.get('task_id')} → {chunk.get('status')}]")
        elif event_type == "status":
            print(f"\n[状态] {chunk.get('message')}")

    print("\n\n完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
