# -*- coding: utf-8 -*-
"""Chroma 向量库访问层。

索引重建策略（避免原实现「先 rmtree 再重建」导致的读写竞争）：
1. 每次重建写入一个全新的 collection（kb_<时间戳>）；
2. 新 collection 写完后，原子更新 ACTIVE_COLLECTION 指针文件；
3. 旧 collection 仍可被正在进行的查询读取，稍后统一清理。

查询侧只认 ACTIVE_COLLECTION，因此切换过程对用户是无感的。
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from langchain_chroma import Chroma

from backend.core.config import Settings, get_settings
from backend.services.embedding import get_embedding

logger = logging.getLogger(__name__)

ACTIVE_COLLECTION_FILE = "ACTIVE_COLLECTION"
DEFAULT_COLLECTION = "kb_default"
# 兼容改造前的默认 collection 名
LEGACY_COLLECTION = "langchain"

_store_lock = threading.Lock()
_store_cache: dict[str, Chroma] = {}
_client_cache: dict[str, object] = {}


def read_active_collection(settings: Settings | None = None) -> str:
    """读取当前生效的 collection 名。

    改造前的项目使用默认 collection "langchain"；当指针文件不存在时，
    优先复用已有索引，避免用户升级后必须重建。
    """
    settings = settings or get_settings()
    pointer = Path(settings.chroma_dir) / ACTIVE_COLLECTION_FILE
    if pointer.is_file():
        name = pointer.read_text(encoding="utf-8").strip()
        if name:
            return name

    try:
        existing = {c.name for c in get_client(settings).list_collections()}
    except Exception:  # 索引目录尚不存在或损坏时，返回默认名
        existing = set()
    if LEGACY_COLLECTION in existing:
        return LEGACY_COLLECTION
    return DEFAULT_COLLECTION


def write_active_collection(name: str, settings: Settings | None = None) -> None:
    """原子更新指针文件：先写临时文件，再 os.replace。"""
    settings = settings or get_settings()
    settings.chroma_dir.mkdir(parents=True, exist_ok=True)
    pointer = Path(settings.chroma_dir) / ACTIVE_COLLECTION_FILE
    tmp = pointer.with_suffix(".tmp")
    tmp.write_text(name, encoding="utf-8")
    os.replace(tmp, pointer)


def get_client(settings: Settings | None = None):
    """获取 Chroma 持久化客户端（用于列举/删除 collection）。"""
    import chromadb

    settings = settings or get_settings()
    key = str(settings.chroma_dir)
    with _store_lock:
        if key not in _client_cache:
            settings.chroma_dir.mkdir(parents=True, exist_ok=True)
            _client_cache[key] = chromadb.PersistentClient(path=key)
        return _client_cache[key]


def get_vectorstore(
    collection_name: str | None = None, settings: Settings | None = None
) -> Chroma:
    settings = settings or get_settings()
    name = collection_name or read_active_collection(settings)
    key = f"{settings.chroma_dir}::{name}"
    with _store_lock:
        if key not in _store_cache:
            _store_cache[key] = Chroma(
                collection_name=name,
                persist_directory=str(settings.chroma_dir),
                embedding_function=get_embedding(),
            )
        return _store_cache[key]


def invalidate_vectorstore(collection_name: str | None = None) -> None:
    """配置或索引变化后清除缓存。"""
    with _store_lock:
        if collection_name is None:
            _store_cache.clear()
        else:
            for key in list(_store_cache):
                if key.endswith(f"::{collection_name}"):
                    _store_cache.pop(key, None)


def list_collections(settings: Settings | None = None) -> list[str]:
    try:
        return [c.name for c in get_client(settings).list_collections()]
    except Exception as exc:
        logger.warning("列举 collection 失败: %s", exc)
        return []


def delete_collection(name: str, settings: Settings | None = None) -> None:
    """删除指定 collection；失败只记录日志，不影响主流程。"""
    try:
        get_client(settings).delete_collection(name)
        invalidate_vectorstore(name)
    except Exception as exc:
        logger.warning("删除旧 collection %s 失败（可忽略）: %s", name, exc)


def cleanup_old_collections(
    keep: set[str], settings: Settings | None = None
) -> list[str]:
    """删除不在保留名单内的 collection，返回实际删除的名字。"""
    removed = []
    for name in list_collections(settings):
        if name not in keep:
            delete_collection(name, settings)
            removed.append(name)
    return removed
