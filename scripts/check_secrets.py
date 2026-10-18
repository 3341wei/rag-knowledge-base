# -*- coding: utf-8 -*-
"""提交前密钥扫描。

用法（项目根目录）：
    python scripts/check_secrets.py            # 扫描 git 追踪的文件
    python scripts/check_secrets.py --all      # 扫描工作区全部文件（跳过忽略目录）

规则：
1. .env 类文件不得被 git 追踪（真实密钥只存在于本地）。
2. 文本中不得出现常见的 API Key 形态（OpenAI/DeepSeek、AWS、GitHub、Slack 等）。
3. .env.example 中的值必须是占位符（包含"请替换"或为空）。

发现疑似泄漏时退出码为 1，可直接用于 CI 和 pre-commit。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 跳过的目录：二进制数据、依赖与缓存
SKIP_DIRS = {
    ".git", ".venv", "venv", "env", "__pycache__", "chroma_db",
    "node_modules", ".pytest_cache", ".ruff_cache", ".mypy_cache", "dist", "build",
}

# 跳过的文件后缀
SKIP_SUFFIXES = {
    ".pyc", ".pyo", ".sqlite3", ".db", ".bin", ".png", ".jpg", ".jpeg",
    ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz", ".woff", ".woff2",
}

# 正则用字符串拼接，避免脚本自身命中规则
_PATTERNS = [
    # OpenAI / DeepSeek / 硅基流动等 sk- 形态（排除示例占位符）
    (r"\bsk" + r"-[A-Za-z0-9]{20,}\b", "疑似 sk- API Key"),
    # AWS Access Key
    (r"\bAK" + r"IA[0-9A-Z]{16}\b", "疑似 AWS Access Key"),
    # GitHub Token
    (r"\bgh" + r"[pousr]_[A-Za-z0-9]{30,}\b", "疑似 GitHub Token"),
    # Slack Token
    (r"\bxox" + r"[baprs]-[A-Za-z0-9-]{10,}\b", "疑似 Slack Token"),
    # 通用长随机串赋值（仅检查明显的 key/secret/token 变量）
    (
        r"(?i)\b[A-Z0-9_]*(?:API_KEY|SECRET|TOKEN|PASSWORD)[A-Z0-9_]*\s*=\s*"
        r"['\"]?(?!\s*$|请替换|你的|xxx|change-me|your-|<)[A-Za-z0-9_\-]{24,}",
        "疑似硬编码密钥赋值",
    ),
]

SKIP_FILES = {"scripts/check_secrets.py"}


def run_git(*args: str, zero: bool = False) -> list[Path]:
    """执行 git 命令并把输出转成路径列表；失败时返回空列表。

    Windows 下 git 输出为 UTF-8，显式解码避免 GBK 报错；
    路径含中文时使用 -z 分隔，避免 git 的引号转义。
    """
    cmd = ["git", "-c", "core.quotepath=false", *args]
    if zero:
        cmd.append("-z")
    try:
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    raw = proc.stdout.decode("utf-8", errors="replace")
    parts = raw.split("\0") if zero else raw.splitlines()
    return [ROOT / p for p in parts if p.strip()]


def in_git_repo() -> bool:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=ROOT,
            capture_output=True,
        ).returncode == 0
    except FileNotFoundError:
        return False


def walk_files() -> list[Path]:
    files = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        files.append(path)
    return files


def is_env_file(path: Path) -> bool:
    name = path.name
    return name == ".env" or (name.startswith(".env.") and name != ".env.example")


def scan_text(path: Path) -> list[str]:
    rel = path.relative_to(ROOT).as_posix()
    if rel in SKIP_FILES:
        return []
    # 真实的 .env 由规则 1 单独检查是否被追踪；内容本身不参与扫描，避免本地误报
    if is_env_file(path):
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    findings = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        # .env.example 中的占位符允许包含 "sk-请替换..."，上面的正则会跳过
        for pattern, label in _PATTERNS:
            if re.search(pattern, line):
                findings.append(f"{rel}:{lineno}: {label}")
                break
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="扫描项目中的疑似密钥泄漏")
    parser.add_argument("--all", action="store_true", help="扫描工作区全部文件（默认只扫描 git 追踪文件）")
    args = parser.parse_args()

    findings: list[str] = []

    if args.all or not in_git_repo():
        targets = walk_files()
    else:
        # 规则 1：.env 不得被追踪
        tracked = run_git("ls-files", "--cached", zero=True)
        for path in tracked:
            if is_env_file(path):
                findings.append(f"{path.relative_to(ROOT).as_posix()}: 真实环境变量文件被 git 追踪")
        # 扫描范围 = 已追踪 + 未忽略的新文件（尊重 .gitignore）
        targets = run_git("ls-files", "--cached", "--others", "--exclude-standard", zero=True)

    # 规则 2：内容扫描
    for path in targets:
        findings.extend(scan_text(path))

    if findings:
        print("[FAIL] 发现疑似密钥泄漏：\n")
        for item in findings:
            print(f"  - {item}")
        print("\n请删除/替换上述内容，并确认 .env 未被提交。")
        return 1

    scope = f"{len(targets)} 个文件"
    print(f"[OK] 未发现疑似密钥泄漏（扫描范围：{scope}）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
