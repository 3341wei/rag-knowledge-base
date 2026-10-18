# -*- coding: utf-8 -*-
"""路由依赖：API Key 鉴权。"""
from __future__ import annotations

import logging

from fastapi import Request

from backend.core.config import get_settings
from backend.core.errors import AuthError
from backend.core.security import verify_api_key

logger = logging.getLogger(__name__)


def extract_api_key(request: Request) -> str | None:
    """支持 X-API-Key 与 Authorization: Bearer 两种传法。"""
    key = request.headers.get("x-api-key")
    if key:
        return key.strip()
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def require_api_key(request: Request) -> None:
    """FastAPI 依赖：校验访问密钥。

    - 已配置 API_KEYS：必须匹配；
    - 未配置：development/test 下放行并告警（仅本机调试），
      production 由启动校验保证不会走到这里。
    """
    settings = get_settings()
    if not settings.auth_enabled:
        logger.warning("未配置 API_KEYS，当前接口不做鉴权（仅限本地调试）")
        return

    provided = extract_api_key(request)
    if not verify_api_key(provided, settings.api_keys):
        raise AuthError("访问密钥无效或缺失，请在请求头 X-API-Key 中提供")
