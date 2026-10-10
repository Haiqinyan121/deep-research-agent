"""FastAPI 入口 —— 把研究图暴露成 HTTP 接口。

两种调用方式：

    POST /research          graph.invoke()  → 一次性返回完整报告
    POST /research/stream   graph.stream(stream_mode=["custom", "updates"])
                            → SSE 逐事件推送全过程

事件格式固定为 `data: {json}\\n\\n`，前端按 `type` 字段分发。
"""

from __future__ import annotations

import json
import sys
import uuid
from typing import Any, Iterator, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field

from config import Configuration
from graph import build_graph

logger.remove()
logger.add(
    sys.stderr,
    level="INFO",
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <4}</level> | "
    "<cyan>{function}</cyan> | <level>{message}</level>",
    colorize=True,
)


class ResearchRequest(BaseModel):
    """触发一次研究的请求体。"""

    topic: str = Field(..., description="研究主题")


class ResearchResponse(BaseModel):
    """非流式接口的返回体。"""

    report_markdown: str = Field(..., description="Markdown 格式的研究报告")
    todo_items: list[dict[str, Any]] = Field(default_factory=list, description="结构化任务列表")


def _sse(payload: dict[str, Any]) -> str:
    """打包成 SSE 的 data 行（前端按 `\\n\\n` 切分事件）。"""

    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def create_app() -> FastAPI:
    app = FastAPI(title="LangGraph Deep Researcher")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz")
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/research", response_model=ResearchResponse)
    def run_research(payload: ResearchRequest) -> ResearchResponse:
        """非流式：一次性跑完再返回。"""

        try:
            config = Configuration.from_env()
            graph = build_graph(config, use_memory=False)
            final_state = graph.invoke({"topic": payload.topic})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("研究失败")
            raise HTTPException(status_code=500, detail="Research failed") from exc

        return ResearchResponse(
            report_markdown=final_state.get("report", ""),
            todo_items=[dict(item) for item in (final_state.get("results") or [])],
        )

    @app.post("/research/stream")
    def stream_research(payload: ResearchRequest) -> StreamingResponse:
        """流式：以 SSE 推送事件。"""

        try:
            config = Configuration.from_env()
            graph = build_graph(config)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        # 每次请求一个独立 thread_id：既满足 checkpointer 的要求，
        # 又保证多次研究之间状态不串味。
        thread_id = str(uuid.uuid4())

        def event_iterator() -> Iterator[str]:
            try:
                for mode, chunk in graph.stream(
                    {"topic": payload.topic},
                    config={"configurable": {"thread_id": thread_id}},
                    # custom → 节点里 writer() 推的事件；updates → 节点状态变更
                    stream_mode=["custom", "updates"],
                ):
                    if mode == "custom":
                        yield _sse(chunk)
                    else:
                        logger.debug("节点状态更新: %s", list(chunk.keys()))
            except Exception as exc:  # pragma: no cover - 兜底
                logger.exception("流式研究失败")
                yield _sse({"type": "error", "detail": str(exc)})
                return

            yield _sse({"type": "done"})

        return StreamingResponse(
            event_iterator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True, log_level="info")
