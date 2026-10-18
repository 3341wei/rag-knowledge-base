# -*- coding: utf-8 -*-
"""兼容 shim：保留旧代码的 `from backend import config` 用法。

新代码请直接使用 `backend.core.config.get_settings()`。
此模块仅为迁移期兼容，后续版本会移除。
"""
from __future__ import annotations

from backend.core.config import ROOT_DIR, Settings, get_settings

_settings = get_settings()

# 旧属性名映射（只读）
LLM_API_KEY = _settings.llm_api_key
LLM_BASE_URL = _settings.llm_base_url
LLM_MODEL = _settings.llm_model

EMBED_API_KEY = _settings.embed_api_key
EMBED_BASE_URL = _settings.embed_base_url
EMBED_MODEL = _settings.embed_model

CHROMA_DIR = str(_settings.chroma_dir)
DATA_DIR = str(_settings.data_dir)

CHUNK_SIZE = _settings.chunk_size
CHUNK_OVERLAP = _settings.chunk_overlap
TOP_K = _settings.top_k

RERANK_MODEL = _settings.rerank_model
RECALL_K = _settings.recall_k
RERANK_TOP_K = _settings.rerank_top_k

__all__ = [
    "ROOT_DIR",
    "Settings",
    "get_settings",
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "EMBED_API_KEY",
    "EMBED_BASE_URL",
    "EMBED_MODEL",
    "CHROMA_DIR",
    "DATA_DIR",
    "CHUNK_SIZE",
    "CHUNK_OVERLAP",
    "TOP_K",
    "RERANK_MODEL",
    "RECALL_K",
    "RERANK_TOP_K",
]
