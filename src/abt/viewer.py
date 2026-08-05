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

  /* --- the audit timeline: one row per command, frame on the left ---------- */
  .summary {
    display: flex; gap: 18px; flex-wrap: wrap; margin-bottom: 14px;
    padding: 11px 14px; border: 1px solid var(--line); border-radius: 8px;
    background: var(--panel); font-size: 12.5px;
  }
  .summary b { font-size: 15px; display: block; font-variant-numeric: tabular-nums; }
  .summary span { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .06em; }
  .summary .bad b { color: var(--bad); }
  .step {
    display: grid; grid-template-columns: 178px 1fr; gap: 14px;
    padding: 12px 0; border-bottom: 1px solid var(--line); align-items: start;
  }
  .step.failed { background: color-mix(in srgb, var(--bad) 7%, transparent); }
  .shot { position: relative; cursor: zoom-in; line-height: 0; }
  .shot img {
    width: 100%; display: block; border-radius: 5px; border: 1px solid var(--line);
    background: var(--code);
  }
  /* Where the command acted. Shared by the thumbnail and the lightbox -- they
     hold the box in different parents, so this cannot be scoped to either. */
  .box {
    position: absolute; border: 2px solid var(--bad); border-radius: 2px;
    box-shadow: 0 0 0 9999px rgba(0,0,0,.12); pointer-events: none;
  }
  .noshot {
    border: 1px dashed var(--line); border-radius: 5px; color: var(--muted);
    font-size: 11px; display: flex; align-items: center; justify-content: center;
    height: 74px; text-align: center; padding: 6px;
  }
  .step-head { display: flex; gap: 9px; align-items: baseline; flex-wrap: wrap; }
  .step-what {
    font-family: ui-monospace, "Cascadia Code", Consolas, monospace; font-size: 13px;
    word-break: break-word;
  }
  .step-meta { color: var(--muted); font-size: 12px; margin-top: 3px; word-break: break-all; }
  .step-err { color: var(--bad); font-size: 12.5px; margin-top: 5px; }
  .step details { margin-top: 7px; }
  .step details summary { cursor: pointer; color: var(--muted); font-size: 12px; }
  .clock { color: var(--muted); font-variant-numeric: tabular-nums; font-size: 12px; }
  @media (max-width: 700px) { .step { grid-template-columns: 1fr; } }

  #lightbox {
    position: fixed; inset: 0; background: rgba(0,0,0,.82); display: none;
    align-items: center; justify-content: center; flex-direction: column; gap: 10px;
    z-index: 50; padding: 24px; cursor: zoom-out;
  }
  #lightbox.on { display: flex; }
  #lightbox .frame { position: relative; max-width: 100%; max-height: 84vh; line-height: 0; }
  #lightbox img { max-width: 100%; max-height: 84vh; border-radius: 6px; }
  #lightbox .cap {
    color: #fff; font-size: 13px; text-align: center; max-width: 900px;
    font-family: ui-monospace, "Cascadia Code", Consolas, monospace;
  }
  #lightbox .hint { color: #bbb; font-size: 11.5px; }
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
      <select id="f-view">
        <option value="timeline">timeline</option>
        <option value="log">raw log</option>
      </select>
      <select id="f-tab"><option value="">all tabs</option></select>
      <select id="f-site"><option value="">all sites</option></select>
      <select id="f-op"><option value="">all ops</option></select>
      <label><input type="checkbox" id="f-err"> errors only</label>
      <label><input type="checkbox" id="f-shot"> with frames only</label>
    </div>
    <div id="events"><div class="empty">Pick a session or a site.</div></div>
  </main>
</div>

<div id="lightbox">
  <div class="frame"><img id="lb-img" alt=""><div class="box" id="lb-box" hidden></div></div>
  <div class="cap" id="lb-cap"></div>
  <div class="hint">← → to step through frames · esc to close</div>
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
        sub: `${s.events} events · ${s.errors} error(s) · ${s.shots || 0} frame(s) · ${when(s.started_at)}`
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

