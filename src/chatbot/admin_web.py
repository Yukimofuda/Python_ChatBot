from __future__ import annotations

from typing import Any

from fastapi import Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from src.chatbot.runtime import recent_messages, runtime_status, send_onebot_v11_message
from src.chatbot.settings import get_settings


class SendMessagePayload(BaseModel):
    target_type: str = Field(pattern="^(group|private)$")
    target_id: int
    message: str = Field(min_length=1, max_length=4000)
    bot_id: str | None = None
    token: str = ""


def _require_admin(token: str = "", header_token: str = "") -> None:
    expected = get_settings().admin_token
    if expected and token != expected and header_token != expected:
        raise HTTPException(status_code=401, detail="Invalid admin token")


def setup_admin_routes(app: Any) -> None:
    if not get_settings().admin_enabled:
        return

    @app.get("/", response_class=HTMLResponse)
    async def root() -> HTMLResponse:
        return HTMLResponse(
            '<meta http-equiv="refresh" content="0; url=/admin">'
            '<a href="/admin">Open admin console</a>'
        )

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return runtime_status()

    @app.get("/admin", response_class=HTMLResponse)
    async def admin_page() -> HTMLResponse:
        return HTMLResponse(ADMIN_HTML)

    @app.get("/admin/api/status")
    async def admin_status() -> dict[str, Any]:
        return runtime_status()

    @app.get("/admin/api/messages")
    async def admin_messages() -> dict[str, Any]:
        return {"items": recent_messages()}

    @app.post("/admin/api/send")
    async def admin_send(
        payload: SendMessagePayload,
        request: Request,
        x_admin_token: str = Header(default=""),
    ) -> dict[str, Any]:
        _require_admin(payload.token, x_admin_token)
        result = await send_onebot_v11_message(
            target_type=payload.target_type,
            target_id=payload.target_id,
            message=payload.message,
            bot_id=payload.bot_id,
        )
        return {
            "ok": True,
            "client": request.client.host if request.client else "",
            "result": result,
        }


