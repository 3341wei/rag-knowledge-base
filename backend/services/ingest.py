# -*- coding: utf-8 -*-
"""文档摄取：加载 → 切分 → 向量化 → 写入新 collection → 原子切换。

并发安全：
- 同一时刻只允许一个重建任务（非阻塞锁，冲突时返回 409）；
- 新索引写入全新 collection，写完后再切换指针，查询不会读到半成品；
- 旧 collection 在切换后清理，但保留上一个版本以便正在进行的查询读完。
"""
from __future__ import annotations

import hashlib
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from backend.core.config import Settings, get_settings
from backend.core.errors import IngestInProgressError
from backend.services.bm25 import invalidate_bm25
from backend.services.embedding import get_embedding
from backend.services.vectorstore import (
    cleanup_old_collections,
    invalidate_vectorstore,
    read_active_collection,
    write_active_collection,
)

logger = logging.getLogger(__name__)

_ingest_lock = threading.Lock()

# 针对中文文档优化分隔符顺序
_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""]


def load_documents(data_dir: Path | None = None) -> list[Document]:
    """递归加载目录下所有 .md / .txt 文档。"""
    settings = get_settings()
    data_dir = Path(data_dir or settings.data_dir)
    docs: list[Document] = []
    if not data_dir.is_dir():
        logger.warning("文档目录不存在: %s", data_dir)
        return docs

    for path in sorted(data_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in (".md", ".txt"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("跳过无法读取的文件 %s: %s", path, exc)
            continue
        if not text.strip():
            continue
        docs.append(
            Document(
                page_content=text,
                metadata={
                    "source": path.name,
                    "relative_path": path.relative_to(data_dir).as_posix(),
                },
            )
        )
    return docs


def _split(docs: list[Document], settings: Settings) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        separators=_SEPARATORS,
    )
    chunks = splitter.split_documents(docs)
    ingested_at = datetime.now(UTC).isoformat(timespec="seconds")
    for index, chunk in enumerate(chunks):
        chunk.metadata["chunk_index"] = index
        chunk.metadata["ingested_at"] = ingested_at
        chunk.metadata["content_hash"] = hashlib.sha256(
            chunk.page_content.encode("utf-8")
        ).hexdigest()[:16]
    return chunks


def build_index(
    data_dir: Path | None = None, settings: Settings | None = None
) -> dict:
    """重建索引。返回 {status, documents, chunks, collection}。"""
    settings = settings or get_settings()
    if not _ingest_lock.acquire(blocking=False):
        raise IngestInProgressError("已有重建任务正在执行，请稍后再试")

    try:
        docs = load_documents(data_dir or settings.data_dir)
        if not docs:
            return {"status": "empty", "documents": 0, "chunks": 0, "collection": read_active_collection(settings)}

        chunks = _split(docs, settings)
        collection = f"kb_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        previous = read_active_collection(settings)

        settings.chroma_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            "开始重建索引：%s 篇文档 / %s 个片段 -> %s",
            len(docs),
            len(chunks),
            collection,
        )
        Chroma.from_documents(
            documents=chunks,
            embedding=get_embedding(),
            collection_name=collection,
            persist_directory=str(settings.chroma_dir),
        )

        # 原子切换：这一刻之后的新查询都走新索引
        write_active_collection(collection, settings)
        invalidate_vectorstore()
        invalidate_bm25()

        # 保留新索引与上一版，清理更早的 collection
        keep = {collection}
        if previous and previous != collection:
            keep.add(previous)
        cleanup_old_collections(keep, settings)

        logger.info("索引重建完成：%s", collection)
        return {
            "status": "ok",
            "documents": len(docs),
            "chunks": len(chunks),
            "collection": collection,
        }
    finally:
        _ingest_lock.release()
