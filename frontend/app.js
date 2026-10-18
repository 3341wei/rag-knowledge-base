/* 企业级 RAG 知识库前端
 *
 * 安全要点：
 * - 所有动态内容都用 textContent / createTextNode 写入，不拼接 innerHTML，
 *   避免文档内容或模型输出造成 XSS；
 * - 访问密钥只存 sessionStorage（仅当前标签页），不写 cookie / localStorage。
 */
"use strict";

const STORAGE_KEY = "rag_api_key";
const STORAGE_SESSION = "rag_session_id";

const state = {
  mode: "agent",
  controller: null,
  streaming: false,
};

const $ = (id) => document.getElementById(id);

/* ---------------- 会话与密钥 ---------------- */

function makeSessionId() {
  const rand = (window.crypto && crypto.randomUUID)
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `sess-${rand.replace(/[^A-Za-z0-9_-]/g, "").slice(0, 40)}`;
}

function getSessionId() {
  let id = sessionStorage.getItem(STORAGE_SESSION);
  if (!id) {
    id = makeSessionId();
    sessionStorage.setItem(STORAGE_SESSION, id);
  }
  return id;
}

function getApiKey() {
  return sessionStorage.getItem(STORAGE_KEY) || "";
}

function authHeaders(extra = {}) {
  const headers = { "Content-Type": "application/json", ...extra };
  const key = getApiKey();
  if (key) headers["X-API-Key"] = key;
  return headers;
}

/* ---------------- 消息渲染 ---------------- */

function clearHint() {
  const hint = $("hint");
  if (hint) hint.remove();
}

function addMessage(role, text = "") {
  clearHint();
  const chat = $("chat");
  const wrap = document.createElement("div");
  wrap.className = `msg ${role}`;

  const label = document.createElement("div");
  label.className = "label";
  label.textContent = role === "user" ? "你" : "AI 助手";

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text; // textContent，天然转义

  wrap.append(label, bubble);
  chat.appendChild(wrap);
  chat.scrollTop = chat.scrollHeight;
  return wrap;
}

function setBubble(wrap, text) {
  const bubble = wrap.querySelector(".bubble");
  if (bubble) bubble.textContent = text;
  const chat = $("chat");
  chat.scrollTop = chat.scrollHeight;
}

function appendToken(wrap, text) {
  const bubble = wrap.querySelector(".bubble");
  if (!bubble) return;
  bubble.textContent += text;
  const chat = $("chat");
  chat.scrollTop = chat.scrollHeight;
}

function renderSources(wrap, sources) {
  if (!sources || sources.length === 0) return;
  const box = document.createElement("div");
  box.className = "sources";

  sources.forEach((item) => {
    const el = document.createElement("div");
    el.className = "source";

    const name = document.createElement("span");
    name.className = "src-name";
    name.textContent = item.source || "未知来源";
    el.append("📄 来源 ", name);

    if (typeof item.score === "number") {
      const score = document.createElement("span");
      score.className = "src-score";
      score.textContent = ` 相关度 ${item.score}`;
      el.append(score);
    }

    const content = document.createElement("span");
    content.textContent = `：${item.content || ""}`;
    el.append(content);
    box.appendChild(el);
  });

  wrap.appendChild(box);
  const chat = $("chat");
  chat.scrollTop = chat.scrollHeight;
}

function renderToolCalls(wrap, tools) {
  if (!tools || tools.length === 0) return;
  const box = document.createElement("div");
  box.className = "toolcalls";
  box.append("🧠 调用工具：");
  tools.forEach((tool, index) => {
    if (index > 0) box.append(" → ");
    const chip = document.createElement("span");
    chip.className = "tool";
    chip.textContent = tool;
    box.append(chip);
  });
  wrap.appendChild(box);
}

function showError(wrap, message) {
  const box = document.createElement("div");
  box.className = "error-box";
  box.setAttribute("role", "alert");
  box.textContent = message;
  wrap.appendChild(box);
  const chat = $("chat");
  chat.scrollTop = chat.scrollHeight;
}

/* ---------------- SSE 解析 ---------------- */

function parseFrame(frame) {
  let event = "message";
  const dataLines = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
  }
  if (dataLines.length === 0) return null;
  try {
    return { event, data: JSON.parse(dataLines.join("\n")) };
  } catch (err) {
    return null;
  }
}

