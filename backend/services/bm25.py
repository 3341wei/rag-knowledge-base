# -*- coding: utf-8 -*-
"""BM25 关键词检索缓存。

原实现每次请求都从 Chroma 全量拉取文档重建 BM25，数据量大时会成为明显瓶颈。
这里在首次检索或索引重建后构建一次并缓存，之后复用。

中文分词：rank_bm25 默认按空格切分，对无空格的中文几乎失效。
这里提供一个无第三方依赖的简单分词器：英文/数字按词，中文按单字。
"""
from __future__ import annotations

import logging
import re
import threading

from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document

from backend.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[一-鿿]")


def zh_preprocess(text: str) -> list[str]:
    """英文/数字按词切分，中文按单字切分（BM25 在中文上的最小可用方案）。"""
    return _TOKEN_RE.findall(text.lower())


_lock = threading.RLock()
_retriever: BM25Retriever | None = None
_retriever_collection: str | None = None


def get_bm25(
    vectorstore,
    collection_name: str,
    k: int | None = None,
    settings: Settings | None = None,
) -> BM25Retriever | None:
    """获取（必要时构建）BM25 索引；collection 为空时返回 None。"""
    global _retriever, _retriever_collection
    settings = settings or get_settings()
    k = k or settings.recall_k

    with _lock:
        if _retriever is not None and _retriever_collection == collection_name:
            _retriever.k = k
            return _retriever

        stored = vectorstore.get(include=["documents", "metadatas"])
        documents = [
            Document(page_content=text, metadata=meta or {})
            for text, meta in zip(
                stored.get("documents") or [],
                stored.get("metadatas") or [],
                strict=False,
            )
            if text
        ]
        if not documents:
            _retriever = None
            _retriever_collection = collection_name
            return None

        _retriever = BM25Retriever.from_documents(
            documents, k=k, preprocess_func=zh_preprocess
        )
        _retriever_collection = collection_name
        logger.info("BM25 索引已构建：%s 个片段（collection=%s）", len(documents), collection_name)
        return _retriever


def invalidate_bm25() -> None:
    global _retriever, _retriever_collection
    with _lock:
        _retriever = None
        _retriever_collection = None


def warmup(settings: Settings | None = None) -> None:
    """启动时预热，失败只告警，不阻断服务启动。"""
    from backend.services.vectorstore import get_vectorstore, read_active_collection

    settings = settings or get_settings()
    try:
        name = read_active_collection(settings)
        get_bm25(get_vectorstore(name, settings), name, settings=settings)
    except Exception as exc:
        logger.warning("BM25 预热失败（首次检索时会重试）: %s", exc)