// What the agent did, in words. The raw request is one click away; this line is
// what makes an hour of unattended work skimmable.
function describe(e) {
  const r = e.request || {}, op = e.op || "?";
  const target = r.ref || r.css || r.xpath || (r.text ? `"${r.text}"` : "") || "";
  const nth = (r.index ? ` [#${r.index}]` : "");
  switch (op) {
    case "goto": return `goto ${r.url || ""}`;
    case "input": return `input ${target}${nth} ← ${JSON.stringify(r.value ?? "")}`;
    case "press": return `press ${r.key || ""}${target ? ` on ${target}` : ""}`;
    case "select": return `select ${JSON.stringify(r.value ?? r.label ?? r.option ?? "")} in ${target}`;
    case "scroll": return `scroll ${r.to || (r.by != null ? `by ${r.by}` : "") || target}`;
    case "click_at": return `click at ${r.x},${r.y}`;
    case "messenger_send": return `messenger send → ${r.thread_url || r.to || r.query || ""}`;
    case "messenger_threads": return "messenger: list threads";
    case "messenger_messages": return `messenger: read ${r.thread_url || ""}`;
    default: return target ? `${op} ${target}${nth}` : op;
  }
}

// One line of "and then what happened", pulled from whichever shape the op
// answers with. Anything richer is in the collapsed request/response pane.
function outcome(e) {
  if (!e.ok) return "";
  const r = e.response;
  if (r == null || typeof r !== "object") return r == null ? "" : String(r);
  if (typeof r.count === "number") return `${r.count} match(es)`;
  if (r.tab_id && e.op && e.op.startsWith("tab")) return `now on ${r.tab_id}`;
  if (Array.isArray(r.messages)) return `${r.messages.length} message(s)`;
  if (Array.isArray(r.threads)) return `${r.threads.length} thread(s)`;
  if (r.sent) return "sent";
  return "";
}

function shotUrl(e) {
  return `/logs/${encodeURIComponent(e.session_id)}/shots/${encodeURIComponent(e.shot)}`;
}

function boxStyle(b) {
  return `left:${b.x * 100}%;top:${b.y * 100}%;width:${b.w * 100}%;height:${b.h * 100}%`;
}

function visible() {
  const tab = $("#f-tab").value, site = $("#f-site").value;
  const op = $("#f-op").value, only = $("#f-err").checked, framed = $("#f-shot").checked;
  return events.filter(e =>
    (!tab || e.tab_id === tab) && (!site || e.site === site) &&
    (!op || e.op === op) && (!only || !e.ok) && (!framed || e.shot));
}

function summaryBar(shown) {
  if (!shown.length) return "";
  const errors = shown.filter(e => !e.ok).length;
  const framed = shown.filter(e => e.shot).length;
  const first = shown[0].at, last = shown[shown.length - 1].at;
  let span = "—";
  if (first && last) {
    const secs = Math.max(0, (new Date(last) - new Date(first)) / 1000);
    span = secs >= 3600 ? `${Math.floor(secs / 3600)}h ${Math.round((secs % 3600) / 60)}m`
         : secs >= 60 ? `${Math.floor(secs / 60)}m ${Math.round(secs % 60)}s`
         : `${secs.toFixed(1)}s`;
  }
  const sites = [...new Set(shown.map(e => e.site).filter(Boolean))];
  const cell = (label, value, bad) =>
    `<div class="${bad ? "bad" : ""}"><b>${esc(value)}</b><span>${esc(label)}</span></div>`;
  return `<div class="summary">
    ${cell("commands", shown.length)}
    ${cell("errors", errors, errors > 0)}
    ${cell("elapsed", span)}
    ${cell("frames", framed)}
    ${cell("sites", sites.length === 1 ? sites[0] : sites.length)}
    ${cell("started", when(first))}
  </div>`;
}

