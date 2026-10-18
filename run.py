# -*- coding: utf-8 -*-
"""本地启动脚本。

    python run.py

开发模式（APP_ENV=development）自动开启热重载；
生产/测试模式关闭，按配置的 host/port 启动。
"""
from __future__ import annotations

import uvicorn

from backend.core.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "backend.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.app_env == "development",
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
