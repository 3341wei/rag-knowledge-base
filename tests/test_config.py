# -*- coding: utf-8 -*-
"""配置校验测试。"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.core.config import Settings


def test_invalid_chunk_overlap():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, chunk_size=100, chunk_overlap=100)


def test_invalid_rerank_top_k():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, recall_k=3, rerank_top_k=5)


def test_api_keys_parsing():
    settings = Settings(_env_file=None, api_keys_raw="a, b ,c")
    assert settings.api_keys == ["a", "b", "c"]
    assert settings.auth_enabled is True


def test_cors_origins_parsing():
    settings = Settings(
        _env_file=None, cors_origins_raw="https://a.example, https://b.example"
    )
    assert settings.cors_origins == ["https://a.example", "https://b.example"]


def test_production_requires_keys(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("SILICONFLOW_API_KEY", "")
    monkeypatch.setenv("API_KEYS", "")

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    message = str(exc_info.value)
    assert "DEEPSEEK_API_KEY" in message
    assert "SILICONFLOW_API_KEY" in message
    assert "API_KEYS" in message


def test_relative_paths_resolved_to_root():
    settings = Settings(_env_file=None, data_dir="./data", chroma_dir="./chroma_db")
    assert settings.data_dir.is_absolute()
    assert settings.chroma_dir.is_absolute()
