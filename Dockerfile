# ============================================================
# 多阶段构建：依赖安装与运行时分离，最终镜像不含编译工具
# 注意：绝不把 .env 复制进镜像，密钥在运行时通过环境变量注入
# ============================================================

FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements.txt


FROM python:3.11-slim AS runtime

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1 \
    HOME=/tmp

# libgomp1 是 onnxruntime（chromadb 依赖）需要的运行库
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 10001 app \
    && useradd -u 10001 -g app -m -d /home/app app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY backend ./backend
COPY frontend ./frontend
COPY scripts ./scripts
COPY data ./data
COPY requirements.txt run.py ./

# 以非 root 用户运行；chown 必须在 USER 之前
RUN mkdir -p /app/chroma_db \
    && chown -R app:app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"

# 单 worker：MemorySaver 与进程内缓存/限流不跨进程共享（见 README「扩展限制」）
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]
