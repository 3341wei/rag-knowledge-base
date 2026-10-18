# -*- coding: utf-8 -*-
"""Embedding 封装（硅基流动，OpenAI 兼容接口）。

langchain 的 OpenAIEmbeddings 默认参数与硅基流动不完全兼容，因此直接使用
官方 openai 客户端，只传 model/input。相比原实现增加了：
- 按 EMBED_BATCH_SIZE 分批，避免超过模型单次批量上限；
- 客户端级超时与重试；
- 密钥缺失时抛出明确的服务不可用错误。
"""
from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache

from langchain_core.embeddings import Embeddings
from openai import OpenAI

from backend.core.config import Settings, get_settings
from backend.core.errors import ServiceUnavailableError


class SiliconFlowEmbedding(Embeddings):
    """实现 LangChain Embeddings 接口，供 Chroma 调用。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.embed_api_key:
            raise ServiceUnavailableError("未配置 SILICONFLOW_API_KEY，无法进行向量化")
        self.model = self.settings.embed_model
        self.batch_size = self.settings.embed_batch_size
        self.client = OpenAI(
            api_key=self.settings.embed_api_key,
            base_url=self.settings.embed_base_url,
            timeout=self.settings.http_timeout_seconds,
            max_retries=self.settings.llm_max_retries,
        )

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = list(texts[start : start + self.batch_size])
            resp = self.client.embeddings.create(model=self.model, input=batch)
            # 按 index 排序，避免上游返回顺序不稳定
            vectors.extend(
                item.embedding for item in sorted(resp.data, key=lambda d: d.index)
            )
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


@lru_cache(maxsize=1)
def get_embedding() -> SiliconFlowEmbedding:
    return SiliconFlowEmbedding()


def reset_embedding() -> None:
    """测试或配置变更后重建客户端。"""
    get_embedding.cache_clear()
