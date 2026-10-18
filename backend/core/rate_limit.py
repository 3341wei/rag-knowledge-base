# -*- coding: utf-8 -*-
"""进程内滑动窗口限流。

为什么自研而不是引入 slowapi：
- 需要按「接口类型」使用不同配额（普通问答 vs 昂贵的重建索引）；
- 纯 ASGI 中间件不缓冲响应体，对 SSE 流式输出没有副作用。

限制：计数保存在当前进程内存中，仅在单进程（Docker 默认 --workers 1）下准确。
水平扩展时应替换为 Redis 等共享存储，README 已注明。
"""
from __future__ import annotations

import threading
import time
from collections import deque

from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from backend.core.context import current_request_id
from backend.core.security import key_fingerprint


class SlidingWindowLimiter:
    """按 key 统计窗口内请求数。线程安全，适用于多线程/协程混用。"""

    def __init__(self, limit: int, window_seconds: int, max_keys: int = 10_000) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> tuple[bool, int]:
        """返回 (是否放行, 需要等待的秒数)。"""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= self.limit:
                retry_after = max(1, int(bucket[0] + self.window_seconds - now) + 1)
                return False, retry_after

            bucket.append(now)
            if len(self._hits) > self._max_keys:
                self._cleanup(cutoff)
            return True, 0

    def _cleanup(self, cutoff: float) -> None:
        """清理已经过期的 key，避免内存随访问来源无限增长。"""
        stale = [k for k, v in self._hits.items() if not v or v[-1] <= cutoff]
        for key in stale:
            self._hits.pop(key, None)


class RateLimitMiddleware:
    """只对 /api/* 生效；健康检查与静态资源不限流。"""

    def __init__(self, app: ASGIApp, settings=None) -> None:
        if settings is None:
            from backend.core.config import get_settings

            settings = get_settings()
        self.app = app
        self.general = SlidingWindowLimiter(
            settings.rate_limit_requests, settings.rate_limit_window_seconds
        )
        self.ingest = SlidingWindowLimiter(
            settings.ingest_rate_limit_requests,
            settings.ingest_rate_limit_window_seconds,
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not path.startswith("/api/") or path in ("/healthz", "/readyz"):
            await self.app(scope, receive, send)
            return

        limiter = self.ingest if path.startswith("/api/ingest") else self.general
        allowed, retry_after = limiter.hit(self._client_key(scope))
        if not allowed:
            response = JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": f"请求过于频繁，请 {retry_after} 秒后重试",
                        "request_id": current_request_id(),
                    }
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-Request-ID": current_request_id(),
                },
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)

    @staticmethod
    def _client_key(scope: Scope) -> str:
        headers = dict(scope.get("headers") or [])
        api_key = headers.get(b"x-api-key", b"").decode("latin-1") or None
        client = scope.get("client")
        ip = client[0] if client else "unknown"
        return f"{ip}:{key_fingerprint(api_key)}"
