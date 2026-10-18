# -*- coding: utf-8 -*-
"""访问密钥校验。

使用 secrets.compare_digest 做常量时间比较，避免通过响应时间推测密钥。
支持逗号分隔的多把密钥，便于轮换（新旧密钥可短暂并存）。
"""
from __future__ import annotations

import hashlib
import secrets


def verify_api_key(provided: str | None, valid_keys: list[str]) -> bool:
    if not provided or not valid_keys:
        return False
    provided_bytes = provided.encode("utf-8")
    matched = False
    # 不提前 return，保证比较次数与密钥数量无关
    for key in valid_keys:
        if secrets.compare_digest(provided_bytes, key.encode("utf-8")):
            matched = True
    return matched


def key_fingerprint(key: str | None) -> str:
    """返回密钥的短指纹，仅用于限流分桶和日志标识，不可逆推原值。"""
    if not key:
        return "anon"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
