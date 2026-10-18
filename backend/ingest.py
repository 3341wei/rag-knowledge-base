# -*- coding: utf-8 -*-
"""文档入库 CLI。

用法（项目根目录）：
    python -m backend.ingest
    python -m backend.ingest --data-dir ./data
"""
from __future__ import annotations

import argparse
import logging

from backend.services.ingest import build_index, load_documents

__all__ = ["build_index", "load_documents"]


def main() -> int:
    parser = argparse.ArgumentParser(description="扫描文档目录并重建向量索引")
    parser.add_argument("--data-dir", default=None, help="文档目录，默认读取 DATA_DIR")
    parser.add_argument("--verbose", action="store_true", help="输出调试日志")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s | %(name)s | %(message)s",
    )

    result = build_index(args.data_dir)
    if result["status"] == "empty":
        print("未在文档目录中找到 .md / .txt 文件，索引未变更。")
        return 1
    print(
        f"索引完成：{result['documents']} 篇文档，"
        f"{result['chunks']} 个片段，collection={result['collection']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
