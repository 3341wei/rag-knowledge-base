# -*- coding: utf-8 -*-
"""健康检查（无需鉴权）。

- /healthz：存活探针，只证明进程还在，供 Docker healthcheck 使用；
- /readyz ：就绪探针，检查配置、目录与索引，未就绪返回 503。
  不主动调用外部 LLM/Embedding，避免产生费用和抖动。
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.core.config import get_settings
from backend.services.vectorstore import get_vectorstore, read_active_collection

router = APIRouter(tags=["health"])


@router.get("/healthz", summary="存活探针")
def healthz() -> dict:
    return {"status": "ok"}


@router.get("/readyz", summary="就绪探针")
def readyz() -> JSONResponse:
    settings = get_settings()

    config = "ok" if settings.chat_ready else "missing_keys"
    data_dir = "ok" if settings.data_dir.is_dir() else "missing"
    chroma_dir = "ok" if settings.chroma_dir.is_dir() else "missing"

    index = "empty"
    collection = read_active_collection(settings)
    try:
        if chroma_dir == "ok":
            count = get_vectorstore(collection, settings)._collection.count()
            index = "ok" if count > 0 else "empty"
    except Exception:
        index = "error"

    checks = {
        "config": config,
        "data_dir": data_dir,
        "chroma_dir": chroma_dir,
        "index": index,
    }
    ready = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ok" if ready else "degraded", "checks": checks},
    )
