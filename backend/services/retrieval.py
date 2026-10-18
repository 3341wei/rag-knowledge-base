# -*- coding: utf-8 -*-
"""检索链路：向量召回 + BM25 召回 → RRF 融合 → Rerank 精排。

保持与原项目一致的对外语义：`retrieve()` 返回 [(Document, 相关度分数), ...]。
Rerank 不可用时自动降级为 RRF 粗排结果，保证问答仍然可用。
"""
from __future__ import annotations

import logging

from langchain_core.documents import Document

from backend.core.config import Settings, get_settings
from backend.core.errors import ServiceUnavailableError
from backend.services import rerank
from backend.services.bm25 import get_bm25
from backend.services.vectorstore import get_vectorstore, read_active_collection

logger = logging.getLogger(__name__)


def rrf_fusion(doc_lists: list[list[Document]], k: int = 60) -> list[Document]:
    """Reciprocal Rank Fusion：排名越靠前、在越多路结果中出现，得分越高。"""
    scores: dict[tuple[str, str], float] = {}
    docs: dict[tuple[str, str], Document] = {}

    for doc_list in doc_lists:
        for rank, doc in enumerate(doc_list):
            key = (doc.metadata.get("source", ""), doc.page_content)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            docs.setdefault(key, doc)

    ordered = sorted(scores, key=lambda key: scores[key], reverse=True)
    return [docs[key] for key in ordered]


def hybrid_search(
    question: str,
    vectorstore=None,
    recall_k: int | None = None,
    settings: Settings | None = None,
) -> list[Document]:
    """混合检索粗召回。任一路失败时退化为另一路，整体失败才抛出。"""
    settings = settings or get_settings()
    recall_k = recall_k or settings.recall_k
    collection_name = getattr(
        getattr(vectorstore, "_collection", None), "name", None
    )
    if vectorstore is None:
        vectorstore = get_vectorstore(settings=settings)
        collection_name = read_active_collection(settings)

    doc_lists: list[list[Document]] = []

    try:
        vec_docs = vectorstore.as_retriever(
            search_kwargs={"k": recall_k}
        ).invoke(question)
        doc_lists.append(vec_docs)
    except Exception as exc:
        logger.warning("向量检索失败: %s", exc)

    try:
        bm25 = get_bm25(vectorstore, collection_name or "unknown", recall_k, settings)
        if bm25 is not None:
            doc_lists.append(bm25.invoke(question))
    except Exception as exc:
        logger.warning("BM25 检索失败: %s", exc)

    if not doc_lists:
        raise ServiceUnavailableError("检索服务暂时不可用，请稍后重试")

    return rrf_fusion(doc_lists)[:recall_k]


def retrieve(
    question: str, settings: Settings | None = None
) -> list[tuple[Document, float]]:
    """完整检索：混合召回 + Rerank。返回按相关度降序的 (文档, 分数)。"""
    settings = settings or get_settings()
    vectorstore = get_vectorstore(settings=settings)
    candidates = hybrid_search(question, vectorstore, settings=settings)
    if not candidates:
        return []

    try:
        ranked = rerank.rerank(
            question,
            [d.page_content for d in candidates],
            top_n=settings.rerank_top_k,
            settings=settings,
        )
        if ranked:
            return [(candidates[i], score) for i, score in ranked]
    except ServiceUnavailableError:
        logger.warning("Rerank 不可用，降级为混合检索粗排结果")

    # 降级：取粗排前 rerank_top_k，分数置 0 表示未经精排
    return [(doc, 0.0) for doc in candidates[: settings.rerank_top_k]]
