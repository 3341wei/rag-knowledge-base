# -*- coding: utf-8 -*-
"""检索效果评测的根目录兼容入口。

实际实现位于 scripts/eval_retrieval.py。
用法：python eval_retrieval.py
"""
import runpy
from pathlib import Path

if __name__ == "__main__":
    target = Path(__file__).resolve().parent / "scripts" / "eval_retrieval.py"
    runpy.run_path(str(target), run_name="__main__")
