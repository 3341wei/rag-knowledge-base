# -*- coding: utf-8 -*-
"""纯 RAG 问答接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.api.deps import require_api_key
from backend.api.sse import sse_response
from backend.core.config import get_settings
from backend.core.errors import BadRequestError
from backend.schemas import ChatRequest, ChatResponse
from backend.services.rag import answer, answer_stream

router = APIRouter(prefix="/api", tags=["chat"])


@router.post(
    "/chat",
    response_model=ChatResponse,
    dependencies=[Depends(require_api_key)],
    summary="纯 RAG 问答（非流式）",
)
def chat(req: ChatRequest) -> dict:
    return answer(req.question)


@router.post(
    "/chat/stream",
    dependencies=[Depends(require_api_key)],
    summary="纯 RAG 问答（SSE 流式）",
)
async def chat_stream(req: ChatRequest):
    if not get_settings().stream_enabled:
        raise BadRequestError("流式接口未启用")
    return sse_response(answer_stream(req.question), mode="rag")