async function consumeSSE(response, onEvent) {
  if (!response.body) throw new Error("当前浏览器不支持流式响应");
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    buffer = buffer.replace(/\r\n/g, "\n");

    let index;
    while ((index = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, index);
      buffer = buffer.slice(index + 2);
      const parsed = parseFrame(frame);
      if (parsed) onEvent(parsed.event, parsed.data);
    }
  }

  buffer += decoder.decode();
  const tail = parseFrame(buffer.trim());
  if (tail) onEvent(tail.event, tail.data);
}

/* ---------------- 请求 ---------------- */

async function readError(response) {
  let payload = null;
  try {
    payload = await response.json();
  } catch (err) {
    /* 忽略非 JSON 错误体 */
  }
  const err = payload && payload.error ? payload.error : {};
  return {
    status: response.status,
    code: err.code || `HTTP_${response.status}`,
    message: err.message || `请求失败（HTTP ${response.status}）`,
    requestId: err.request_id || "",
  };
}

function friendlyError(err) {
  if (err.status === 401) return "访问密钥无效或缺失，请点击右上角「设置」填写。";
  if (err.status === 429) return err.message || "请求过于频繁，请稍后重试。";
  if (err.status === 413) return "问题内容过长，请精简后重试。";
  if (err.status === 503) return err.message || "服务暂未就绪（请检查密钥配置或先重建索引）。";
  if (err.status === 504) return "模型服务响应超时，请稍后重试。";
  const suffix = err.requestId ? `（请求 ID：${err.requestId}）` : "";
  return `${err.message}${suffix}`;
}

function setStreaming(active) {
  state.streaming = active;
  $("sendBtn").disabled = active;
  $("sendBtn").classList.toggle("hidden", active);
  $("stopBtn").classList.toggle("hidden", !active);
  $("question").disabled = active;
}

async function streamChat(url, question, wrap, handlers) {
  const controller = new AbortController();
  state.controller = controller;

  const response = await fetch(url, {
    method: "POST",
    headers: authHeaders({ Accept: "text/event-stream" }),
    body: JSON.stringify({ question, session_id: getSessionId() }),
    signal: controller.signal,
  });

  if (!response.ok) {
    throw await readError(response);
  }

  await consumeSSE(response, (event, data) => {
    if (event === "token") {
      appendToken(wrap, data.text || "");
      handlers.onToken && handlers.onToken(data);
    } else if (event === "reset") {
      setBubble(wrap, "");
      handlers.onReset && handlers.onReset(data);
    } else if (event === "tool") {
      handlers.onTool && handlers.onTool(data);
    } else if (event === "sources") {
      handlers.onSources && handlers.onSources(data.sources || []);
    } else if (event === "done") {
      handlers.onDone && handlers.onDone(data);
    } else if (event === "error") {
      handlers.onError && handlers.onError(data);
    }
  });
}

async function send() {
  if (state.streaming) return;

  const input = $("question");
  const question = input.value.trim();
  if (!question) return;

  addMessage("user", question);
  input.value = "";

  const wrap = addMessage("ai", "");
  const bubble = wrap.querySelector(".bubble");
  bubble.classList.add("streaming");

  const tools = [];
  let finalSources = [];

  setStreaming(true);

  try {
    const url = state.mode === "agent" ? "/api/agent/stream" : "/api/chat/stream";
    await streamChat(url, question, wrap, {
      onToken: () => {},
      onReset: () => {
        // 模型决定调用工具，清空过程性文字
      },
      onTool: (data) => {
        if (data.name && !tools.includes(data.name)) tools.push(data.name);
      },
      onSources: (sources) => {
        finalSources = sources;
      },
      onDone: (data) => {
        if (data.answer) setBubble(wrap, data.answer);
        renderToolCalls(wrap, data.tool_calls || tools);
        renderSources(wrap, data.sources || finalSources);
      },
      onError: (data) => {
        const suffix = data.request_id ? `（请求 ID：${data.request_id}）` : "";
        showError(wrap, `${data.message || "生成失败，请稍后重试"}${suffix}`);
      },
    });
  } catch (err) {
    if (err.name === "AbortError") {
      showError(wrap, "已停止生成。");
    } else {
      showError(wrap, friendlyError(err));
      if (err.status === 401) openSettings();
    }
  } finally {
    bubble.classList.remove("streaming");
    setStreaming(false);
    state.controller = null;
    input.focus();
  }
}

