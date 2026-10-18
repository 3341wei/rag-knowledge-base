# -*- coding: utf-8 -*-
"""检索纯逻辑与降级行为测试。"""
from __future__ import annotations

from langchain_core.documents import Document

from backend.core.config import get_settings
from backend.core.errors import ServiceUnavailableError
from backend.services import retrieval

D1 = Document(page_content="年假每年 10 天", metadata={"source": "员工手册.md"})
D2 = Document(page_content="报销 30 天内提交", metadata={"source": "财务细则.md"})
D3 = Document(page_content="密码至少 10 位", metadata={"source": "信息安全.md"})


def test_rrf_orders_consistent_documents_first():
    fused = retrieval.rrf_fusion([[D1, D2], [D1, D2]])
    assert fused == [D1, D2]


def test_rrf_deduplicates_same_content():
    fused = retrieval.rrf_fusion([[D1, D2], [D1, D2, D3]])
    assert len(fused) == 3
    assert fused[0] is D1


def test_retrieve_degrades_when_rerank_unavailable(monkeypatch):
    settings = get_settings()
    docs = [D1, D2, D3]
    monkeypatch.setattr(retrieval, "get_vectorstore", lambda **kwargs: object())
    monkeypatch.setattr(retrieval, "hybrid_search", lambda *a, **kw: docs)

    def boom(*args, **kwargs):
        raise ServiceUnavailableError("rerank down")

    monkeypatch.setattr(retrieval.rerank, "rerank", boom)

    result = retrieval.retrieve("年假有几天", settings)
    assert len(result) == settings.rerank_top_k
    assert all(score == 0.0 for _, score in result)


def test_retrieve_uses_rerank_order(monkeypatch):
    settings = get_settings()
    docs = [D1, D2, D3]
    monkeypatch.setattr(retrieval, "get_vectorstore", lambda **kwargs: object())
    monkeypatch.setattr(retrieval, "hybrid_search", lambda *a, **kw: docs)
    # 精排：D3 最相关，D1 次之
    monkeypatch.setattr(retrieval.rerank, "rerank", lambda *a, **kw: [(2, 0.9), (0, 0.5)])

    result = retrieval.retrieve("密码要求", settings)
    assert [doc.page_content for doc, _ in result] == [D3.page_content, D1.page_content]
    assert result[0][1] == 0.9
