"""搜索客户端 —— 统一封装搜索后端，输出固定结构的 payload。

直接调用搜索厂商的 SDK，**不依赖任何 Agent 框架**，
这样搜索层可以独立替换、独立测试。

两个核心函数：
  * `SearchClient.search()`      —— 执行搜索，返回结构化 payload
  * `prepare_research_context()` —— 去重 → 按 token 截断 → 拼装 Prompt 上下文

本项目只使用 Tavily 一个搜索后端，且**不做「这家失败就换另一家」的降级**：
降级会把真正出问题的接口藏起来 —— 兜底自己再报错时，抛出来的是兜底的错误，
排查时看到的原因和真实原因根本不是一回事。网络抖动交给重试处理。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from config import Configuration
from utils import deduplicate_and_format_sources, format_sources

logger = logging.getLogger(__name__)

MAX_TOKENS_PER_SOURCE = 2000
MAX_RESULTS = 5

# ---- 重试策略 ----
# TLS 被重置、连接超时这类抖动是**暂时**的，隔一会儿重发通常就通了。
# 失败后按下面的间隔重试，TAVILY_RETRY_DELAYS 的长度 + 1 = 总尝试次数。
TAVILY_RETRY_DELAYS = (1.0, 3.0)

# 这几类错误重试没有意义：key 无效、额度用尽、请求本身不合法，
# 再试几次结果还是同一个，只会白白拖慢一次研究。
TAVILY_FATAL_ERRORS = frozenset(
    {
        "InvalidAPIKeyError",
        "MissingAPIKeyError",
        "UsageLimitExceededError",
        "ForbiddenError",
        "BadRequestError",
    }
)


def _brief(exc: Exception, limit: int = 160) -> str:
    """异常信息可能很长（SSL 报错能有两百多字符），日志里截断一下。"""

    text = str(exc).replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


class SearchError(RuntimeError):
    """搜索后端不可用或调用失败。"""


class SearchClient:
    """统一封装搜索后端，输出固定结构的 payload。

    返回的 payload 结构：
        {"results": [{"title","url","content","raw_content"}],
         "backend": "<实际生效的后端>", "answer": <直接答案或 None>,
         "notices": ["..."]}
    """

    def __init__(self, config: Configuration) -> None:
        self.config = config
        self._tavily_client: Any | None = None
        self._notices: list[str] = []
        self._setup_backends()

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------
    def _setup_backends(self) -> None:
        """构造时就把客户端准备好，并把可用情况记进 notices（前端会展示）。"""

        key = self.config.tavily_api_key
        if not key:
            self._notices.append("⚠️ TAVILY_API_KEY 未设置，搜索不可用")
            return

        try:
            from tavily import TavilyClient

            self._tavily_client = TavilyClient(api_key=key)
            self._notices.append("✅ Tavily 搜索引擎已初始化")
        except Exception as exc:  # pragma: no cover
            logger.warning("Tavily 初始化失败: %s", exc)
            self._notices.append(f"⚠️ Tavily 初始化失败: {_brief(exc)}")

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def search(
        self,
        query: str,
        loop_count: int = 0,
    ) -> tuple[dict[str, Any], list[str], Optional[str], str]:
        """执行搜索，返回 (payload, notices, answer_text, backend_label)。

        失败只有两种处理：**能重试的重试，重试不动的把原始错误抛出来**。
        不换后端、不吞异常 —— 失败原因必须能一路透到界面上，
        否则一个外部依赖的偶发故障会被伪装成别的东西。
        """

        if self._tavily_client is None:
            raise SearchError(
                "未配置 TAVILY_API_KEY，无法搜索。请在 langgraph/.env 里填入后重试。"
            )

        notices = list(self._notices)
        results, answer_text = self._search_tavily(query, notices)
        backend_label = "tavily"

        payload: dict[str, Any] = {
            "results": results,
            "backend": backend_label,
            "answer": answer_text,
            "notices": notices,
        }

        logger.info(
            "搜索完成 backend=%s results=%d answer=%s loop=%s",
            backend_label,
            len(results),
            bool(answer_text),
            loop_count,
        )
        return payload, notices, answer_text, backend_label

    # ------------------------------------------------------------------
    # Tavily
    # ------------------------------------------------------------------
    def _search_tavily(
        self,
        query: str,
        notices: list[str],
    ) -> tuple[list[dict[str, Any]], Optional[str]]:
        """调用 Tavily；网络类错误自动重试，重试耗尽则抛出 SearchError。

        重试会往 notices 里记一条 —— nodes.py 把 notices 当作 `status` 事件推给
        前端，所以「第 1 次失败、正在重试」在界面的事件日志里看得到。
        否则用户只会觉得这一次检索莫名其妙变慢了。
        """

        attempts = len(TAVILY_RETRY_DELAYS) + 1

        for attempt in range(1, attempts + 1):
            try:
                return self._tavily_request(query)
            except Exception as exc:
                fatal = type(exc).__name__ in TAVILY_FATAL_ERRORS
                if fatal or attempt >= attempts:
                    raise SearchError(f"Tavily 搜索失败：{_brief(exc, 400)}") from exc

                delay = TAVILY_RETRY_DELAYS[attempt - 1]
                logger.warning(
                    "Tavily 第 %d/%d 次调用失败：%s（%.1fs 后重试）",
                    attempt,
                    attempts,
                    _brief(exc),
                    delay,
                )
                notices.append(
                    f"⚠️ Tavily 第 {attempt}/{attempts} 次调用失败，{delay:g}s 后重试：{_brief(exc)}"
                )
                time.sleep(delay)

        # 循环里要么 return、要么 raise，走不到这里；留着只是给类型检查一个交代。
        raise SearchError("Tavily 搜索失败")

    def _tavily_request(self, query: str) -> tuple[list[dict[str, Any]], Optional[str]]:
        """真正的那一次网络请求（不含重试逻辑，便于单独测试）。"""

        response = self._tavily_client.search(  # type: ignore[union-attr]
            query=query,
            max_results=MAX_RESULTS,
            search_depth="advanced",
            include_answer=True,
            include_raw_content=self.config.fetch_full_page,
        )

        results: list[dict[str, Any]] = []
        for item in response.get("results", []):
            results.append(
                {
                    "title": item.get("title") or item.get("url", ""),
                    "url": item.get("url", ""),
                    "content": item.get("content", ""),
                    "raw_content": item.get("raw_content"),
                }
            )

        return results, response.get("answer")


def prepare_research_context(
    search_result: dict[str, Any] | None,
    answer_text: Optional[str],
    config: Configuration,
) -> tuple[str, str]:
    """把搜索结果整理为 (来源摘要, 上下文)。

    去重 → 按 token 截断 → 拼成 Prompt 上下文 → 喂给 LLM。
    与知识库检索的区别只在于检索源是互联网而不是私有文档库。
    """

    sources_summary = format_sources(search_result)
    context = deduplicate_and_format_sources(
        search_result or {"results": []},
        max_tokens_per_source=MAX_TOKENS_PER_SOURCE,
        fetch_full_page=config.fetch_full_page,
    )

    if answer_text:
        context = f"AI直接答案：\n{answer_text}\n\n{context}"

    return sources_summary, context
