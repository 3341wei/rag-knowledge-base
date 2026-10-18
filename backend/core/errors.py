# -*- coding: utf-8 -*-
"""统一异常与错误响应。

所有可预期的业务错误继承 AppError，由全局处理器转成固定结构：
    {"error": {"code": "...", "message": "...", "request_id": "..."}}
生产环境不会把堆栈或上游原始报文返回给客户端。
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.core.context import current_request_id

logger = logging.getLogger(__name__)


class AppError(Exception):
    """业务异常基类。"""

    status_code = 500
    code = "INTERNAL_ERROR"

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.code
        super().__init__(self.message)


class BadRequestError(AppError):
    status_code = 400
    code = "BAD_REQUEST"


class AuthError(AppError):
    status_code = 401
    code = "UNAUTHORIZED"


class RateLimitError(AppError):
    status_code = 429
    code = "RATE_LIMITED"


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "SERVICE_UNAVAILABLE"


class UpstreamError(AppError):
    status_code = 502
    code = "UPSTREAM_ERROR"


class UpstreamTimeoutError(AppError):
    status_code = 504
    code = "UPSTREAM_TIMEOUT"


class IngestInProgressError(AppError):
    status_code = 409
    code = "INGEST_IN_PROGRESS"


def _error_body(code: str, message: str) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": current_request_id(),
        }
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.error("%s: %s", exc.code, exc.message, exc_info=True)
        else:
            logger.warning("%s: %s", exc.code, exc.message)
        headers = {"X-Request-ID": current_request_id()}
        if isinstance(exc, RateLimitError):
            headers["Retry-After"] = "60"
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.code, exc.message),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # 只返回字段级摘要，避免把内部类型信息暴露出去
        details = []
        for item in exc.errors():
            loc = ".".join(str(p) for p in item.get("loc", ()) if p != "body")
            details.append(f"{loc}: {item.get('msg', '参数不合法')}")
        return JSONResponse(
            status_code=422,
            content=_error_body("VALIDATION_ERROR", "；".join(details) or "参数不合法"),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body("HTTP_ERROR", str(exc.detail)),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("未处理异常: %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content=_error_body("INTERNAL_ERROR", "服务内部错误，请稍后重试"),
        )
