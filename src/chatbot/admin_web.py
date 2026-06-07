from __future__ import annotations

from typing import Any

from fastapi.responses import HTMLResponse

from src.chatbot.runtime import recent_messages, runtime_status
from src.chatbot.settings import get_settings


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


ADMIN_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Python Bot Admin</title>
  <style>
    :root {
      --bg: #f2efe8;
      --panel: rgba(255, 251, 242, 0.92);
      --ink: #1e2328;
      --muted: #6d736f;
      --line: rgba(30, 35, 40, 0.12);
      --accent: #bf5b32;
      --accent-soft: #f5d4b0;
      font-family: "Avenir Next", "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at top right, rgba(191, 91, 50, 0.16), transparent 28%),
        linear-gradient(180deg, #fcf7ee 0%, #efe5d5 100%);
    }
    header, main { width: min(1100px, calc(100vw - 28px)); margin: 0 auto; }
    header { padding: 28px 0 18px; }
    h1 { margin: 0; font-size: 32px; letter-spacing: 0.02em; }
    .subtitle { margin-top: 8px; color: var(--muted); }
    .grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 14px;
      margin: 18px 0;
    }
    .card, section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: 0 18px 40px rgba(70, 50, 30, 0.08);
      backdrop-filter: blur(8px);
    }
    .card { padding: 18px; }
    .card span { color: var(--muted); font-size: 13px; }
    .card strong { display: block; margin-top: 10px; font-size: 24px; }
    section { padding: 20px; margin-bottom: 18px; }
    h2 { margin: 0 0 14px; font-size: 17px; }
    table { width: 100%; border-collapse: collapse; }
    th, td {
      padding: 10px 8px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      font-size: 14px;
      overflow-wrap: anywhere;
    }
    th { color: var(--muted); font-size: 12px; }
    code {
      display: inline-block;
      padding: 4px 8px;
      background: var(--accent-soft);
      border-radius: 999px;
      font-size: 12px;
    }
    @media (max-width: 860px) {
      .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 520px) {
      .grid { grid-template-columns: 1fr; }
      h1 { font-size: 26px; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Python Bot Admin</h1>
    <div class="subtitle">Readonly local status panel for the public-safe build.</div>
  </header>
  <main>
    <div class="grid">
      <div class="card"><span>Service</span><strong id="ok">-</strong></div>
      <div class="card"><span>Adapters</span><strong id="adapters">-</strong></div>
      <div class="card"><span>Connected Bots</span><strong id="bots">-</strong></div>
      <div class="card"><span>Uptime</span><strong id="uptime">-</strong></div>
    </div>
    <section>
      <h2>Connection</h2>
      <p>OneBot V11 reverse WebSocket:</p>
      <code id="ws">ws://127.0.0.1:8080/onebot/v11/ws</code>
    </section>
    <section>
      <h2>Recent Activity</h2>
      <table>
        <thead>
          <tr>
            <th>Time</th><th>Adapter</th><th>Conversation</th><th>Speaker</th><th>Text</th>
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
      $('ok').textContent = status.ok ? 'healthy' : 'down';
      $('adapters').textContent = status.adapters.join(', ') || 'none';
      $('bots').textContent = status.bots.length ? status.bots.length : '0';
      $('uptime').textContent = fmtUptime(status.uptime_seconds);
      $('ws').textContent = status.onebot_ws_url;

      const messages = await fetch('/admin/api/messages').then((r) => r.json());
      $('messages').innerHTML = messages.items.map((item) => `
        <tr>
          <td>${item.time}</td>
          <td>${item.adapter}</td>
          <td>${item.conversation}</td>
          <td>${item.speaker}</td>
          <td>${(item.text || '').replace(/</g, '&lt;')}</td>
        </tr>
      `).join('') || '<tr><td colspan="5">No messages yet.</td></tr>';
    }
    refresh();
    setInterval(refresh, 5000);
  </script>
</body>
</html>
"""
