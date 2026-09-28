"""The /app page: the desktop app's whole interface.

One window: the session's browser tab, live, on one side, and a chat with a
model of the person's choosing on the other. Kept as one string with no
external assets, like the log viewer, so it needs no build step and works
offline.

Tokens never travel in this page's source. Inside the desktop shell they come
from pywebview's bridge (`window.pywebview.api`), which reads the owner-only
token files; opened in an ordinary browser, the page asks for the operator
token once and keeps it for the tab's life.
"""

APP_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Browser Toolkit</title>
<style>
  :root {
    --bg: #f6f6f4; --panel: #ffffff; --line: #e2e2de; --ink: #1b1b1a; --muted: #6b6b66;
    --accent: #2f6f4e; --accent-ink: #ffffff; --bad: #a8322d; --soft: #efefeb; --code: #f3f3f0;
    --user: #e8f1ec; --tool: #f4f2ea;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #141517; --panel: #1b1c20; --line: #2c2e34; --ink: #e8e8e6; --muted: #9a9a94;
      --accent: #6ec296; --accent-ink: #0d1f16; --bad: #e8837e; --soft: #23252a; --code: #121316;
      --user: #1f2b25; --tool: #25241f;
    }
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body {
    background: var(--bg); color: var(--ink); display: flex; flex-direction: column;
    font: 13px/1.45 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  }
  button, select, input, textarea {
    font: inherit; color: inherit; background: var(--panel); border: 1px solid var(--line);
    border-radius: 6px;
  }
  button { padding: 4px 10px; cursor: pointer; white-space: nowrap; }
  button:hover { border-color: var(--muted); }
  button.primary { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); }
  button.icon { padding: 4px 8px; }
  button:disabled { opacity: .5; cursor: default; }
  select, input { padding: 4px 6px; }
  label.field { display: flex; flex-direction: column; gap: 4px; margin: 10px 0; }
  label.check { display: flex; gap: 8px; align-items: center; margin: 8px 0; }
  .muted { color: var(--muted); }
  .small { font-size: 12px; }

  #top {
    display: flex; align-items: center; gap: 8px; padding: 8px 12px; flex-wrap: wrap;
    background: var(--panel); border-bottom: 1px solid var(--line);
  }
  #top .brand { font-weight: 600; margin-right: 6px; }
  #top .group { display: flex; align-items: center; gap: 4px; }
  #top .spacer { flex: 1; }
  #status { font-size: 12px; }

  #main { flex: 1; display: flex; min-height: 0; }
  #main.dock-left { flex-direction: row-reverse; }
  #browser { flex: 1; display: flex; flex-direction: column; min-width: 0; }
  #tabs { display: flex; gap: 2px; padding: 6px 8px 0; overflow-x: auto; background: var(--soft); }
  .tab {
    padding: 5px 10px; border: 1px solid var(--line); border-bottom: none; border-radius: 6px 6px 0 0;
    background: var(--bg); max-width: 220px; overflow: hidden; text-overflow: ellipsis;
    white-space: nowrap; cursor: pointer; font-size: 12px;
  }
  .tab.on { background: var(--panel); font-weight: 600; }
  .tab.locked { opacity: .55; cursor: default; }
  #nav { display: flex; gap: 4px; padding: 6px 8px; background: var(--panel); border-bottom: 1px solid var(--line); }
  #url { flex: 1; min-width: 0; }
  #view { flex: 1; overflow: auto; background: var(--code); position: relative; }
  #screen { width: 100%; display: block; outline: none; cursor: default; }
  #screen:focus { box-shadow: inset 0 0 0 2px var(--accent); }
  #viewmsg {
    position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
    text-align: center; padding: 24px; color: var(--muted);
  }

  #splitter { width: 5px; cursor: col-resize; background: var(--line); }
  #chat {
    width: 420px; min-width: 280px; max-width: 70vw; display: flex; flex-direction: column;
    background: var(--panel);
  }
  #main.chat-hidden #chat, #main.chat-hidden #splitter { display: none; }
  #chathead { display: flex; gap: 4px; padding: 8px; border-bottom: 1px solid var(--line); align-items: center; }
  #chatpick { flex: 1; min-width: 0; }
  #messages { flex: 1; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 10px; }
  .msg { padding: 8px 10px; border-radius: 8px; white-space: pre-wrap; word-wrap: break-word; }
  .msg.user { background: var(--user); align-self: flex-end; max-width: 90%; }
  .msg.assistant { background: var(--soft); max-width: 95%; }
  .msg.md { white-space: normal; }
  .md > :first-child { margin-top: 0; } .md > :last-child { margin-bottom: 0; }
  .md p, .md ul, .md ol, .md pre, .md blockquote, .md table { margin: 6px 0; }
  .md h1, .md h2, .md h3, .md h4 { margin: 10px 0 4px; line-height: 1.3; }
  .md h1 { font-size: 16px; } .md h2 { font-size: 15px; } .md h3, .md h4 { font-size: 13.5px; }
  .md ul, .md ol { padding-left: 20px; }
  .md li { margin: 2px 0; }
  .md code {
    background: var(--code); border-radius: 4px; padding: 1px 4px;
    font: 12px ui-monospace, "Cascadia Code", Consolas, monospace;
  }
  .md pre { background: var(--code); border-radius: 6px; padding: 8px 10px; overflow-x: auto; }
  .md pre code { background: none; padding: 0; white-space: pre; }
  .md blockquote { border-left: 3px solid var(--line); padding-left: 8px; color: var(--muted); }
  .md a { color: var(--accent); }
  .md table { border-collapse: collapse; font-size: 12px; display: block; overflow-x: auto; }
  .md th, .md td { border: 1px solid var(--line); padding: 3px 7px; text-align: left; }
  .md th { background: var(--code); }
  .md hr { border: none; border-top: 1px solid var(--line); }
  .msg.notice { color: var(--muted); font-size: 12px; background: none; padding: 0 4px; }
  .msg.error { color: var(--bad); font-size: 12px; background: none; padding: 0 4px; }
  details.tool { background: var(--tool); border-radius: 8px; padding: 6px 10px; font-size: 12px; }
  details.tool summary { cursor: pointer; }
  details.tool pre {
    white-space: pre-wrap; word-break: break-all; max-height: 260px; overflow: auto;
    background: var(--code); padding: 6px; border-radius: 4px; margin: 6px 0 0;
    font: 11.5px/1.4 ui-monospace, "Cascadia Code", Consolas, monospace;
  }
  details.tool.fail summary { color: var(--bad); }
  #composer { border-top: 1px solid var(--line); padding: 8px; display: flex; flex-direction: column; gap: 6px; }
  #prompt { resize: vertical; min-height: 64px; max-height: 40vh; padding: 8px; }
  #composer .row { display: flex; gap: 6px; align-items: center; }
  #model { flex: 1; min-width: 0; }

  #drawer { position: fixed; top: 50%; right: 0; transform: translateY(-50%); border-radius: 6px 0 0 6px; display: none; }
  #main.dock-left ~ #drawer { right: auto; left: 0; border-radius: 0 6px 6px 0; }
  #main.chat-hidden ~ #drawer { display: block; }

  dialog {
    border: 1px solid var(--line); border-radius: 10px; background: var(--panel); color: var(--ink);
    width: min(520px, 92vw); padding: 18px 20px;
  }
  dialog::backdrop { background: rgba(0,0,0,.35); }
  dialog h2 { margin: 0 0 6px; font-size: 16px; }
  dialog .actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
  dialog textarea { width: 100%; min-height: 90px; padding: 6px; font-family: ui-monospace, Consolas, monospace; font-size: 12px; }
  dialog input[type=text], dialog input[type=password], dialog select { width: 100%; }
  .hint { font-size: 12px; color: var(--muted); }
