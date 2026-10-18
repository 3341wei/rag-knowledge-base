# -*- coding: utf-8 -*-
"""Agent 服务（LangChain 1.x create_agent + LangGraph）。

LLM 自主决定调用哪个工具（知识库检索 / 计算器 / 当前时间），
程序执行后把结果喂回，直到模型能给出最终答案。

流式协议：
- `messages` 模式取模型输出的文本 token；
- `updates` 模式检测工具调用，发 `reset` 清掉「我先查一下」这类前置文本，
  并从 ToolMessage.artifact 中拿到结构化来源；
- 以工具调用后的最终文本作为答案，避免把中间过程混入结果。

并发说明：
- 记忆由 MemorySaver 保存在进程内，thread_id 隔离不同会话；
- 因此服务以 --workers 1 运行。水平扩展需换成外部 checkpointer。
"""
from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import AsyncIterator

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langgraph.checkpoint.memory import MemorySaver

from backend.services.rag import extract_text, get_llm
from backend.services.tools import TOOL_NAMES, TOOLS

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "你是一个企业智能助手，可以查询公司知识库、做数学计算、获取当前时间。"
    "当问题需要工具时，先调用工具获取信息，再基于工具结果回答；"
    "不要编造工具没有返回的信息。回答保持简洁。"
)

_checkpointer = MemorySaver()
_agent = None
_agent_lock = threading.Lock()


def get_agent():
    """构建带记忆的 tool-calling Agent（进程内单例）。"""
    global _agent
    if _agent is None:
        with _agent_lock:
            if _agent is None:
                _agent = create_agent(
                    get_llm(),
                    TOOLS,
                    system_prompt=SYSTEM_PROMPT,
                    checkpointer=_checkpointer,
                )
    return _agent


def reset_agent() -> None:
    global _agent
    with _agent_lock:
        _agent = None


def forget_session(thread_id: str) -> None:
    """删除某个会话的记忆（用于前端「新会话」/清理）。"""
    try:
        _checkpointer.delete_thread(thread_id)
    except Exception as exc:  # pragma: no cover - 取决于 checkpointer 实现
        logger.warning("清理会话 %s 失败: %s", thread_id, exc)


def _agent_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _extract_tool_calls(messages) -> list[str]:
    names: list[str] = []
    for msg in messages:
        for tc in getattr(msg, "tool_calls", None) or []:
            name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
            if name and name not in names:
                names.append(name)
    return names


def _collect_sources(messages) -> list[dict]:
    """从本轮新增消息的 ToolMessage.artifact 中合并来源，按内容去重。"""
    merged: list[dict] = []
    seen: set[tuple] = set()
    for msg in messages:
        if not isinstance(msg, ToolMessage) or not msg.artifact:
            continue
        artifact = msg.artifact
        items = artifact if isinstance(artifact, list) else [artifact]
        for item in items:
            if not isinstance(item, dict):
                continue
            key = (item.get("source"), item.get("content"))
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged


def run(question: str, thread_id: str = "default") -> dict:
    """同步运行 Agent，返回 {answer, tool_calls, sources}。

    只统计「本轮新增」的消息：MemorySaver 中保存着历史轮次，
    直接遍历全部消息会把上一轮的工具调用再次算进来。
    """
    agent = get_agent()
    config = _agent_config(thread_id)

    previous_count = 0
    try:
        state = agent.get_state(config)
        previous_count = len(state.values.get("messages") or [])
    except Exception:
        previous_count = 0

    result = agent.invoke({"messages": [("user", question)]}, config=config)
    new_messages = result["messages"][previous_count:]

    return {
        "answer": extract_text(new_messages[-1].content) if new_messages else "",
        "tool_calls": _extract_tool_calls(new_messages),
        "sources": _collect_sources(new_messages),
    }


async def run_collect(question: str, thread_id: str = "default") -> dict:
    """异步收集流式结果，供非流式 HTTP 接口复用，保证两条路径行为一致。"""
    final: dict = {"answer": "", "tool_calls": [], "sources": []}
    async for event, data in run_stream(question, thread_id):
        if event == "done":
            final = data
    return final


async def run_stream(
    question: str, thread_id: str = "default"
) -> AsyncIterator[tuple[str, dict]]:
    """流式运行 Agent。

    事件：tool → reset → token* → sources → done
    （tool/reset 仅在本次回答触发工具时出现）
    """
    agent = get_agent()
    config = _agent_config(thread_id)
    parts: list[str] = []
    tool_calls: list[str] = []
    sources: list[dict] = []
    seen_sources: set[tuple] = set()

    async for mode, data in agent.astream(
        {"messages": [("user", question)]},
        config=config,
        stream_mode=["messages", "updates"],
    ):
        if mode == "messages":
            chunk, _metadata = data
            text = extract_text(getattr(chunk, "content", None))
            # 只转发模型文本；ToolMessageChunk 的 content 也会走这里，
            # 用消息类型过滤，避免把工具结果当成回答。
            if text and isinstance(chunk, AIMessageChunk):
                parts.append(text)
                yield "token", {"text": text}

        elif mode == "updates":
            for update in data.values():
                messages = update.get("messages", []) if isinstance(update, dict) else []
                for msg in messages:
                    # 模型决定调用工具：清空此前输出的过程性文本
                    if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                        if parts:
                            parts.clear()
                            yield "reset", {"reason": "tool_call"}
                        for tc in msg.tool_calls:
                            name = (
                                tc.get("name")
                                if isinstance(tc, dict)
                                else getattr(tc, "name", None)
                            )
                            if name in TOOL_NAMES and name not in tool_calls:
                                tool_calls.append(name)
                                yield "tool", {"name": name}
                    # 工具执行完成：收集结构化来源
                    if isinstance(msg, ToolMessage) and msg.artifact:
                        items = msg.artifact if isinstance(msg.artifact, list) else [msg.artifact]
                        for item in items:
                            if not isinstance(item, dict):
                                continue
                            key = (item.get("source"), item.get("content"))
                            if key in seen_sources:
                                continue
                            seen_sources.add(key)
                            sources.append(item)

    yield "sources", {"sources": sources}
    yield "done", {
        "answer": "".join(parts),
        "tool_calls": tool_calls,
        "sources": sources,
    }


async def warmup() -> None:
    """可选的启动预热：只建实例，不发起外部调用。"""
    try:
        await asyncio.to_thread(get_agent)
    except Exception as exc:
        logger.warning("Agent 预热失败（首次请求时会重试）: %s", exc)
