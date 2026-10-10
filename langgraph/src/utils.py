"""搜索结果的后处理：去重、截断、拼成能喂给模型的上下文。

这三个函数是「节点」与「提示词」之间的**契约**：
返回的字符串会被直接拼进 Prompt，报告里的引用也依赖同一套格式。
所以内部实现可以自由重写，**输出的字面格式不能动** ——
`* 标题 : URL` 那一行还被前端 `parseSources()` 解析成来源卡片。
"""

from __future__ import annotations

import logging
from typing import Any

# token 估算的经验系数。中文接近「1 字 ≈ 1 token」，英文约「4 字符 ≈ 1 token」，
# 取 4 是偏保守的折中：宁可少喂一点，也不要超出模型的上下文窗口。
CHARS_PER_TOKEN = 4

logger = logging.getLogger(__name__)


def strip_thinking_tokens(text: str) -> str:
    """删除模型输出里的 ``<think>...</think>`` 推理段。

    部分推理模型会把思维链一起吐出来。这些内容不该进报告，也不该占用
    摘要的篇幅，所以在落库前先剥掉。

    为什么用循环而不是正则：这里要求开闭标签**成对出现**才动手，
    循环写起来比 ``re.sub(r"<think>.*?</think>", "", text, flags=re.S)``
    更直白，也不会在缺闭合标签时误删后半段。

    两个退出条件都必须写死，否则畸形输入会让它停不下来：
    没有开标签、或者开标签之后找不到闭合标签，都直接收工
    （残余的孤立标签留着不动，总好过吞掉半篇正文）。
    """

    open_tag, close_tag = "<think>", "</think>"
    while True:
        start = text.find(open_tag)
        if start == -1:
            break
        end = text.find(close_tag, start + len(open_tag))
        if end == -1:
            break
        text = text[:start] + text[end + len(close_tag) :]
    return text


def deduplicate_and_format_sources(
    search_response: dict[str, Any] | list[dict[str, Any]],
    max_tokens_per_source: int,
    *,
    fetch_full_page: bool = False,
) -> str:
    """把原始搜索结果整理成一段结构化的上下文文本。

    三步：
      1. **去重** —— 同一篇网页常被多个查询命中，按 URL 只保留首次出现的
      2. **截断** —— 抓回了全文时按「每源 token 上限」截短，防止几篇长文吃掉整个上下文
      3. **格式化** —— 统一成「标题 / URL / 内容」，让模型有稳定的引用依据

    `search_response` 允许是 ``{"results": [...]}`` 或直接是列表，
    因为不同的搜索后端返回的形态并不一致。
    """

    if isinstance(search_response, dict):
        raw_sources = search_response.get("results") or []
    else:
        raw_sources = search_response

    # dict 保留插入顺序，输出顺序因此与「首次命中顺序」一致，比 set 更可预测
    unique_sources: dict[str, dict[str, Any]] = {}
    for source in raw_sources:
        url = source.get("url")
        if url and url not in unique_sources:
            unique_sources[url] = source

    char_limit = max_tokens_per_source * CHARS_PER_TOKEN
    blocks: list[str] = []

    for source in unique_sources.values():
        url = source.get("url", "")
        blocks.append(f"信息来源: {source.get('title') or url}\n\n")
        blocks.append(f"URL: {url}\n\n")
        blocks.append(f"信息内容: {source.get('content', '')}\n\n")

        if not fetch_full_page:
            continue

        # 抓全页时才有 raw_content；有些后端不给，别让 None 走进 len()
        raw_content = source.get("raw_content") or ""
        if not raw_content:
            logger.debug("来源没有 raw_content，跳过正文：%s", url)
        elif len(raw_content) > char_limit:
            raw_content = f"{raw_content[:char_limit]}... [truncated]"

        blocks.append(f"详细信息内容限制为 {max_tokens_per_source} 个 token: {raw_content}\n\n")

    return "".join(blocks).strip()


def format_sources(search_results: dict[str, Any] | None) -> str:
    """生成一句一条的来源清单，形如 ``* 标题 : URL``。

    与 `deduplicate_and_format_sources` 的分工：
    那个产出的是喂进 Prompt 的**长上下文**，这个产出的是人看的**短清单** ——
    它会被附在报告末尾，也由 SSE 的 `sources` 事件推给前端渲染成来源卡片，
    所以**必须带完整 URL**。
    """

    if not search_results:
        return ""

    results = search_results.get("results") or []
    return "\n".join(
        f"* {item.get('title', item.get('url', ''))} : {item.get('url', '')}"
        for item in results
        if item.get("url")
    )