function render() {
  const shown = visible();
  const view = $("#f-view").value;
  if (!shown.length) {
    $("#events").innerHTML = `<div class="empty">no events match these filters</div>`;
    return;
  }
  $("#events").innerHTML = summaryBar(shown) +
    (view === "log" ? shown.map(logRow).join("") : shown.map(stepRow).join(""));
  $("#events").querySelectorAll(".shot").forEach(el => {
    el.onclick = () => openShot(Number(el.dataset.seq), el.dataset.session);
  });
}

function stepRow(e) {
  const frame = e.shot
    ? `<div class="shot" data-seq="${e.seq}" data-session="${esc(e.session_id)}">
         <img loading="lazy" src="${esc(shotUrl(e))}" alt="frame for #${e.seq}">
         ${e.shot_box ? `<div class="box" style="${boxStyle(e.shot_box)}"></div>` : ""}
       </div>`
    : `<div class="noshot">no frame<br>(read-only step)</div>`;
  const err = e.ok ? "" :
    `<div class="step-err">${esc(e.error_type || "error")}: ${esc((e.response && e.response.message) || "")}</div>`;
  const out = outcome(e);
  return `<div class="step ${e.ok ? "" : "failed"}">
    ${frame}
    <div>
      <div class="step-head">
        <span class="clock">${esc(e.at ? new Date(e.at).toLocaleTimeString() : "")}</span>
        <span class="step-what">${esc(describe(e))}</span>
        <span class="pill ${e.ok ? "ok" : "err"}">${e.ok ? "ok" : esc(e.error_type || "error")}</span>
        <span class="grow"></span>
        <span class="pill">${esc(e.tab_id || "—")}</span>
        <span class="pill">${e.duration_ms}ms</span>
      </div>
      <div class="step-meta">${esc(e.url || "")}${out ? ` · ${esc(out)}` : ""}</div>
      ${err}
      <details>
        <summary>request &amp; ${e.ok ? "response" : "error"}</summary>
        <pre>${esc(JSON.stringify(e.request, null, 2))}</pre>
        <pre>${esc(JSON.stringify(e.response, null, 2))}</pre>
      </details>
    </div>
  </div>`;
}

function logRow(e) {
  return `
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
    </details>`;
}

// --- lightbox: step through the frames without leaving the timeline ---------
let framed = [], atFrame = -1;

function openShot(seq, sessionId) {
  framed = visible().filter(e => e.shot);
  atFrame = framed.findIndex(e => e.seq === seq && e.session_id === sessionId);
  if (atFrame < 0) return;
  showFrame();
  $("#lightbox").classList.add("on");
}

function showFrame() {
  const e = framed[atFrame];
  if (!e) return;
  $("#lb-img").src = shotUrl(e);
  const box = $("#lb-box");
  if (e.shot_box) { box.hidden = false; box.style.cssText = boxStyle(e.shot_box); }
  else box.hidden = true;
  $("#lb-cap").textContent =
    `#${e.seq} · ${describe(e)} · ${e.ok ? "ok" : (e.error_type || "error")} · ${e.url || ""}`;
}

function stepFrame(delta) {
  if (atFrame < 0) return;
  atFrame = Math.min(framed.length - 1, Math.max(0, atFrame + delta));
  showFrame();
}

$("#lightbox").onclick = () => $("#lightbox").classList.remove("on");
document.addEventListener("keydown", (ev) => {
  if (!$("#lightbox").classList.contains("on")) return;
  if (ev.key === "Escape") $("#lightbox").classList.remove("on");
  if (ev.key === "ArrowRight") { stepFrame(1); ev.preventDefault(); }
  if (ev.key === "ArrowLeft") { stepFrame(-1); ev.preventDefault(); }
});

$("#tab-sessions").onclick = () => { mode = "sessions"; draw(); };
$("#tab-sites").onclick = () => { mode = "sites"; draw(); };
["#f-view", "#f-tab", "#f-site", "#f-op", "#f-err", "#f-shot"].forEach(s => $(s).onchange = render);

boot().catch(e => { $("#hint").textContent = "error: " + e.message; });
</script>
</body>
</html>
"""
