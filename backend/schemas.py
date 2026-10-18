# -*- coding: utf-8 -*-
"""API 请求与响应模型。

请求侧做长度与字符集校验，避免超长文本消耗大量 token 或写入异常会话 ID。
"""
from __future__ import annotations

from pydantic import BaseModel, Field

SESSION_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"


class ChatRequest(BaseModel):
    question: str = Field(
        ..., min_length=1, max_length=2000, description="用户问题"
    )
    session_id: str = Field(
        default="default",
        max_length=64,
        pattern=SESSION_ID_PATTERN,
        description="会话 ID，用于隔离多轮记忆",
    )


class Source(BaseModel):
    source: str
    content: str
    score: float


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source] = Field(default_factory=list)


class AgentResponse(ChatResponse):
    tool_calls: list[str] = Field(default_factory=list)


class IngestResponse(BaseModel):
    status: str
    documents: int
    chunks: int
    collection: str


class StatsResponse(BaseModel):
    status: str
    documents: int
    chunks: int
    collection: str
    uptime_seconds: int
    config: dict


class ReadyChecks(BaseModel):
    config: str
    data_dir: str
    chroma_dir: str
    index: str


class ReadyResponse(BaseModel):
    status: str
    checks: ReadyChecks
