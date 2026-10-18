# -*- coding: utf-8 -*-
"""RAG 核心：检索 → 拼上下文 → 生成（带引用溯源）。

同时提供同步与流式两种形式：
- answer()         供 POST /api/chat 使用；
- answer_stream()  供 POST /api/chat/stream 使用，逐 token 产出 SSE 事件。
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from functools import lru_cache

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from backend.core.config import Settings, get_settings
from backend.core.errors import ServiceUnavailableError
from backend.services.retrieval import retrieve

logger = logging.getLogger(__name__)

# 系统提示词：要求「仅依据上下文回答」，这是抑制幻觉的关键
PROMPT = ChatPromptTemplate.from_template(
    "你是一个企业知识库助手，仅根据下面的【上下文】回答问题。\n"
    "如果上下文没有答案，就说「知识库中暂无相关信息」，不要编造。\n"
    "回答时保持简洁，并在合适的位置注明依据来源。\n\n"
    "【上下文】\n{context}\n\n【问题】\n{question}\n\n【回答】"
)

NO_ANSWER = "知识库中暂无相关信息。"


@lru_cache(maxsize=1)
def get_llm() -> ChatOpenAI:
    settings = get_settings()
    if not settings.llm_api_key:
        raise ServiceUnavailableError("未配置 DEEPSEEK_API_KEY，无法调用对话模型")
    return ChatOpenAI(
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        temperature=settings.llm_temperature,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )


def reset_llm() -> None:
    get_llm.cache_clear()


def extract_text(content) -> str:
    """兼容模型返回 str 或分块 list 两种内容结构。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text", "")))
        return "".join(parts)
    return str(content)


def build_context(docs) -> str:
    return "\n\n".join(d.page_content for d in docs)


def build_sources(top) -> list[dict]:
    return [
        {
            "source": d.metadata.get("source", "未知来源"),
            "content": d.page_content[:150],
            "score": round(float(score), 4),
        }
        for d, score in top
    ]


def answer(question: str, settings: Settings | None = None) -> dict:
    """同步问答：返回 {answer, sources}。"""
    settings = settings or get_settings()
    top = retrieve(question, settings)
    if not top:
        return {"answer": NO_ANSWER, "sources": []}

    docs = [d for d, _ in top]
    messages = PROMPT.format_messages(context=build_context(docs), question=question)
    result = get_llm().invoke(messages)
    return {
        "answer": extract_text(result.content),
        "sources": build_sources(top),
    }


async def answer_stream(
    question: str, settings: Settings | None = None
) -> AsyncIterator[tuple[str, dict]]:
    """异步流式问答，产出 (事件名, 数据) 二元组。

    事件序列：meta → token* → sources → done
    检索是同步阻塞操作（HTTP + Chroma），放到线程池执行，避免阻塞事件循环。
    """
    settings = settings or get_settings()
    top = await asyncio.to_thread(retrieve, question, settings)

    if not top:
        yield "token", {"text": NO_ANSWER}
        yield "sources", {"sources": []}
        yield "done", {"answer": NO_ANSWER, "sources": []}
        return

    docs = [d for d, _ in top]
    sources = build_sources(top)
    messages = PROMPT.format_messages(context=build_context(docs), question=question)

    parts: list[str] = []
    async for chunk in get_llm().astream(messages):
        text = extract_text(chunk.content)
        if text:
            parts.append(text)
            yield "token", {"text": text}

    final = "".join(parts)
    yield "sources", {"sources": sources}
    yield "done", {"answer": final, "sources": sources}