</style>
</head>
<body>
<div id="top">
  <span class="brand">AI Browser Toolkit</span>
  <div class="group">
    <span class="muted small">Session</span>
    <select id="session" title="Session: a browser profile with its logins, plus its own rules, tabs and chats"></select>
    <button class="icon" id="session-new" title="New session">+</button>
    <button class="icon" id="session-edit" title="Session settings">⚙</button>
    <button class="icon" id="session-del" title="Delete this session">🗑</button>
  </div>
  <span id="status" class="muted"></span>
  <span class="spacer"></span>
  <button class="icon" id="dock" title="Move the chat to the other side">⇆</button>
  <button class="icon" id="toggle-chat" title="Hide or show the chat (Ctrl+B)">☰</button>
  <button id="app-settings" title="Model settings">Models</button>
</div>

<div id="main" class="dock-right">
  <section id="browser">
    <div id="tabs"></div>
    <div id="nav">
      <button class="icon" id="back" title="Back">←</button>
      <button class="icon" id="fwd" title="Forward">→</button>
      <button class="icon" id="reload" title="Reload the page">⟳</button>
      <button class="icon" id="restart" title="Restart this session's browser (it starts and recovers on its own; this is for when a page is wedged)">⏻</button>
      <input id="url" placeholder="Type a URL and press Enter" spellcheck="false">
      <button class="icon" id="newtab" title="New tab">＋ tab</button>
    </div>
    <div id="view">
      <img id="screen" tabindex="0" alt="" draggable="false">
      <div id="viewmsg">Starting the browser…</div>
    </div>
  </section>
  <div id="splitter" title="Drag to resize"></div>
  <aside id="chat">
    <div id="chathead">
      <select id="chatpick" title="Conversations in this session"></select>
      <button class="icon" id="chat-new" title="New chat">+</button>
      <button class="icon" id="chat-del" title="Delete this chat">🗑</button>
    </div>
    <div id="messages"></div>
    <div id="composer">
      <textarea id="prompt" placeholder="Tell the browser what to do. Enter sends, Shift+Enter for a new line."></textarea>
      <div class="row">
        <select id="model" title="Model for this chat"></select>
        <button id="stop" disabled>Stop</button>
        <button id="send" class="primary">Send</button>
      </div>
    </div>
  </aside>
</div>
<button id="drawer" title="Show the chat (Ctrl+B)">💬</button>

<dialog id="dlg-settings">
  <h2>Models</h2>
  <div class="hint">Any OpenAI-compatible endpoint. The key is stored on this machine only, readable by your account.</div>
  <label class="field">Endpoint URL<input type="text" id="set-endpoint" spellcheck="false"></label>
  <label class="field">API key <span class="hint" id="set-keyhint"></span>
    <input type="password" id="set-key" placeholder="leave empty to keep the current key" autocomplete="off"></label>
  <label class="field">Models, one per line, first is the default
    <textarea id="set-models" spellcheck="false"></textarea></label>
  <div class="hint">If a model fails (no tool support, rate limit), the chat moves down the list.</div>
  <div class="actions">
    <button id="set-free">Fetch free OpenRouter models</button>
    <span class="spacer" style="flex:1"></span>
    <button data-close>Cancel</button>
    <button id="set-save" class="primary">Save</button>
  </div>
</dialog>

