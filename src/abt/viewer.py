"""The /viewer page: a self-contained browser for recorded sessions.

Kept as one string with no external assets so it works with the browser offline
and needs no static-file mount.
"""

VIEWER_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>abt session logs</title>
<style>
  :root {
    --bg: #fbfbfa; --panel: #fff; --line: #e4e4e1; --ink: #1a1a19;
    --muted: #6b6b66; --accent: #2f6f4e; --bad: #a8322d; --code: #f4f4f2;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #16171a; --panel: #1d1e22; --line: #2e3036; --ink: #e8e8e6;
      --muted: #9a9a94; --accent: #6ec296; --bad: #e8837e; --code: #131417;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--ink);
    font: 14px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  }
  header {
    padding: 14px 20px; border-bottom: 1px solid var(--line);
    display: flex; align-items: baseline; gap: 16px; flex-wrap: wrap;
    background: var(--panel);
  }
  h1 { font-size: 15px; margin: 0; letter-spacing: -0.01em; }
  .sub { color: var(--muted); font-size: 12.5px; }
  .layout { display: grid; grid-template-columns: 290px 1fr; min-height: calc(100vh - 53px); }
  @media (max-width: 800px) { .layout { grid-template-columns: 1fr; } }
  aside { border-right: 1px solid var(--line); background: var(--panel); overflow-y: auto; }
  .tabs { display: flex; border-bottom: 1px solid var(--line); }
  .tabs button {
    flex: 1; padding: 10px; background: none; border: none; cursor: pointer;
    color: var(--muted); font: inherit; font-size: 13px; border-bottom: 2px solid transparent;
  }
  .tabs button.on { color: var(--ink); border-bottom-color: var(--accent); font-weight: 600; }
  .row {
    padding: 11px 16px; border-bottom: 1px solid var(--line); cursor: pointer;
  }
  .row:hover { background: var(--code); }
  .row.on { background: var(--code); box-shadow: inset 3px 0 0 var(--accent); }
  .row b { display: block; font-weight: 600; font-size: 13px; }
  .row span { color: var(--muted); font-size: 12px; }
  main { padding: 18px 22px; overflow-x: auto; }
  .filters { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }
  .filters select, .filters label {
    font: inherit; font-size: 12.5px; padding: 5px 8px; border-radius: 6px;
    border: 1px solid var(--line); background: var(--panel); color: var(--ink);
  }
  .filters label { display: flex; align-items: center; gap: 6px; cursor: pointer; }
  .ev {
    border: 1px solid var(--line); border-radius: 8px; margin-bottom: 9px;
    background: var(--panel); overflow: hidden;
  }
  .ev > summary {
    padding: 10px 13px; cursor: pointer; display: flex; gap: 10px;
    align-items: center; flex-wrap: wrap; list-style: none;
  }
  .ev > summary::-webkit-details-marker { display: none; }
  .seq { color: var(--muted); font-variant-numeric: tabular-nums; min-width: 34px; font-size: 12px; }
  .op {
    font-family: ui-monospace, "Cascadia Code", Consolas, monospace;
    font-weight: 600; font-size: 13px;
  }
  .pill {
    font-size: 11px; padding: 2px 7px; border-radius: 99px;
    border: 1px solid var(--line); color: var(--muted);
  }
  .ok { color: var(--accent); border-color: var(--accent); }
  .err { color: var(--bad); border-color: var(--bad); }
  .grow { flex: 1; }
  pre {
    margin: 0; padding: 12px 13px; background: var(--code); font-size: 12.5px;
    overflow-x: auto; border-top: 1px solid var(--line);
    font-family: ui-monospace, "Cascadia Code", Consolas, monospace;
  }
  .pane-title { font-size: 11px; color: var(--muted); padding: 8px 13px 0; text-transform: uppercase; letter-spacing: .06em; }
  .empty { color: var(--muted); padding: 40px 0; text-align: center; }
</style>
</head>
<body>
<header>
  <h1>abt session logs</h1>
  <span class="sub" id="hint">loading…</span>
</header>

<div class="layout">
  <aside>
    <div class="tabs">
      <button id="tab-sessions" class="on">Sessions</button>
      <button id="tab-sites">Sites</button>
    </div>
    <div id="list"></div>
  </aside>
  <main>
    <div class="filters" id="filters" hidden>
      <select id="f-tab"><option value="">all tabs</option></select>
      <select id="f-site"><option value="">all sites</option></select>
      <select id="f-op"><option value="">all ops</option></select>
      <label><input type="checkbox" id="f-err"> errors only</label>
    </div>
    <div id="events"><div class="empty">Pick a session or a site.</div></div>
  </main>
</div>

<script>
const $ = (s) => document.querySelector(s);
let mode = "sessions", sessions = [], sites = [], current = null, siteFilter = null, events = [];

