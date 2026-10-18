# -*- coding: utf-8 -*-
"""HTTP 接口测试：鉴权、健康检查、校验、SSE 协议。

外部检索/模型调用全部被 monkeypatch，测试不联网、不消耗额度。
"""
from __future__ import annotations

from backend.api import routes_agent, routes_chat
from backend.core.rate_limit import SlidingWindowLimiter


def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "X-Request-ID" in response.headers


def test_chat_requires_key(client):
    response = client.post("/api/chat", json={"question": "你好"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_chat_rejects_wrong_key(client):
    response = client.post(
        "/api/chat", json={"question": "你好"}, headers={"X-API-Key": "wrong"}
    )
    assert response.status_code == 401


def test_chat_ok(client, headers, monkeypatch):
    monkeypatch.setattr(
        routes_chat, "answer", lambda question: {"answer": "测试答案", "sources": []}
    )
    response = client.post("/api/chat", json={"question": "你好"}, headers=headers)
    assert response.status_code == 200
    assert response.json() == {"answer": "测试答案", "sources": []}


def test_bearer_token_supported(client, monkeypatch):
    monkeypatch.setattr(
        routes_chat, "answer", lambda question: {"answer": "ok", "sources": []}
    )
    response = client.post(
        "/api/chat",
        json={"question": "你好"},
        headers={"Authorization": "Bearer test-key"},
    )
    assert response.status_code == 200


def test_question_validation(client, headers):
    empty = client.post("/api/chat", json={"question": ""}, headers=headers)
    assert empty.status_code == 422

    bad_session = client.post(
        "/api/chat",
        json={"question": "你好", "session_id": "bad id!"},
        headers=headers,
    )
    assert bad_session.status_code == 422


def test_agent_ok(client, headers, monkeypatch):
    async def fake_collect(question, thread_id="default"):
        return {"answer": "2", "tool_calls": ["calculator"], "sources": []}

    monkeypatch.setattr(routes_agent, "run_collect", fake_collect)
    response = client.post(
        "/api/agent", json={"question": "1+1", "session_id": "s1"}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["tool_calls"] == ["calculator"]


def test_chat_stream_protocol(client, headers, monkeypatch):
    async def fake_stream(question):
        yield "token", {"text": "你"}
        yield "token", {"text": "好"}
        yield "sources", {"sources": []}
        yield "done", {"answer": "你好", "sources": []}

    monkeypatch.setattr(routes_chat, "answer_stream", fake_stream)

    with client.stream(
        "POST", "/api/chat/stream", json={"question": "hi"}, headers=headers
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())

    assert "event: meta" in body
    assert "event: token" in body
    assert '"text": "你"' in body
    assert "event: done" in body
    # 帧之间以空行分隔
    assert body.count("\n\n") >= 4


def test_rate_limiter_window():
    limiter = SlidingWindowLimiter(limit=2, window_seconds=60)
    assert limiter.hit("client-a")[0] is True
    assert limiter.hit("client-a")[0] is True

    allowed, retry_after = limiter.hit("client-a")
    assert allowed is False
    assert retry_after >= 1

    # 不同 key 互不影响
    assert limiter.hit("client-b")[0] is True


def test_request_id_echo(client):
    response = client.get("/healthz", headers={"X-Request-ID": "abcdef12"})
    assert response.headers["X-Request-ID"] == "abcdef12"


def test_security_headers(client):
    response = client.get("/healthz")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
