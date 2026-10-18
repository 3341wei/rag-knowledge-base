# -*- coding: utf-8 -*-
"""Agent 智能体接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Path

from backend.api.deps import require_api_key
from backend.api.sse import sse_response
from backend.core.config import get_settings
from backend.core.errors import BadRequestError
from backend.schemas import AgentResponse, ChatRequest
from backend.services.agent import forget_session, run_collect, run_stream

router = APIRouter(prefix="/api", tags=["agent"])


@router.post(
    "/agent",
    response_model=AgentResponse,
    dependencies=[Depends(require_api_key)],
    summary="智能体问答（非流式）",
)
async def agent_chat(req: ChatRequest) -> dict:
    return await run_collect(req.question, thread_id=req.session_id)


@router.post(
    "/agent/stream",
    dependencies=[Depends(require_api_key)],
    summary="智能体问答（SSE 流式）",
)
async def agent_stream(req: ChatRequest):
    if not get_settings().stream_enabled:
        raise BadRequestError("流式接口未启用")
    return sse_response(
        run_stream(req.question, thread_id=req.session_id), mode="agent"
    )


@router.delete(
    "/agent/session/{session_id}",
    dependencies=[Depends(require_api_key)],
    summary="清空某个会话的 Agent 记忆",
)
def delete_session(
    session_id: str = Path(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
) -> dict:
    forget_session(session_id)
    return {"status": "ok", "session_id": session_id}