const esc = (s) => String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const when = (iso) => iso ? new Date(iso).toLocaleString() : "—";

async function get(url) {
  const r = await fetch(url);
  const b = await r.json();
  if (!b.ok) throw new Error((b.error && b.error.message) || "request failed");
  return b.result;
}

async function boot() {
  const data = await get("/logs");
  sessions = data.sessions || [];
  sites = await get("/logs/sites");
  $("#hint").textContent = data.recording
    ? `recording → ${data.current} · ${sessions.length} session(s)`
    : "recording disabled (start with --log-dir)";
  draw();
  if (sessions.length) pickSession(sessions[0].session_id);
}

function draw() {
  const list = $("#list");
  $("#tab-sessions").classList.toggle("on", mode === "sessions");
  $("#tab-sites").classList.toggle("on", mode === "sites");
  const rows = mode === "sessions"
    ? sessions.map(s => ({
        key: s.session_id,
        title: s.session_id + (s.ended_at ? "" : " · live"),
        sub: `${s.events} events · ${s.errors} error(s) · ${when(s.started_at)}`
      }))
    : sites.map(s => ({
        key: s.site,
        title: s.site,
        sub: `${s.events} events · ${s.errors} error(s) · ${s.sessions.length} session(s)`
      }));
  list.innerHTML = rows.length
    ? rows.map(r => `<div class="row" data-key="${esc(r.key)}"><b>${esc(r.title)}</b><span>${esc(r.sub)}</span></div>`).join("")
    : `<div class="empty">nothing recorded yet</div>`;
  list.querySelectorAll(".row").forEach(el => {
    el.onclick = () => mode === "sessions" ? pickSession(el.dataset.key) : pickSite(el.dataset.key);
  });
}

async function pickSession(id) {
  current = id; siteFilter = null;
  markActive(id);
  const data = await get(`/logs/${encodeURIComponent(id)}`);
  events = data.events;
  fillFilters(data.tabs, data.sites);
  render();
}

async function pickSite(site) {
  siteFilter = site;
  markActive(site);
  const row = sites.find(s => s.site === site);
  events = [];
  for (const id of (row ? row.sessions : [])) {
    const data = await get(`/logs/${encodeURIComponent(id)}?site=${encodeURIComponent(site)}`);
    events = events.concat(data.events);
  }
  events.sort((a, b) => (a.at || "").localeCompare(b.at || "") );
  fillFilters([...new Set(events.map(e => e.tab_id).filter(Boolean))], [site]);
  render();
}

function markActive(key) {
  document.querySelectorAll(".row").forEach(el => el.classList.toggle("on", el.dataset.key === key));
}

function fillFilters(tabs, siteList) {
  $("#filters").hidden = false;
  const set = (sel, values, label) => {
    const keep = sel.value;
    sel.innerHTML = `<option value="">${label}</option>` +
      values.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join("");
    sel.value = values.includes(keep) ? keep : "";
  };
  set($("#f-tab"), tabs, "all tabs");
  set($("#f-site"), siteList, "all sites");
  set($("#f-op"), [...new Set(events.map(e => e.op).filter(Boolean))].sort(), "all ops");
}

function render() {
  const tab = $("#f-tab").value, site = $("#f-site").value;
  const op = $("#f-op").value, only = $("#f-err").checked;
  const shown = events.filter(e =>
    (!tab || e.tab_id === tab) && (!site || e.site === site) &&
    (!op || e.op === op) && (!only || !e.ok));

  $("#events").innerHTML = shown.length ? shown.map(e => `
    <details class="ev">
      <summary>
        <span class="seq">#${e.seq}</span>
        <span class="op">${esc(e.op || "?")}</span>
        <span class="pill ${e.ok ? "ok" : "err"}">${e.ok ? "ok" : esc(e.error_type || "error")}</span>
        <span class="grow"></span>
        <span class="pill">${esc(e.tab_id || "—")}</span>
        <span class="pill">${esc(e.site || "—")}</span>
        <span class="pill">${e.duration_ms}ms</span>
      </summary>
      <div class="pane-title">request</div>
      <pre>${esc(JSON.stringify(e.request, null, 2))}</pre>
      <div class="pane-title">${e.ok ? "response" : "error"}</div>
      <pre>${esc(JSON.stringify(e.response, null, 2))}</pre>
    </details>`).join("")
    : `<div class="empty">no events match these filters</div>`;
}

$("#tab-sessions").onclick = () => { mode = "sessions"; draw(); };
$("#tab-sites").onclick = () => { mode = "sites"; draw(); };
["#f-tab", "#f-site", "#f-op", "#f-err"].forEach(s => $(s).onchange = render);

boot().catch(e => { $("#hint").textContent = "error: " + e.message; });
</script>
</body>
</html>
"""