/* ---------------- 工具操作 ---------------- */

async function rebuildIndex() {
  if (!window.confirm("重建索引会重新对所有文档做向量化，可能消耗 Embedding 额度。确认继续？")) {
    return;
  }
  const btn = $("rebuildBtn");
  btn.disabled = true;
  const original = btn.textContent;
  btn.textContent = "索引重建中…";

  try {
    const response = await fetch("/api/ingest", {
      method: "POST",
      headers: authHeaders(),
    });
    if (!response.ok) throw await readError(response);
    const data = await response.json();
    setStatus(
      `✅ 索引完成：${data.documents} 篇文档，${data.chunks} 个片段（${data.collection}）`
    );
  } catch (err) {
    setStatus(`❌ 重建失败：${friendlyError(err)}`, true);
  } finally {
    btn.disabled = false;
    btn.textContent = original;
  }
}

async function loadStatus() {
  try {
    const response = await fetch("/api/stats", { headers: authHeaders() });
    if (!response.ok) {
      if (response.status === 401) {
        setStatus("🔑 服务端已启用鉴权，请点击右上角「设置」填写访问密钥。", true);
      } else {
        setStatus("无法获取服务状态。", true);
      }
      return;
    }
    const data = await response.json();
    setStatus(
      `知识库：${data.documents} 篇文档 / ${data.chunks} 个片段 · 索引 ${data.collection} · 已运行 ${formatUptime(data.uptime_seconds)}`
    );
  } catch (err) {
    setStatus("无法连接后端服务。", true);
  }
}

function formatUptime(seconds) {
  if (!seconds || seconds < 60) return `${seconds || 0} 秒`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟`;
  return `${Math.floor(seconds / 3600)} 小时`;
}

function setStatus(text, isError = false) {
  const bar = $("statusbar");
  bar.textContent = text;
  bar.classList.toggle("error", isError);
}

/* ---------------- 设置与初始化 ---------------- */

function openSettings() {
  const input = $("apiKeyInput");
  input.value = getApiKey();
  const dialog = $("settingsDialog");
  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.setAttribute("open", "");
}

function bindEvents() {
  $("sendBtn").addEventListener("click", send);
  $("stopBtn").addEventListener("click", () => {
    if (state.controller) state.controller.abort();
  });
  $("question").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      send();
    }
  });

  $("modeAgent").addEventListener("click", () => setMode("agent"));
  $("modeRag").addEventListener("click", () => setMode("rag"));

  $("newSessionBtn").addEventListener("click", () => {
    sessionStorage.setItem(STORAGE_SESSION, makeSessionId());
    $("chat").replaceChildren();
    const hint = document.createElement("div");
    hint.className = "hint";
    hint.id = "hint";
    hint.textContent = "已开始新会话，在下方输入问题 👇";
    $("chat").appendChild(hint);
    setStatus("已创建新会话。");
  });

  $("settingsBtn").addEventListener("click", openSettings);
  $("closeSettingsBtn").addEventListener("click", () => $("settingsDialog").close());
  $("saveKeyBtn").addEventListener("click", () => {
    const value = $("apiKeyInput").value.trim();
    if (value) sessionStorage.setItem(STORAGE_KEY, value);
    else sessionStorage.removeItem(STORAGE_KEY);
    $("settingsDialog").close();
    setStatus(value ? "访问密钥已保存到当前标签页。" : "访问密钥已清除。");
    loadStatus();
  });
  $("clearKeyBtn").addEventListener("click", () => {
    sessionStorage.removeItem(STORAGE_KEY);
    $("apiKeyInput").value = "";
  });

  $("rebuildBtn").addEventListener("click", rebuildIndex);
}

function setMode(mode) {
  state.mode = mode;
  $("modeAgent").classList.toggle("active", mode === "agent");
  $("modeRag").classList.toggle("active", mode === "rag");
}

document.addEventListener("DOMContentLoaded", () => {
  bindEvents();
  loadStatus();
});
