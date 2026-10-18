# -*- coding: utf-8 -*-
"""测试环境配置。

必须在导入 backend.main 之前设置环境变量：
- 使用假密钥 + 临时目录，测试全程不访问外部 API；
- 关闭启动预热，避免测试变慢。
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

TEST_ROOT = Path(__file__).resolve().parent
TEMP_ROOT = Path(tempfile.mkdtemp(prefix="rag-kb-test-"))

os.environ.update(
    {
        "APP_ENV": "test",
        "API_KEYS": "test-key,test-key-2",
        "DEEPSEEK_API_KEY": "test-llm-key",
        "SILICONFLOW_API_KEY": "test-embed-key",
        "DATA_DIR": str(TEST_ROOT / "fixtures" / "data"),
        "CHROMA_DIR": str(TEMP_ROOT / "chroma_db"),
        "WARMUP_BM25": "false",
        "RATE_LIMIT_REQUESTS": "1000",
        "RATE_LIMIT_WINDOW_SECONDS": "60",
        "INGEST_RATE_LIMIT_REQUESTS": "1000",
        "LOG_LEVEL": "WARNING",
        "STREAM_ENABLED": "true",
    }
)


@pytest.fixture(scope="session")
def app():
    from backend.core.config import reset_settings

    reset_settings()
    from backend.main import create_app

    return create_app()


@pytest.fixture()
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def headers():
    return {"X-API-Key": "test-key"}