<dialog id="dlg-session">
  <h2 id="ses-title">Session</h2>
  <label class="field" id="ses-name-row">Name<input type="text" id="ses-name" placeholder="lowercase, e.g. research" spellcheck="false"></label>
  <label class="field">Browser profile <span class="hint">— its logins and cookies</span>
    <span style="display:flex; gap:6px">
      <select id="ses-profile" style="flex:1"></select>
      <button class="icon" id="ses-profile-del" type="button" title="Delete the selected profile (only when no session uses it)">🗑</button>
    </span>
  </label>
  <label class="field" id="ses-newprofile-row" style="display:none">New profile name
    <input type="text" id="ses-newprofile" placeholder="lowercase, e.g. work" spellcheck="false"></label>
  <label class="field">Allowed and blocked URLs, one per line
    <textarea id="ses-rules" spellcheck="false" placeholder="app.example.com/admin&#10;!app.example.com/api"></textarea></label>
  <div class="hint">A line allows a host and path; a line starting with ! blocks it. Any allowed line makes everything else blocked. Empty means no limits.</div>
  <label class="check"><input type="checkbox" id="ses-strict"> Check every request (images, scripts, styles too)</label>
  <label class="check"><input type="checkbox" id="ses-runjs"> Allow run_js (scripts the model writes)</label>
  <label class="check" id="ses-sealed-row"><input type="checkbox" id="ses-sealed" checked> Sealed: only this app can drive it</label>
  <div class="actions">
    <button data-close>Cancel</button>
    <button id="ses-save" class="primary">Save</button>
  </div>
</dialog>

<dialog id="dlg-token">
  <h2>Operator token</h2>
  <div class="hint">Opened outside the desktop app, this page needs the server's operator token once.
    It is in <code id="tok-path">sessions/operator.token</code>, readable only by your account.</div>
  <label class="field">Token<input type="password" id="tok-value" autocomplete="off"></label>
  <div class="actions"><button id="tok-save" class="primary">Continue</button></div>
</dialog>

