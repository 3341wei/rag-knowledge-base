# -*- coding: utf-8 -*-
"""SSE（Server-Sent Events）编码与异常兜底。

响应一旦开始（HTTP 200），后续错误无法再改状态码，
因此统一以 `event: error` 帧告知客户端，并附带 request_id 便于排查。
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from fastapi.responses import StreamingResponse

from backend.core.context import current_request_id
from backend.core.errors import AppError

logger = logging.getLogger(__name__)


def format_sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def sse_response(
    events: AsyncIterator[tuple[str, dict]], mode: str
) -> StreamingResponse:
    request_id = current_request_id()

    async def generate() -> AsyncIterator[str]:
        yield format_sse(
            "meta", {"request_id": request_id, "mode": mode, "stream": True}
        )
        try:
            async for event, data in events:
                yield format_sse(event, data)
        except asyncio.CancelledError:
            # 客户端主动断开：停止生成，不做额外处理
            raise
        except AppError as exc:
            logger.warning("流式请求失败: %s %s", exc.code, exc.message)
            yield format_sse(
                "error",
                {"code": exc.code, "message": exc.message, "request_id": request_id},
            )
        except Exception:
            logger.exception("流式请求发生未处理异常")
            yield format_sse(
                "error",
                {
                    "code": "INTERNAL_ERROR",
                    "message": "服务内部错误，请稍后重试",
                    "request_id": request_id,
                },
            )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
