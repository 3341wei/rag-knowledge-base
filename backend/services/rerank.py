# -*- coding: utf-8 -*-
"""Rerank 精排（硅基流动 Cross-Encoder）。

相比原实现增加了超时、重试与降级：Rerank 只是提升排序质量，
它失败时不应让整个问答不可用，调用方会退化为粗召回顺序。
"""
from __future__ import annotations

import logging
import time

import requests

from backend.core.config import Settings, get_settings
from backend.core.errors import ServiceUnavailableError

logger = logging.getLogger(__name__)

_session: requests.Session | None = None


def get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
    return _session


def close_session() -> None:
    global _session
    if _session is not None:
        _session.close()
        _session = None


def rerank(
    query: str,
    documents: list[str],
    top_n: int | None = None,
    settings: Settings | None = None,
) -> list[tuple[int, float]]:
    """返回 [(候选下标, 相关度分数), ...]，按相关度降序。"""
    settings = settings or get_settings()
    if not documents:
        return []
    if not settings.embed_api_key:
        raise ServiceUnavailableError("未配置 SILICONFLOW_API_KEY，无法执行 Rerank")

    top_n = top_n or settings.rerank_top_k
    url = f"{settings.embed_base_url.rstrip('/')}/rerank"
    payload = {
        "model": settings.rerank_model,
        "query": query,
        "documents": documents,
        "top_n": min(top_n, len(documents)),
    }
    headers = {"Authorization": f"Bearer {settings.embed_api_key}"}

    last_error: Exception | None = None
    for attempt in range(settings.llm_max_retries + 1):
        try:
            resp = get_session().post(
                url,
                headers=headers,
                json=payload,
                timeout=(
                    5,
                    settings.http_timeout_seconds,
                ),
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            return [
                (int(item["index"]), float(item["relevance_score"]))
                for item in results
                if 0 <= int(item.get("index", -1)) < len(documents)
            ]
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = exc
            if attempt < settings.llm_max_retries:
                time.sleep(0.5 * (2**attempt))
                continue
        except requests.HTTPError as exc:
            last_error = exc
            # 4xx（鉴权/参数错误）重试无意义，直接抛出
            status = exc.response.status_code if exc.response is not None else None
            if status and 400 <= status < 500 and status != 429:
                raise
            if attempt < settings.llm_max_retries:
                time.sleep(0.5 * (2**attempt))
                continue
        except (KeyError, ValueError, TypeError) as exc:
            # 响应结构异常，重试一次也无意义
            last_error = exc
            break

    logger.warning("Rerank 调用失败，将降级为粗召回顺序: %s", last_error)
    raise ServiceUnavailableError("重排序服务暂时不可用") from last_error
