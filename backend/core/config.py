# -*- coding: utf-8 -*-
"""全局配置：基于 pydantic-settings，启动时完成校验。

设计要点：
- 所有配置项集中在这里，缺失/非法配置在启动阶段暴露，而不是运行到一半才报错。
- 密钥只从环境变量或 .env 读取，代码中不出现任何真实值。
- development 模式允许密钥缺失（便于无 Key 体验前端），对应接口返回 503；
  production 模式强制校验，配置不全直接拒绝启动。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录：backend/core/config.py -> core -> backend -> 项目根
ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """应用配置。环境变量名与 .env 中的名称一致（大小写不敏感）。"""

    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    # ---------------- 运行环境 ----------------
    app_env: Literal["development", "production", "test"] = "development"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    log_format: Literal["text", "json"] = "text"
    cors_origins_raw: str = Field(default="", validation_alias="CORS_ORIGINS")

    # ---------------- 访问控制 ----------------
    api_keys_raw: str = Field(default="", validation_alias="API_KEYS")
    rate_limit_requests: int = 30
    rate_limit_window_seconds: int = 60
    ingest_rate_limit_requests: int = 3
    ingest_rate_limit_window_seconds: int = 3600

    # ---------------- LLM ----------------
    llm_api_key: str = Field(default="", validation_alias="DEEPSEEK_API_KEY")
    llm_base_url: str = Field(
        default="https://api.deepseek.com", validation_alias="DEEPSEEK_BASE_URL"
    )
    llm_model: str = Field(default="deepseek-chat", validation_alias="DEEPSEEK_MODEL")
    llm_temperature: float = 0.1
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2

    # ---------------- Embedding ----------------
    embed_api_key: str = Field(default="", validation_alias="SILICONFLOW_API_KEY")
    embed_base_url: str = Field(
        default="https://api.siliconflow.cn/v1", validation_alias="SILICONFLOW_BASE_URL"
    )
    embed_model: str = Field(
        default="BAAI/bge-large-zh-v1.5", validation_alias="SILICONFLOW_EMBED_MODEL"
    )
    embed_batch_size: int = 32
    http_timeout_seconds: float = 30.0

    # ---------------- Rerank ----------------
    rerank_model: str = Field(
        default="BAAI/bge-reranker-v2-m3", validation_alias="RERANK_MODEL"
    )

    # ---------------- 路径 ----------------
    data_dir: Path = Field(default=Path("./data"), validation_alias="DATA_DIR")
    chroma_dir: Path = Field(default=Path("./chroma_db"), validation_alias="CHROMA_DIR")

    # ---------------- 切分与检索 ----------------
    chunk_size: int = 500
    chunk_overlap: int = 50
    top_k: int = 3
    recall_k: int = 20
    rerank_top_k: int = 3
    warmup_bm25: bool = True

    # ---------------- 流式 ----------------
    stream_enabled: bool = True

    @field_validator("data_dir", "chroma_dir", mode="after")
    @classmethod
    def _resolve_path(cls, value: Path) -> Path:
        """相对路径统一基于项目根目录解析，避免受启动目录影响。"""
        return value if value.is_absolute() else (ROOT_DIR / value).resolve()

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        return str(value).upper()

    @model_validator(mode="after")
    def _validate(self) -> Settings:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP 必须小于 CHUNK_SIZE")
        if self.rerank_top_k > self.recall_k:
            raise ValueError("RERANK_TOP_K 不能大于 RECALL_K")
        if self.embed_batch_size < 1:
            raise ValueError("EMBED_BATCH_SIZE 必须大于 0")
        if self.rate_limit_requests < 1 or self.rate_limit_window_seconds < 1:
            raise ValueError("限流参数必须为正整数")

        if not self.llm_model or not self.embed_model:
            raise ValueError("LLM 模型名与 Embedding 模型名不能为空")

        if self.is_production:
            missing = self.missing_required_keys
            if missing:
                raise ValueError(
                    "生产环境缺少必要配置：" + "、".join(missing)
                    + "。请在 .env 中补齐，或使用 APP_ENV=development 本地调试。"
                )
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def api_keys(self) -> list[str]:
        return [k.strip() for k in self.api_keys_raw.split(",") if k.strip()]

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins_raw.split(",") if o.strip()]

    @property
    def auth_enabled(self) -> bool:
        """配置了密钥就必须鉴权；生产环境由启动校验保证密钥非空。"""
        return bool(self.api_keys)

    @property
    def missing_required_keys(self) -> list[str]:
        missing = []
        if not self.llm_api_key:
            missing.append("DEEPSEEK_API_KEY")
        if not self.embed_api_key:
            missing.append("SILICONFLOW_API_KEY")
        if self.is_production and not self.api_keys:
            missing.append("API_KEYS")
        return missing

    @property
    def chat_ready(self) -> bool:
        return bool(self.llm_api_key and self.embed_api_key)

    def safe_summary(self) -> dict:
        """可安全写日志/返回给前端的配置摘要，绝不包含密钥值。"""
        return {
            "app_env": self.app_env,
            "llm_model": self.llm_model,
            "embed_model": self.embed_model,
            "rerank_model": self.rerank_model,
            "llm_key_configured": bool(self.llm_api_key),
            "embed_key_configured": bool(self.embed_api_key),
            "auth_enabled": self.auth_enabled,
            "data_dir": str(self.data_dir),
            "chroma_dir": str(self.chroma_dir),
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程内单例。测试中可用 reset_settings() 清除后重建。"""
    return Settings()


def reset_settings() -> None:
    get_settings.cache_clear()