<script>
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const store = {
  get(k, d) { try { const v = localStorage.getItem("abt." + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem("abt." + k, JSON.stringify(v)); } catch (e) {} },
};

const S = {
  op: null, tokens: {}, sessions: [], profiles: [], session: store.get("session", "default"),
  profile: null, chat: null, chatSock: null, screenSock: null, tab: null, tabs: [],
  meta: null, running: false, busy: false, settings: null, runningChats: new Set(), buffers: {},
  starting: false, lastStart: {},
};

// --- tokens ---------------------------------------------------------------------

function bridge() { return window.pywebview && window.pywebview.api; }

async function waitForBridge() {
  if (bridge()) return true;
  return new Promise(res => {
    let done = false;
    window.addEventListener("pywebviewready", () => { if (!done) { done = true; res(true); } });
    setTimeout(() => { if (!done) { done = true; res(!!bridge()); } }, 1500);
  });
}

async function operatorToken() {
  if (S.op) return S.op;
  if (bridge()) { S.op = await bridge().operator_token(); if (S.op) return S.op; }
  try { S.op = sessionStorage.getItem("abt.op"); } catch (e) {}
  if (S.op) return S.op;
  try { const w = await (await fetch("/app/where")).json(); if (w.ok) $("#tok-path").textContent = w.result.sessions_dir + "/operator.token"; } catch (e) {}
  return new Promise(res => {
    $("#dlg-token").showModal();
    $("#tok-save").onclick = () => {
      S.op = $("#tok-value").value.trim();
      try { sessionStorage.setItem("abt.op", S.op); } catch (e) {}
      $("#dlg-token").close(); res(S.op);
    };
  });
}

async function sessionToken(name) {
  const info = S.sessions.find(s => s.name === name);
  if (!info || !info.sealed) return null;
  if (S.tokens[name]) return S.tokens[name];
  if (bridge()) { const t = await bridge().session_token(name); if (t) S.tokens[name] = t; }
  if (!S.tokens[name]) { try { S.tokens[name] = sessionStorage.getItem("abt.tok." + name); } catch (e) {} }
  return S.tokens[name] || null;
}

// --- server calls ------------------------------------------------------------------

async function api(method, path, body, opts = {}) {
  const headers = { "content-type": "application/json" };
  const session = opts.session === undefined ? S.session : opts.session;
  if (session) headers["X-ABT-Session"] = session;
  const token = opts.operator ? await operatorToken() : (session ? await sessionToken(session) : null);
  if (token) headers["X-ABT-Token"] = token;
  const r = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  let b;
  try { b = await r.json(); } catch (e) { throw new Error(`HTTP ${r.status}`); }
  if (b.ok === false) {
    const err = b.error || {};
    const e = new Error(err.message || "request failed"); e.type = err.type; e.hint = err.hint; throw e;
  }
  return b.result !== undefined ? b.result : b;
}

const run = (cmd) => api("POST", "/command-list", cmd);

function say(text, bad) {
  const el = $("#status"); el.textContent = text || ""; el.style.color = bad ? "var(--bad)" : "";
  if (text && !bad) setTimeout(() => { if (el.textContent === text) el.textContent = ""; }, 4000);
}

function fail(e) { say((e.type ? e.type + ": " : "") + e.message, true); }

// --- profiles and sessions -------------------------------------------------------------

async function loadAll() {
  S.profiles = await api("GET", "/profiles", undefined, { session: null });
  S.sessions = await api("GET", "/sessions", undefined, { session: null });
  if (!S.sessions.find(s => s.name === S.session)) S.session = "default";
  const current = S.sessions.find(s => s.name === S.session);
  S.profile = current ? current.profile : "default";
  drawSessions();
}

function drawSessions() {
  // One list, grouped by the profile each session runs on: the profile is a
  // property of the session, not a second thing to pick.
  const byProfile = {};
  for (const s of S.sessions) (byProfile[s.profile] = byProfile[s.profile] || []).push(s);
  $("#session").innerHTML = Object.keys(byProfile).sort().map(profile =>
    `<optgroup label="profile: ${esc(profile)}">` + byProfile[profile].map(s =>
      `<option value="${esc(s.name)}"${s.name === S.session ? " selected" : ""}>${esc(s.name)}${s.sealed ? " 🔒" : ""}${s.running ? " ●" : ""}</option>`).join("") +
    `</optgroup>`).join("");
}

async function selectSession(name) {
  if (!name) return;
  S.session = name; store.set("session", name);
  const info = S.sessions.find(s => s.name === name);
  S.profile = info ? info.profile : S.profile;
  drawSessions();
  closeScreen();
  // Chats first, then the socket: what it replays lands on the drawn chat.
  await refreshBrowser(); await loadChats(); openChatSocket();
}

$("#session").onchange = (e) => selectSession(e.target.value);

function openSessionDialog(edit) {
  const dlg = $("#dlg-session");
  $("#ses-title").textContent = edit ? `Session: ${S.session}` : "New session";
  $("#ses-name-row").style.display = edit ? "none" : "";
  $("#ses-sealed-row").style.display = edit ? "none" : "";
  const drawProfiles = (pick) => {
    $("#ses-profile").innerHTML = S.profiles.map(p =>
      `<option value="${esc(p.name)}"${p.name === pick ? " selected" : ""}>${esc(p.name)}${p.running ? " ●" : ""}</option>`).join("")
      + `<option value="__new__">+ New profile…</option>`;
    $("#ses-newprofile-row").style.display = "none";
  };
  drawProfiles(S.profile);
  $("#ses-newprofile").value = "";
  $("#ses-profile").onchange = () => {
    const isNew = $("#ses-profile").value === "__new__";
    $("#ses-newprofile-row").style.display = isNew ? "" : "none";
    if (isNew) $("#ses-newprofile").focus();
  };
  $("#ses-profile-del").onclick = async () => {
    const name = $("#ses-profile").value;
    if (name === "__new__") return;
    if (name === "default") return say("The default profile cannot be removed", true);
    if (!confirm(`Delete profile "${name}" and every login in it? This cannot be undone.`)) return;
    try {
      await api("DELETE", "/profiles/" + encodeURIComponent(name), undefined, { session: null });
      S.profiles = await api("GET", "/profiles", undefined, { session: null });
      drawProfiles(S.profile); say("Profile deleted");
    } catch (e) { fail(e); }
  };
  $("#ses-name").value = ""; $("#ses-rules").value = ""; $("#ses-strict").checked = false; $("#ses-runjs").checked = true;
  if (edit) {
    api("GET", "/sessions/" + encodeURIComponent(S.session)).then(info => {
      const st = info.settings || {};
      $("#ses-rules").value = (st.rules || []).join("\n");
      $("#ses-strict").checked = !!st.strict;
      $("#ses-runjs").checked = st.run_js !== false;
    }).catch(fail);
  }
  $("#ses-save").onclick = async () => {
    const settings = {
      rules: $("#ses-rules").value.split("\n").map(s => s.trim()).filter(Boolean),
      strict: $("#ses-strict").checked, run_js: $("#ses-runjs").checked,
    };
    try {
      // A new profile is made first, then the session on it.
      let profile = $("#ses-profile").value;
      if (profile === "__new__") {
        profile = $("#ses-newprofile").value.trim();
        if (!profile) return say("Name the new profile", true);
        await api("POST", "/profiles", { name: profile }, { session: null });
        S.profiles = await api("GET", "/profiles", undefined, { session: null });
      }
      if (edit) {
        const body = { settings };
        if (profile !== S.profile) body.profile = profile;
        const out = await api("PATCH", "/sessions/" + encodeURIComponent(S.session), body);
        if (out.warning) say(out.warning);
        await loadAll(); await selectSession(S.session);
      } else {
        const name = $("#ses-name").value.trim();
        const out = await api("POST", "/sessions", { name, profile, sealed: $("#ses-sealed").checked, settings }, { session: null });
        if (out.token) { S.tokens[name] = out.token; try { sessionStorage.setItem("abt.tok." + name, out.token); } catch (e) {} }
        await loadAll(); await selectSession(name);
      }
      dlg.close(); say("Saved");
    } catch (e) { fail(e); }
  };
  dlg.showModal();
}
$("#session-new").onclick = () => openSessionDialog(false);
$("#session-edit").onclick = () => S.session && openSessionDialog(true);
$("#session-del").onclick = async () => {
  if (!S.session || S.session === "default") return say("The default session cannot be removed", true);
  if (!confirm(`Delete session "${S.session}"? Its tabs close; its logs and chats are kept aside.`)) return;
  try { await api("DELETE", "/sessions/" + encodeURIComponent(S.session)); S.session = "default"; await loadAll(); await selectSession("default"); }
  catch (e) { fail(e); }
};

// --- the browser pane ------------------------------------------------------------------

async function refreshBrowser() {
  if (!S.session) return;
  // /browser answers without touching the browser. /status reads every tab,
  // and doing that under an agent's feet switches tabs mid-command.
  let status;
  try { status = await api("GET", "/browser?session=" + encodeURIComponent(S.session)); }
  catch (e) { fail(e); return; }
  S.running = !!status.running;
  if (!S.running) {
    // Nobody presses start: a session that is shown gets its browser.
    S.tabs = []; drawTabs(); closeScreen();
    return ensureBrowser("browser_start");
  }
  try { S.tabs = await run({ op: "tab_list" }); }
  catch (e) {
    S.tabs = [];
    if (e.type === "browser_dead") return ensureBrowser("browser_restart");
  }
  const own = S.tabs.filter(t => !t.locked && !t.unowned && !t.pending);
  const active = own.find(t => t.active) || own[0];
  if (!S.tab || !S.tabs.find(t => t.tab_id === S.tab)) S.tab = active ? active.tab_id : null;
  const shown = S.tabs.find(t => t.tab_id === S.tab);
  if (shown && document.activeElement !== $("#url")) $("#url").value = shown.url || "";
  drawTabs();
  if (S.tab) openScreen(S.tab);
}

function drawTabs() {
  $("#tabs").innerHTML = S.tabs.map(t => {
    const cls = ["tab", t.tab_id === S.tab ? "on" : "", t.locked ? "locked" : ""].join(" ");
    const label = t.locked ? `🔒 ${t.locked}` : t.pending ? "opening…" : (t.title || t.url || t.tab_id);
    return `<div class="${cls}" data-tab="${esc(t.tab_id)}" title="${esc(t.url || "")}">${esc(label)}</div>`;
  }).join("");
}

$("#tabs").onclick = async (e) => {
  const el = e.target.closest(".tab"); if (!el) return;
  const tab = S.tabs.find(t => t.tab_id === el.dataset.tab); if (!tab) return;
  try {
    if (tab.unowned) await run({ op: "tab_claim", tab_id: tab.tab_id });
    else if (tab.locked) return say(`That tab belongs to session ${tab.locked}`, true);
    else await run({ op: "tab_switch", tab_id: tab.tab_id });
    S.tab = tab.tab_id; await refreshBrowser();
  } catch (err) { fail(err); }
};

// Start or restart this session's browser, once at a time and not in a loop:
// a browser that will not come up says why instead of retrying forever.
async function ensureBrowser(op) {
  const session = S.session;
  if (!session || S.starting) return;
  const last = S.lastStart[session] || 0;
  if (Date.now() - last < 15000) {
    $("#viewmsg").style.display = ""; $("#viewmsg").textContent = "The browser did not come up. ⏻ tries again.";
    return;
  }
  S.starting = true; S.lastStart[session] = Date.now();
  $("#viewmsg").style.display = "";
  $("#viewmsg").textContent = op === "browser_restart" ? "Restarting the browser…" : "Starting the browser…";
  try { await run({ op }); }
  catch (e) {
    // A browser already up (another page started it) is what we wanted.
    if (!/already running/.test(e.message || "")) { fail(e); $("#viewmsg").textContent = e.message; }
  }
  S.starting = false;
  if (S.session === session) { await loadAll(); await refreshBrowser(); }
}
$("#restart").onclick = () => { S.lastStart[S.session] = 0; ensureBrowser("browser_restart"); };

async function nav(cmd) { try { await run(cmd); await refreshBrowser(); } catch (e) { fail(e); } }
$("#back").onclick = () => nav({ op: "back", diff: false });
$("#fwd").onclick = () => nav({ op: "forward", diff: false });
$("#reload").onclick = () => nav({ op: "reload", diff: false });
$("#newtab").onclick = async () => {
  try { const out = await run({ op: "tab_new" }); S.tab = out.tab_id; await refreshBrowser(); } catch (e) { fail(e); }
};
$("#url").onkeydown = (e) => {
  if (e.key !== "Enter") return;
  let url = $("#url").value.trim(); if (!url) return;
  if (!/^[a-z]+:/i.test(url)) url = "https://" + url;
  nav({ op: "goto", url, diff: false });
};

// --- the live view ------------------------------------------------------------------------

function closeScreen() {
  if (S.screenSock) { try { S.screenSock.close(); } catch (e) {} }
  S.screenSock = null; S.meta = null; $("#screen").removeAttribute("src");
}

async function openScreen(tab) {
  if (S.screenSock && S.screenSock._tab === tab && S.screenSock.readyState <= 1) return;
  closeScreen();
  const op = await operatorToken();
  const q = new URLSearchParams({ tab, session: S.session, token: op });
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/screencast?${q}`);
  ws._tab = tab; S.screenSock = ws;
  $("#viewmsg").style.display = ""; $("#viewmsg").textContent = "Connecting…";
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.type === "frame") {
      $("#screen").src = "data:image/jpeg;base64," + m.data; S.meta = m.metadata;
      $("#viewmsg").style.display = "none";
    } else if (m.ok === false) {
      const err = m.error || {};
      $("#viewmsg").style.display = ""; $("#viewmsg").textContent = err.message || "Cannot show this tab";
      // The page's browser went away: bring it back rather than show a corpse.
      if (err.type === "browser_dead") ensureBrowser("browser_restart");
    }
  };
  ws.onclose = () => { if (S.screenSock === ws) { S.screenSock = null; setTimeout(() => S.running && refreshBrowser(), 1500); } };
}

function sendInput(event) { if (S.screenSock && S.screenSock.readyState === 1) S.screenSock.send(JSON.stringify(event)); }

function pagePoint(e) {
  const img = $("#screen"); const m = S.meta; if (!m) return null;
  const width = m.deviceWidth || img.naturalWidth, height = m.deviceHeight || img.naturalHeight;
  return { x: e.offsetX / img.clientWidth * width, y: e.offsetY / img.clientHeight * height };
}
function mods(e) { return (e.altKey ? 1 : 0) | (e.ctrlKey ? 2 : 0) | (e.metaKey ? 4 : 0) | (e.shiftKey ? 8 : 0); }
const BUTTONS = ["left", "middle", "right"];

$("#screen").addEventListener("mousedown", (e) => {
  e.preventDefault(); $("#screen").focus(); const p = pagePoint(e); if (!p) return;
  sendInput({ type: "mouse", event: "mousePressed", ...p, button: BUTTONS[e.button] || "left", clickCount: e.detail || 1, modifiers: mods(e) });
});
$("#screen").addEventListener("mouseup", (e) => {
  const p = pagePoint(e); if (!p) return;
  sendInput({ type: "mouse", event: "mouseReleased", ...p, button: BUTTONS[e.button] || "left", clickCount: e.detail || 1, modifiers: mods(e) });
  if (!S.runningChats.size) setTimeout(refreshBrowser, 800);
});
let lastMove = 0;
$("#screen").addEventListener("mousemove", (e) => {
  const now = Date.now(); if (now - lastMove < 60) return; lastMove = now;
  const p = pagePoint(e); if (p) sendInput({ type: "mouse", event: "mouseMoved", ...p, modifiers: mods(e) });
});
$("#screen").addEventListener("wheel", (e) => {
  e.preventDefault(); const p = pagePoint(e); if (!p) return;
  sendInput({ type: "mouse", event: "mouseWheel", ...p, deltaX: e.deltaX, deltaY: e.deltaY, modifiers: mods(e) });
}, { passive: false });
$("#screen").addEventListener("contextmenu", (e) => e.preventDefault());
$("#screen").addEventListener("keydown", (e) => {
  if (e.ctrlKey && e.key.toLowerCase() === "b") return;
  e.preventDefault();
  if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) { sendInput({ type: "text", text: e.key }); return; }
  sendInput({ type: "key", event: "rawKeyDown", key: e.key, code: e.code, windowsVirtualKeyCode: e.keyCode, modifiers: mods(e) });
  if (e.key === "Enter") sendInput({ type: "key", event: "char", text: "\r", key: "Enter", modifiers: mods(e) });
});
$("#screen").addEventListener("keyup", (e) => {
  if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) return;
  e.preventDefault();
  sendInput({ type: "key", event: "keyUp", key: e.key, code: e.code, windowsVirtualKeyCode: e.keyCode, modifiers: mods(e) });
});

// --- layout: dock, drawer, width -------------------------------------------------------

function applyLayout() {
  const main = $("#main");
  main.classList.toggle("dock-left", store.get("dock", "right") === "left");
  main.classList.toggle("dock-right", store.get("dock", "right") !== "left");
  main.classList.toggle("chat-hidden", !!store.get("hidden", false));
  $("#chat").style.width = store.get("width", 420) + "px";
}
$("#dock").onclick = () => { store.set("dock", store.get("dock", "right") === "left" ? "right" : "left"); applyLayout(); };
const toggleChat = () => { store.set("hidden", !store.get("hidden", false)); applyLayout(); };
$("#toggle-chat").onclick = toggleChat;
$("#drawer").onclick = toggleChat;
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "b") { e.preventDefault(); toggleChat(); }
}, true);
$("#splitter").addEventListener("mousedown", (e) => {
  e.preventDefault();
  const left = store.get("dock", "right") === "left";
  const move = (ev) => {
    const width = left ? ev.clientX : window.innerWidth - ev.clientX;
    const clamped = Math.max(280, Math.min(window.innerWidth * 0.7, width));
    $("#chat").style.width = clamped + "px"; store.set("width", Math.round(clamped));
  };
  const up = () => { document.removeEventListener("mousemove", move); document.removeEventListener("mouseup", up); };
  document.addEventListener("mousemove", move); document.addEventListener("mouseup", up);
});

// --- models -----------------------------------------------------------------------------

async function loadModels() {
  try { S.settings = await api("GET", "/app/settings", undefined, { operator: true, session: null }); }
  catch (e) { S.settings = { models: [] }; }
  drawModels();
}
function drawModels(chosen) {
  const models = S.settings.models || [];
  const pick = chosen || (S.chat && S.chat.model) || models[0];
  $("#model").innerHTML = models.length
    ? models.map(m => `<option${m === pick ? " selected" : ""}>${esc(m)}</option>`).join("")
    : `<option value="">add a model in Models</option>`;
}
$("#app-settings").onclick = async () => {
  await loadModels();
  $("#set-endpoint").value = S.settings.endpoint || "https://openrouter.ai/api/v1";
  $("#set-key").value = "";
  $("#set-keyhint").textContent = S.settings.has_key ? `(saved: ${S.settings.key_hint})` : "(none saved)";
  $("#set-models").value = (S.settings.models || []).join("\n");
  $("#dlg-settings").showModal();
};
$("#set-free").onclick = async () => {
  $("#set-free").disabled = true; $("#set-free").textContent = "Fetching…";
  try {
    await api("PUT", "/app/settings", { endpoint: $("#set-endpoint").value.trim() }, { operator: true, session: null });
    const found = await api("GET", "/app/models/free", undefined, { operator: true, session: null });
    const have = new Set($("#set-models").value.split("\n").map(s => s.trim()).filter(Boolean));
    const add = found.map(m => m.id).filter(id => !have.has(id));
    $("#set-models").value = [...have, ...add].join("\n");
    say(`${found.length} free models with tool support; ${add.length} added`);
  } catch (e) { fail(e); }
  $("#set-free").disabled = false; $("#set-free").textContent = "Fetch free OpenRouter models";
};
$("#set-save").onclick = async () => {
  const body = {
    endpoint: $("#set-endpoint").value.trim(),
    models: $("#set-models").value.split("\n").map(s => s.trim()).filter(Boolean),
  };
  if ($("#set-key").value.trim()) body.api_key = $("#set-key").value.trim();
  try { S.settings = await api("PUT", "/app/settings", body, { operator: true, session: null }); drawModels(); $("#dlg-settings").close(); say("Saved"); }
  catch (e) { fail(e); }
};
document.querySelectorAll("[data-close]").forEach(b => b.onclick = () => b.closest("dialog").close());

// --- chats ------------------------------------------------------------------------------

async function loadChats(pick) {
  if (!S.session) return;
  let list = [];
  try { list = await api("GET", "/app/chats"); } catch (e) { fail(e); }
  if (!list.length) { const c = await api("POST", "/app/chats", { model: $("#model").value || null }); list = [c]; }
  const id = pick || (list.find(c => c.id === store.get("chat." + S.session)) || list[0]).id;
  $("#chatpick").innerHTML = list.map(c => `<option value="${esc(c.id)}"${c.id === id ? " selected" : ""}>${esc(c.title || "New chat")}</option>`).join("");
  await openChat(id);
}
async function openChat(id) {
  try { S.chat = await api("GET", "/app/chats/" + encodeURIComponent(id)); } catch (e) { return fail(e); }
  store.set("chat." + S.session, id);
  drawModels(); drawHistory();
  // A reply still running: its saved history lags, so show what it has done.
  for (const e of S.buffers[id] || []) renderEvent(e);
  setBusy(S.runningChats.has(id));
}
$("#chatpick").onchange = (e) => openChat(e.target.value);
$("#chat-new").onclick = async () => { try { const c = await api("POST", "/app/chats", { model: $("#model").value || null }); await loadChats(c.id); } catch (e) { fail(e); } };
$("#chat-del").onclick = async () => {
  if (!S.chat || !confirm("Delete this chat?")) return;
  try { await api("DELETE", "/app/chats/" + encodeURIComponent(S.chat.id)); store.set("chat." + S.session, null); await loadChats(); } catch (e) { fail(e); }
};

function add(html) { const m = $("#messages"); m.insertAdjacentHTML("beforeend", html); m.scrollTop = m.scrollHeight; }
function bubble(role, text) {
  if (role === "assistant") return add(`<div class="msg assistant md">${markdown(text)}</div>`);
  add(`<div class="msg ${role}">${esc(text)}</div>`);
}

// Markdown for the model's replies. Small and self-contained -- the page
// loads nothing from the network -- and safe by construction: every piece of
// text is escaped before any markup is added, and links must be http(s).
function markdown(src) {
  const inline = (text) => {
    const codes = [];
    let t = esc(text).replace(/`([^`]+)`/g, (_, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
    t = t.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
         .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
         .replace(/__([^_]+)__/g, "<strong>$1</strong>")
         .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>")
         .replace(/(^|[\s(])_([^_\s][^_]*)_(?=[\s).,!?:;]|$)/g, "$1<em>$2</em>")
         .replace(/~~([^~]+)~~/g, "<del>$1</del>");
    return t.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[+i]}</code>`);
  };
  const lines = String(src ?? "").replace(/\r\n?/g, "\n").split("\n");
  const out = [];
  let i = 0;
  const isTableRow = (l) => /^\s*\|.*\|\s*$/.test(l);
  const cells = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim());
  const bullet = /^\s*[-*+]\s+/, number = /^\s*\d+[.)]\s+/;
  while (i < lines.length) {
    const line = lines[i];
    if (/^\s*```/.test(line)) {
      const body = [];
      i++;
      while (i < lines.length && !/^\s*```/.test(lines[i])) body.push(lines[i++]);
      i++;
      out.push(`<pre><code>${esc(body.join("\n"))}</code></pre>`);
      continue;
    }
    if (!line.trim()) { i++; continue; }
    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) { const n = heading[1].length; out.push(`<h${n}>${inline(heading[2])}</h${n}>`); i++; continue; }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { out.push("<hr>"); i++; continue; }
    if (isTableRow(line) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
      const head = cells(line);
      i += 2;
      const rows = [];
      while (i < lines.length && isTableRow(lines[i])) rows.push(cells(lines[i++]));
      out.push("<table><thead><tr>" + head.map(c => `<th>${inline(c)}</th>`).join("") + "</tr></thead><tbody>" +
        rows.map(r => "<tr>" + r.map(c => `<td>${inline(c)}</td>`).join("") + "</tr>").join("") + "</tbody></table>");
      continue;
    }
    if (/^\s*>/.test(line)) {
      const quote = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) quote.push(lines[i++].replace(/^\s*>\s?/, ""));
      out.push(`<blockquote>${markdown(quote.join("\n"))}</blockquote>`);
      continue;
    }
    if (bullet.test(line) || number.test(line)) {
      const ordered = number.test(line), marker = ordered ? number : bullet;
      const items = [];
      while (i < lines.length && marker.test(lines[i])) {
        let item = lines[i++].replace(marker, "");
        // A wrapped continuation line belongs to the item above it.
        while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !bullet.test(lines[i]) && !number.test(lines[i])) item += " " + lines[i++].trim();
        items.push(`<li>${inline(item)}</li>`);
      }
      out.push(ordered ? `<ol>${items.join("")}</ol>` : `<ul>${items.join("")}</ul>`);
      continue;
    }
    const para = [];
    while (i < lines.length && lines[i].trim() && !/^\s*(```|#{1,4}\s|>|[-*+]\s|\d+[.)]\s)/.test(lines[i]) && !isTableRow(lines[i])) para.push(lines[i++]);
    if (!para.length) para.push(lines[i++]);
    out.push(`<p>${para.map(inline).join("<br>")}</p>`);
  }
  return out.join("");
}
function toolBlock(name, args, result, bad) {
  const shown = result === undefined ? "…running" : String(result).slice(0, 4000);
  add(`<details class="tool${bad ? " fail" : ""}"><summary>${bad ? "✗" : "▸"} ${esc(name)}</summary><pre>${esc(JSON.stringify(args, null, 1))}</pre><pre>${esc(shown)}</pre></details>`);
}
function drawHistory() {
  $("#messages").innerHTML = "";
  const msgs = (S.chat && S.chat.messages) || [];
  const results = {};
  msgs.filter(m => m.role === "tool").forEach(m => results[m.tool_call_id] = m.content);
  for (const m of msgs) {
    if (m.role === "user") bubble("user", m.content);
    else if (m.role === "assistant") {
      if (m.content) bubble("assistant", m.content);
      for (const call of m.tool_calls || []) {
        let args = {}; try { args = JSON.parse(call.function.arguments || "{}"); } catch (e) {}
        const r = results[call.id]; toolBlock(call.function.name, args, r, r && r.includes('"ok":false'));
      }
    }
  }
  if (!msgs.length) add(`<div class="msg notice">Ask for something in the browser — for example “open example.com and read me the heading”. Pick a model in Models first.</div>`);
}

function openChatSocket() {
  // Leaving a session no longer stops its replies: they run on the server,
  // and this socket only watches. Coming back replays what was missed.
  if (S.chatSock) { try { S.chatSock.close(); } catch (e) {} }
  S.chatSock = null; S.runningChats = new Set(); S.buffers = {};
  setBusy(false);
  if (!S.session) return;
  sessionToken(S.session).then(token => {
    const q = new URLSearchParams({ session: S.session }); if (token) q.set("token", token);
    const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/app/chat?${q}`);
    S.chatSock = ws;
    ws.onmessage = (ev) => onChatEvent(JSON.parse(ev.data));
    ws.onclose = () => { if (S.chatSock === ws) S.chatSock = null; };
  });
}

let pendingTool = null;
function renderEvent(e) {
  if (e.type === "user") bubble("user", e.text);
  else if (e.type === "assistant") bubble("assistant", e.text);
  else if (e.type === "tool_call") { pendingTool = e; }
  else if (e.type === "tool_result") {
    // No refresh here: the live view already shows the page, and a tab_list
    // between the agent's steps holds its session's lock for nothing.
    toolBlock(e.name, pendingTool ? pendingTool.args : {}, e.text, e.error); pendingTool = null;
  }
  else if (e.type === "notice") bubble("notice", e.text);
  else if (e.type === "error") bubble("error", e.text);
}

async function onChatEvent(e) {
  if (e.ok === false) { bubble("error", (e.error && e.error.message) || "chat unavailable"); return; }
  const id = e.chat_id;
  const here = S.chat && S.chat.id === id;
  if (e.type === "resume") {
    // A reply that was already running when this page connected.
    S.runningChats.add(id); S.buffers[id] = [];
    if (here) { drawHistory(); setBusy(true); }
    return;
  }
  if (e.type === "done") {
    S.runningChats.delete(id); delete S.buffers[id];
    const opt = [...$("#chatpick").options].find(o => o.value === id); if (opt) opt.textContent = e.title;
    if (here) { await openChat(id); refreshBrowser(); }
    return;
  }
  if (e.type === "user") { S.runningChats.add(id); S.buffers[id] = []; if (here) setBusy(true); }
  // Refused before it started (say, that chat was already replying): nothing
  // else will clear "Working…", so this does.
  if (e.type === "error" && !S.runningChats.has(id)) { if (here) { bubble("error", e.text); setBusy(false); } return; }
  if (!S.buffers[id]) S.buffers[id] = [];
  S.buffers[id].push(e);
  if (here) renderEvent(e);
}

function setBusy(busy) {
  S.busy = busy; $("#send").disabled = busy; $("#stop").disabled = !busy;
  $("#send").textContent = busy ? "Working…" : "Send";
}

async function send() {
  const text = $("#prompt").value.trim();
  if (!text || S.busy || !S.chat) return;
  if (!S.chatSock || S.chatSock.readyState !== 1) { openChatSocket(); return say("Reconnecting the chat — send again in a moment", true); }
  $("#prompt").value = ""; setBusy(true);
  S.chatSock.send(JSON.stringify({ type: "send", chat_id: S.chat.id, text, model: $("#model").value || null }));
}
$("#send").onclick = send;
$("#stop").onclick = () => S.chatSock && S.chat && S.chatSock.send(JSON.stringify({ type: "stop", chat_id: S.chat.id }));
$("#prompt").onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } };

// --- start -------------------------------------------------------------------------------

(async function boot() {
  applyLayout();
  await waitForBridge();
  try {
    await operatorToken();
    await loadAll();
    await loadModels();
    await selectSession(S.session);
  } catch (e) { fail(e); }
  setInterval(() => { if (!document.hidden && !S.runningChats.size) refreshBrowser(); }, 5000);
})();
</script>
</body>
</html>
"""