ADMIN_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Bot Admin</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #172026;
      --muted: #697780;
      --line: #dce3e8;
      --accent: #087f8c;
      --accent-strong: #065f69;
      --danger: #b42318;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--bg); color: var(--text); }
    header {
      min-height: 72px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 18px 28px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }
    h1 { margin: 0; font-size: 22px; font-weight: 750; }
    main {
      width: min(1180px, calc(100vw - 32px));
      margin: 20px auto 40px;
      display: grid;
      gap: 16px;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }
    section, .metric {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    section { padding: 18px; }
    .metric { padding: 14px; min-height: 86px; }
    .metric span, label { color: var(--muted); font-size: 13px; }
    .metric strong {
      display: block;
      margin-top: 8px;
      font-size: 22px;
      overflow-wrap: anywhere;
    }
    h2 { margin: 0 0 14px; font-size: 16px; }
    form {
      display: grid;
      grid-template-columns: 150px 1fr 1fr;
      gap: 12px;
      align-items: end;
    }
    input, select, textarea {
      width: 100%;
      min-height: 40px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px 10px;
      font: inherit;
      background: #fff;
      color: var(--text);
    }
    textarea { grid-column: 1 / -1; min-height: 92px; resize: vertical; }
    button {
      min-height: 40px;
      border: 0;
      border-radius: 6px;
      padding: 0 16px;
      background: var(--accent);
      color: #fff;
      font-weight: 700;
      cursor: pointer;
    }
    button:hover { background: var(--accent-strong); }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th, td {
      padding: 10px 8px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }
    th { color: var(--muted); font-size: 12px; font-weight: 700; }
    td { overflow-wrap: anywhere; }
    .muted { color: var(--muted); }
    .error { color: var(--danger); }
    .row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
    code {
      padding: 2px 5px;
      border-radius: 5px;
      background: #eef2f4;
      font-size: 13px;
    }
    @media (max-width: 820px) {
      header { padding: 16px; align-items: flex-start; flex-direction: column; }
      .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      form { grid-template-columns: 1fr; }
      textarea { grid-column: auto; }
    }
    @media (max-width: 520px) {
      .grid { grid-template-columns: 1fr; }
      main { width: calc(100vw - 20px); }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Bot Admin</h1>
      <div class="muted">OneBot V11 控制台</div>
    </div>
    <div class="row">
      <span class="muted">反向 WS</span>
      <code id="ws">ws://127.0.0.1:8080/onebot/v11/ws</code>
    </div>
  </header>
  <main>
    <div class="grid">
      <div class="metric"><span>服务状态</span><strong id="ok">-</strong></div>
      <div class="metric"><span>在线 Bot</span><strong id="bots">-</strong></div>
      <div class="metric"><span>适配器</span><strong id="adapters">-</strong></div>
      <div class="metric"><span>运行时间</span><strong id="uptime">-</strong></div>
    </div>
    <section>
      <h2>发送 OneBot 消息</h2>
      <form id="send-form">
        <label>目标类型
          <select name="target_type">
            <option value="group">群聊</option>
            <option value="private">私聊</option>
          </select>
        </label>
        <label>目标账号 / 群号
          <input name="target_id" inputmode="numeric" placeholder="例如 123456789" required>
        </label>
        <label>Bot 账号，可留空
          <input name="bot_id" placeholder="自动选择已连接 OneBot V11">
        </label>
        <label>管理 Token
          <input name="token" type="password" placeholder="本地未设置可留空">
        </label>
        <button type="submit">发送</button>
        <textarea name="message" placeholder="输入要发送的消息" required></textarea>
      </form>
      <p id="send-result" class="muted"></p>
    </section>
    <section>
      <h2>最近消息</h2>
      <table>
        <thead>
          <tr>
            <th>时间</th><th>来源</th><th>会话</th><th>用户</th><th>内容</th>
          </tr>
        </thead>
        <tbody id="messages"></tbody>
      </table>
    </section>
  </main>
  <script>
    const $ = (id) => document.getElementById(id);
    const fmtUptime = (seconds) => {
      const h = Math.floor(seconds / 3600);
      const m = Math.floor((seconds % 3600) / 60);
      const s = seconds % 60;
      return `${h}h ${m}m ${s}s`;
    };
    async function refresh() {
      const status = await fetch('/admin/api/status').then((r) => r.json());
      $('ok').textContent = status.ok ? '正常' : '异常';
      $('bots').textContent = status.bots.length ? status.bots.map((b) => b.self_id).join(', ') : '未连接';
      $('adapters').textContent = status.adapters.join(', ') || '无';
      $('uptime').textContent = fmtUptime(status.uptime_seconds);
      $('ws').textContent = status.onebot_v11_reverse_ws;

      const messages = await fetch('/admin/api/messages').then((r) => r.json());
      $('messages').innerHTML = messages.items.map((item) => `
        <tr>
          <td>${new Date(item.time).toLocaleTimeString()}</td>
          <td>${item.adapter}<br><span class="muted">${item.detail_type || item.event_type}</span></td>
          <td>${item.group_id ? `群 ${item.group_id}` : item.session_id}</td>
          <td>${item.user_id}</td>
          <td>${item.text || '<span class="muted">非文本消息</span>'}</td>
        </tr>
      `).join('');
    }
    $('send-form').addEventListener('submit', async (event) => {
      event.preventDefault();
      const data = Object.fromEntries(new FormData(event.currentTarget).entries());
      data.target_id = Number(data.target_id);
      const result = $('send-result');
      result.className = 'muted';
      result.textContent = '发送中...';
      try {
        const response = await fetch('/admin/api/send', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(data),
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || '发送失败');
        result.textContent = '已发送';
        event.currentTarget.message.value = '';
        refresh();
      } catch (error) {
        result.className = 'error';
        result.textContent = error.message;
      }
    });
    refresh();
    setInterval(refresh, 3000);
  </script>
</body>
</html>
"""
