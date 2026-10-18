# -*- coding: utf-8 -*-
"""管理接口：重建索引、统计信息。"""
from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Depends, Request

from backend.api.deps import require_api_key
from backend.core.config import get_settings
from backend.schemas import IngestResponse, StatsResponse
from backend.services.ingest import build_index
from backend.services.vectorstore import get_vectorstore, read_active_collection

router = APIRouter(prefix="/api", tags=["admin"])


@router.post(
    "/ingest",
    response_model=IngestResponse,
    dependencies=[Depends(require_api_key)],
    summary="重建向量索引（扫描 data/ 目录）",
)
async def do_ingest() -> dict:
    # 向量化是同步阻塞操作，放线程池避免卡住事件循环
    return await asyncio.to_thread(build_index)


@router.get(
    "/stats",
    response_model=StatsResponse,
    dependencies=[Depends(require_api_key)],
    summary="知识库统计信息（不含任何密钥）",
)
def stats(request: Request) -> dict:
    settings = get_settings()
    collection = read_active_collection(settings)
    try:
        chunks = get_vectorstore(collection, settings)._collection.count()
        status = "ok"
    except Exception:
        chunks = 0
        status = "degraded"

    documents = len(
        [
            p
            for p in settings.data_dir.rglob("*")
            if p.is_file() and p.suffix.lower() in (".md", ".txt")
        ]
    ) if settings.data_dir.is_dir() else 0

    started_at = getattr(request.app.state, "started_at", time.time())
    return {
        "status": status,
        "documents": documents,
        "chunks": chunks,
        "collection": collection,
        "uptime_seconds": int(time.time() - started_at),
        "config": settings.safe_summary(),
    }
