PYTHON ?= python
COMPOSE ?= docker compose

.PHONY: help install install-dev run test lint format check-secrets eval docker-up docker-down docker-logs

help:
	@echo "install       安装生产依赖"
	@echo "install-dev   安装开发/测试依赖"
	@echo "run           本地启动服务"
	@echo "test          运行测试"
	@echo "lint          静态检查"
	@echo "format        格式化代码"
	@echo "check-secrets 提交前密钥扫描"
	@echo "eval          运行检索效果评测（需要真实 API Key）"
	@echo "docker-up     构建并启动 Docker Compose"
	@echo "docker-down   停止容器"
	@echo "docker-logs   查看容器日志"

install:
	$(PYTHON) -m pip install -r requirements.txt

install-dev:
	$(PYTHON) -m pip install -r requirements-dev.txt

run:
	$(PYTHON) run.py

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check .

format:
	$(PYTHON) -m ruff format .

check-secrets:
	$(PYTHON) scripts/check_secrets.py

eval:
	$(PYTHON) scripts/eval_retrieval.py

docker-up:
	$(COMPOSE) up -d --build

docker-down:
	$(COMPOSE) down

docker-logs:
	$(COMPOSE) logs -f app
