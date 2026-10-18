# -*- coding: utf-8 -*-
"""请求级上下文（ContextVar）。

用途：
- request_id：贯穿日志，便于排查一次请求的完整链路。
- sources：Agent 工具在执行时把检索来源写入列表，接口结束后读取。
  这里刻意保存的是 list 的「引用」：ContextVar 在 asyncio 子任务/线程池中
  复制的是同一个对象，因此工具里 append 的内容可以被请求协程读到，
  并且不同请求各自持有独立的 list，不会像全局变量那样串数据。
"""
from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
sources_var: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "request_sources", default=None
)


def start_sources_collection() -> Token:
    """请求开始时调用：建立本次请求专属的来源收集列表。"""
    return sources_var.set([])


def get_collected_sources() -> list[dict[str, Any]]:
    """读取当前请求已收集的来源（无收集器时返回空列表）。"""
    return sources_var.get() or []


def reset_sources_collection(token: Token) -> None:
    """请求结束后恢复，避免上下文残留。"""
    sources_var.reset(token)


def current_request_id() -> str:
    return request_id_var.get()
