"""The /app page: the desktop app's whole interface.

One window: the session's browser tab, live, on one side, and a chat with a
model of the person's choosing on the other. Kept as one string with no
external assets, like the log viewer, so it needs no build step and works
offline.

Tokens never travel in this page's source. Inside the desktop shell they come
from pywebview's bridge (`window.pywebview.api`), which reads the owner-only
token files; opened in an ordinary browser, the page asks for the operator
token once and keeps it for the tab's life.

The design is neutral graphite in both themes, with one colour: green, and it
only ever means "live" -- a browser running, an agent working. What the agent
is doing is said in plain words, on the page it is doing it to.
"""

APP_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Browser Toolkit</title>
<style>
  :root {
    --bg: #FAFAF9; --panel: #FFFFFF; --raised: #F3F3F1; --ink: #1C1C1C; --muted: #6F6F6F;
    --line: #E4E4E2; --live: #16A34A; --live-soft: rgba(22,163,74,.12); --bad: #C2410C;
    --bad-soft: rgba(194,65,12,.10); --btn: #1C1C1C; --btn-ink: #FFFFFF; --code: #F3F3F1;
    --user: #1C1C1C; --user-ink: #FFFFFF; --shadow: 0 8px 28px rgba(0,0,0,.14);
  }
  :root[data-theme="dark"] {
    --bg: #161616; --panel: #1E1E1E; --raised: #262626; --ink: #EDEDED; --muted: #9A9A9A;
    --line: #333333; --live: #22C55E; --live-soft: rgba(34,197,94,.14); --bad: #F97316;
    --bad-soft: rgba(249,115,22,.12); --btn: #EDEDED; --btn-ink: #161616; --code: #262626;
    --user: #EDEDED; --user-ink: #161616; --shadow: 0 8px 28px rgba(0,0,0,.5);
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #161616; --panel: #1E1E1E; --raised: #262626; --ink: #EDEDED; --muted: #9A9A9A;
      --line: #333333; --live: #22C55E; --live-soft: rgba(34,197,94,.14); --bad: #F97316;
      --bad-soft: rgba(249,115,22,.12); --btn: #EDEDED; --btn-ink: #161616; --code: #262626;
      --user: #EDEDED; --user-ink: #161616; --shadow: 0 8px 28px rgba(0,0,0,.5);
    }
  }
  * { box-sizing: border-box; }
  [hidden] { display: none !important; }
  html, body { height: 100%; margin: 0; }
  body {
    background: var(--bg); color: var(--ink); display: flex; flex-direction: column;
    font: 13.5px/1.5 "Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  button, select, input, textarea { font: inherit; color: inherit; }
  button {
    background: var(--panel); border: 1px solid var(--line); border-radius: 7px;
    padding: 5px 11px; cursor: pointer; white-space: nowrap; line-height: 1.35;
  }
  button:hover { background: var(--raised); }
  button:disabled { opacity: .45; cursor: default; }
  button.primary { background: var(--btn); color: var(--btn-ink); border-color: var(--btn); font-weight: 600; }
  button.primary:hover { opacity: .88; background: var(--btn); }
  button.ghost { border-color: transparent; background: transparent; }
  button.ghost:hover { background: var(--raised); }
  button.icon { padding: 5px 8px; min-width: 32px; }
  select, input, textarea {
    background: var(--panel); border: 1px solid var(--line); border-radius: 7px; padding: 5px 8px;
  }
  :focus-visible { outline: 2px solid var(--ink); outline-offset: 1px; }
  .muted { color: var(--muted); }
  .spacer { flex: 1; }
  @media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; } }

  /* --- top bar --- */
  #top {
    display: flex; align-items: center; gap: 8px; padding: 8px 12px;
    background: var(--panel); border-bottom: 1px solid var(--line); position: relative;
  }
  #session-btn { display: flex; align-items: center; gap: 8px; padding: 5px 10px 5px 9px; max-width: 360px; }
  #session-btn .name { font-weight: 600; overflow: hidden; text-overflow: ellipsis; }
  #session-btn .sub { color: var(--muted); font-size: 12px; overflow: hidden; text-overflow: ellipsis; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--line); flex: none; }
  .dot.on { background: var(--live); }
  .dot.busy { background: var(--live); animation: pulse 1.2s ease-in-out infinite; }
  @keyframes pulse { 50% { opacity: .35; } }
  .pill {
    font-size: 12px; padding: 2px 9px; border-radius: 999px; border: 1px solid var(--line);
    color: var(--muted); cursor: pointer; background: transparent;
  }
  #model-btn .label { color: var(--muted); }
  #model-btn .value { font-weight: 600; max-width: 220px; overflow: hidden; text-overflow: ellipsis; display: inline-block; vertical-align: bottom; }

  .menu {
    position: absolute; top: calc(100% + 4px); left: 12px; z-index: 20; width: 330px; max-height: 70vh;
    overflow: auto; background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
    box-shadow: var(--shadow); padding: 6px;
  }
  .menu h4 { margin: 8px 8px 4px; font-size: 12px; font-weight: 600; color: var(--muted); }
  .menu .row {
    display: flex; align-items: center; gap: 8px; width: 100%; text-align: left; border: none;
    background: transparent; padding: 7px 8px; border-radius: 7px;
  }
  .menu .row:hover, .menu .row.on { background: var(--raised); }
  .menu .row .grow { flex: 1; overflow: hidden; text-overflow: ellipsis; }
  .menu .row .meta { color: var(--muted); font-size: 12px; }
  .menu hr { border: none; border-top: 1px solid var(--line); margin: 6px 2px; }

  /* --- panes --- */
  #main { flex: 1; display: flex; min-height: 0; }
  #main.dock-left { flex-direction: row-reverse; }
  #browser { flex: 1; display: flex; flex-direction: column; min-width: 0; }
  #tabs { display: flex; gap: 4px; padding: 7px 10px 0; overflow-x: auto; background: var(--bg); }
  .tab {
    padding: 6px 12px; border: 1px solid var(--line); border-bottom: none; border-radius: 8px 8px 0 0;
    background: var(--bg); max-width: 220px; overflow: hidden; text-overflow: ellipsis;
    white-space: nowrap; cursor: pointer; font-size: 12.5px; color: var(--muted);
  }
  .tab.on { background: var(--panel); color: var(--ink); font-weight: 600; }
  .tab.locked { opacity: .55; cursor: not-allowed; }
  #nav { display: flex; gap: 4px; padding: 7px 10px; background: var(--panel); border-bottom: 1px solid var(--line); }
  #url {
    flex: 1; min-width: 0; font: 12.5px ui-monospace, "Cascadia Mono", Consolas, monospace;
    background: var(--raised); border-color: transparent;
  }
  #url:focus { background: var(--panel); border-color: var(--line); }
  #view { flex: 1; overflow: auto; background: var(--raised); position: relative; }
  #view.working { box-shadow: inset 0 0 0 2px var(--live); }
  #screen { width: 100%; display: block; outline: none; cursor: default; }
  #viewmsg {
    position: absolute; inset: 0; display: flex; flex-direction: column; gap: 10px; align-items: center;
    justify-content: center; text-align: center; padding: 24px; color: var(--muted);
  }
  #activity {
    position: sticky; bottom: 12px; margin: -44px auto 12px; width: fit-content; max-width: 90%;
    display: flex; align-items: center; gap: 8px; padding: 7px 14px; border-radius: 999px;
    background: var(--panel); border: 1px solid var(--line); box-shadow: var(--shadow); font-size: 12.5px;
  }
  #activity .text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  #splitter { width: 5px; cursor: col-resize; background: var(--line); flex: none; }
  #splitter:hover { background: var(--muted); }
  #chat { width: 420px; min-width: 300px; max-width: 70vw; display: flex; flex-direction: column; background: var(--panel); }
  #main.chat-hidden #chat, #main.chat-hidden #splitter { display: none; }
  #chathead { display: flex; gap: 6px; padding: 8px 10px; border-bottom: 1px solid var(--line); align-items: center; }
  #chatpick { flex: 1; min-width: 0; border-color: transparent; font-weight: 600; background: transparent; }
  #chatpick:hover { border-color: var(--line); }

  #messages { flex: 1; overflow-y: auto; padding: 14px 14px 6px; display: flex; flex-direction: column; gap: 10px; }
  .msg { padding: 8px 12px; border-radius: 12px; white-space: pre-wrap; word-wrap: break-word; max-width: 92%; }
  .msg.user { background: var(--user); color: var(--user-ink); align-self: flex-end; border-bottom-right-radius: 4px; }
  .msg.assistant { background: var(--raised); border-bottom-left-radius: 4px; }
  .msg.notice { color: var(--muted); font-size: 12px; background: none; padding: 0 2px; }
  .msg.error { color: var(--bad); background: var(--bad-soft); font-size: 12.5px; }
  .step { font-size: 12.5px; color: var(--muted); max-width: 100%; }
  .step summary { cursor: pointer; list-style: none; display: flex; gap: 7px; align-items: baseline; padding: 1px 2px; }
  .step summary::-webkit-details-marker { display: none; }
  .step summary:hover { color: var(--ink); }
  .step .mark { width: 14px; flex: none; text-align: center; }
  .step.ok .mark { color: var(--live); }
  .step.fail .mark, .step.fail summary { color: var(--bad); }
  .step pre {
    white-space: pre-wrap; word-break: break-all; max-height: 240px; overflow: auto; background: var(--code);
    padding: 7px 9px; border-radius: 7px; margin: 5px 0 2px 21px;
    font: 11.5px/1.45 ui-monospace, "Cascadia Mono", Consolas, monospace; color: var(--ink);
  }

  .empty { margin: auto 0; padding: 8px 2px; }
  .empty h3 { margin: 0 0 4px; font-size: 15px; }
  .empty p { margin: 0 0 12px; color: var(--muted); }
  .suggestions { display: flex; flex-direction: column; gap: 6px; }
  .suggestions button { text-align: left; white-space: normal; padding: 8px 11px; border-radius: 9px; }

  .setup { padding: 4px 2px; }
  .setup h3 { margin: 0 0 4px; font-size: 15px; }
  .setup ol { padding-left: 18px; margin: 12px 0 0; display: flex; flex-direction: column; gap: 14px; }
  .setup label { display: block; font-weight: 600; margin-bottom: 5px; }
  .setup input { width: 100%; }
  .setup .hint { color: var(--muted); font-size: 12px; margin-top: 4px; }
  .setup .models { display: flex; flex-direction: column; gap: 2px; max-height: 190px; overflow: auto; margin-top: 6px; }
  .setup .models label { font-weight: 400; display: flex; gap: 8px; align-items: center; margin: 0; padding: 4px 6px; border-radius: 6px; cursor: pointer; }
  .setup .models label:hover { background: var(--raised); }

  #composer { border-top: 1px solid var(--line); padding: 10px; display: flex; flex-direction: column; gap: 7px; }
  #prompt { resize: none; min-height: 44px; max-height: 40vh; padding: 9px 11px; border-radius: 10px; line-height: 1.45; }
  #composer .row { display: flex; gap: 6px; align-items: center; }
  #model { min-width: 0; flex: 1; font-size: 12px; color: var(--muted); border-color: transparent; background: transparent; }
  #model:hover { border-color: var(--line); }

  #drawer {
    position: fixed; top: 50%; right: 0; transform: translateY(-50%); border-radius: 8px 0 0 8px;
    display: none; writing-mode: vertical-rl; padding: 12px 6px; box-shadow: var(--shadow);
  }
  #main.dock-left ~ #drawer { right: auto; left: 0; border-radius: 0 8px 8px 0; }
  #main.chat-hidden ~ #drawer { display: block; }

  #toasts { position: fixed; bottom: 16px; left: 50%; transform: translateX(-50%); display: flex; flex-direction: column; gap: 6px; z-index: 50; align-items: center; }
  .toast {
    background: var(--btn); color: var(--btn-ink); padding: 8px 14px; border-radius: 9px; box-shadow: var(--shadow);
    font-size: 12.5px; max-width: 520px; animation: rise .18s ease-out;
  }
  .toast.bad { background: var(--bad); color: #fff; }
  @keyframes rise { from { transform: translateY(6px); opacity: 0; } }

  dialog {
    border: 1px solid var(--line); border-radius: 12px; background: var(--panel); color: var(--ink);
    width: min(520px, 92vw); padding: 20px 22px; box-shadow: var(--shadow);
  }
  dialog::backdrop { background: rgba(0,0,0,.4); }
  dialog h2 { margin: 0 0 4px; font-size: 16px; }
  dialog .lead { margin: 0 0 12px; color: var(--muted); }
  dialog .actions { display: flex; gap: 8px; margin-top: 18px; align-items: center; }
  dialog textarea { width: 100%; min-height: 84px; font: 12px ui-monospace, "Cascadia Mono", Consolas, monospace; }
  dialog input[type=text], dialog input[type=password], dialog select { width: 100%; }
  .field { display: block; margin: 12px 0; }
  .field > span { display: block; font-weight: 600; margin-bottom: 5px; }
  .field .hint { font-weight: 400; color: var(--muted); font-size: 12px; margin-top: 4px; display: block; }
  .check { display: flex; gap: 9px; align-items: flex-start; margin: 9px 0; }
  .check small { display: block; color: var(--muted); }
  details.more > summary { cursor: pointer; color: var(--muted); margin: 10px 0 4px; }

  /* markdown in replies */
  .msg.md { white-space: normal; }
  .md > :first-child { margin-top: 0; } .md > :last-child { margin-bottom: 0; }
  .md p, .md ul, .md ol, .md pre, .md blockquote, .md table { margin: 6px 0; }
  .md h1, .md h2, .md h3, .md h4 { margin: 10px 0 4px; line-height: 1.3; }
  .md h1 { font-size: 16px; } .md h2 { font-size: 15px; } .md h3, .md h4 { font-size: 13.5px; }
  .md ul, .md ol { padding-left: 20px; }
  .md li { margin: 2px 0; }
  .md code { background: var(--panel); border-radius: 4px; padding: 1px 4px; font: 12px ui-monospace, "Cascadia Mono", Consolas, monospace; }
  .md pre { background: var(--panel); border-radius: 7px; padding: 8px 10px; overflow-x: auto; }
  .md pre code { background: none; padding: 0; white-space: pre; }
  .md blockquote { border-left: 3px solid var(--line); padding-left: 8px; color: var(--muted); }
  .md a { color: inherit; text-decoration: underline; text-underline-offset: 2px; }
  .md table { border-collapse: collapse; font-size: 12px; display: block; overflow-x: auto; }
  .md th, .md td { border: 1px solid var(--line); padding: 3px 7px; text-align: left; }
  .md th { background: var(--panel); }
  .md hr { border: none; border-top: 1px solid var(--line); }
</style>
</head>
<body>
<header id="top">
  <button id="session-btn" aria-haspopup="true" aria-expanded="false" title="Switch session. Each session is a browser with its own logins, rules and chats.">
    <span class="dot" id="session-dot"></span>
    <span class="name" id="session-name">default</span>
    <span class="sub" id="session-sub"></span>
    <span class="muted">▾</span>
  </button>
  <div class="menu" id="session-menu" hidden></div>
  <button class="pill" id="rules-pill" hidden title="This session can only reach some sites. Click to change."></button>
  <span class="spacer"></span>
  <button class="ghost" id="model-btn" title="Choose the AI model and where it runs"><span class="label">Model</span> <span class="value" id="model-name">not set</span></button>
  <button class="icon ghost" id="theme" title="Theme: follows your system. Click to switch."></button>
  <button class="icon ghost" id="dock" title="Move the chat to the other side">⇆</button>
  <button class="icon ghost" id="toggle-chat" title="Hide the chat (Ctrl+B)">⇥</button>
</header>

<div id="main" class="dock-right">
  <section id="browser" aria-label="Browser">
    <div id="tabs"></div>
    <div id="nav">
      <button class="icon ghost" id="back" title="Back">←</button>
      <button class="icon ghost" id="fwd" title="Forward">→</button>
      <button class="icon ghost" id="reload" title="Reload">⟳</button>
      <input id="url" placeholder="Type an address and press Enter (Ctrl+L)" spellcheck="false" aria-label="Address">
      <button class="icon ghost" id="newtab" title="New tab">＋</button>
      <button class="icon ghost" id="restart" title="Restart this browser. It starts and recovers on its own; use this if a page is stuck.">⏻</button>
    </div>
    <div id="view">
      <img id="screen" tabindex="0" alt="The live browser page. Click and type here to use it yourself." draggable="false">
      <div id="viewmsg">Starting the browser…</div>
      <div id="activity" hidden><span class="dot busy"></span><span class="text" id="activity-text"></span></div>
    </div>
  </section>
  <div id="splitter" title="Drag to resize"></div>
  <aside id="chat" aria-label="Chat">
    <div id="chathead">
      <select id="chatpick" title="Conversations in this session"></select>
      <button id="chat-new" title="Start a new conversation">＋ New</button>
      <button class="icon ghost" id="chat-del" title="Delete this conversation">🗑</button>
    </div>
    <div id="messages"></div>
    <div id="composer">
      <textarea id="prompt" rows="1" placeholder="Tell the browser what to do…" aria-label="Message"></textarea>
      <div class="row">
        <select id="model" title="Model for this message"></select>
        <button id="stop" hidden>Stop</button>
        <button id="send" class="primary">Send</button>
      </div>
    </div>
  </aside>
</div>
<button id="drawer" title="Show the chat (Ctrl+B)">Chat</button>
<div id="toasts" aria-live="polite"></div>

<dialog id="dlg-settings">
  <h2>Model</h2>
  <p class="lead">The AI that reads the page and decides what to do. Any OpenAI-compatible service works.</p>
  <label class="field"><span>API key</span>
    <input type="password" id="set-key" placeholder="Leave empty to keep the saved key" autocomplete="off">
    <span class="hint" id="set-keyhint"></span></label>
  <label class="field"><span>Models to use, first one by default</span>
    <textarea id="set-models" spellcheck="false" placeholder="one model id per line"></textarea>
    <span class="hint">If one fails — no tool support, too busy — the next one is tried.</span></label>
  <button id="set-free" type="button">Add free OpenRouter models</button>
  <details class="more"><summary>Another provider</summary>
    <label class="field"><span>Service address</span>
      <input type="text" id="set-endpoint" spellcheck="false">
      <span class="hint">For example http://localhost:11434/v1 for Ollama.</span></label>
  </details>
  <div class="actions">
    <span class="spacer"></span>
    <button data-close>Cancel</button>
    <button id="set-save" class="primary">Save</button>
  </div>
</dialog>

<dialog id="dlg-session">
  <h2 id="ses-title">New session</h2>
  <p class="lead" id="ses-lead">A session is a browser the AI works in, with its own tabs and chats.</p>
  <label class="field" id="ses-name-row"><span>Name</span>
    <input type="text" id="ses-name" placeholder="e.g. research" spellcheck="false">
    <span class="hint">Lowercase letters, numbers and dashes.</span></label>
  <label class="field"><span>Logins from</span>
    <span style="display:flex; gap:6px">
      <select id="ses-profile" style="flex:1"></select>
      <button class="icon" id="ses-profile-del" type="button" title="Delete this profile and its logins (only if no session uses it)">🗑</button>
    </span>
    <span class="hint">A profile keeps logins and cookies. Sessions on the same profile share them.</span></label>
  <label class="field" id="ses-newprofile-row" hidden><span>New profile name</span>
    <input type="text" id="ses-newprofile" placeholder="e.g. work" spellcheck="false"></label>
  <label class="field"><span>Sites it may visit</span>
    <textarea id="ses-rules" spellcheck="false" placeholder="Leave empty for any site.&#10;app.example.com/admin&#10;!app.example.com/api"></textarea>
    <span class="hint">One per line. A line allows a site or page; a line starting with ! blocks it. Once anything is allowed, everything else is blocked.</span></label>
  <details class="more"><summary>More</summary>
    <label class="check"><input type="checkbox" id="ses-runjs" checked><span>Let the AI run scripts on the page<small>Scripts still cannot reach blocked sites.</small></span></label>
    <label class="check"><input type="checkbox" id="ses-strict"><span>Also check images, styles and scripts against the site list<small>Stricter, but pages that load from other sites may break.</small></span></label>
    <label class="check" id="ses-sealed-row"><input type="checkbox" id="ses-sealed" checked><span>Only this app can use it<small>Other programs and agents on this computer cannot drive it.</small></span></label>
  </details>
  <div class="actions">
    <button id="ses-del" hidden>Delete session</button>
    <span class="spacer"></span>
    <button data-close>Cancel</button>
    <button id="ses-save" class="primary">Create session</button>
  </div>
</dialog>

<dialog id="dlg-token">
  <h2>Connect to the toolkit</h2>
  <p class="lead">Opened outside the desktop app, this page needs the server's access token once.
    It is in <code id="tok-path">sessions/operator.token</code>.</p>
  <label class="field"><span>Access token</span><input type="password" id="tok-value" autocomplete="off"></label>
  <div class="actions"><span class="spacer"></span><button id="tok-save" class="primary">Connect</button></div>
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
  meta: null, running: false, busy: false, settings: { models: [] }, runningChats: new Set(), buffers: {},
  starting: false, lastStart: {},
};

// --- theme ------------------------------------------------------------------------

const THEMES = ["system", "light", "dark"];
function applyTheme() {
  const t = store.get("theme", "system");
  if (t === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", t);
  $("#theme").textContent = { system: "◐", light: "☀", dark: "☾" }[t];
  $("#theme").title = { system: "Theme follows your system", light: "Light theme", dark: "Dark theme" }[t] + " — click to switch";
}
$("#theme").onclick = () => {
  const next = THEMES[(THEMES.indexOf(store.get("theme", "system")) + 1) % THEMES.length];
  store.set("theme", next); applyTheme();
  toast({ system: "Theme follows your system", light: "Light theme", dark: "Dark theme" }[next]);
};

// --- toasts ------------------------------------------------------------------------

function toast(text, bad) {
  if (!text) return;
  const el = document.createElement("div");
  el.className = "toast" + (bad ? " bad" : ""); el.textContent = text;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), bad ? 6500 : 3200);
}
const say = toast;
function fail(e) { toast(e.hint && e.type === "url_blocked" ? e.message : (e.message || String(e)), true); }

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
  try { b = await r.json(); } catch (e) { throw new Error(`The toolkit answered HTTP ${r.status}`); }
  if (b.ok === false) {
    const err = b.error || {};
    const e = new Error(err.message || "The toolkit refused that"); e.type = err.type; e.hint = err.hint; throw e;
  }
  return b.result !== undefined ? b.result : b;
}

const run = (cmd) => api("POST", "/command-list", cmd);

// --- sessions -------------------------------------------------------------------------

async function loadAll() {
  S.profiles = await api("GET", "/profiles", undefined, { session: null });
  S.sessions = await api("GET", "/sessions", undefined, { session: null });
  if (!S.sessions.find(s => s.name === S.session)) S.session = "default";
  const current = S.sessions.find(s => s.name === S.session);
  S.profile = current ? current.profile : "default";
  drawSessionButton();
}

function drawSessionButton() {
  const info = S.sessions.find(s => s.name === S.session) || { name: S.session, profile: S.profile };
  $("#session-name").textContent = info.name + (info.sealed ? " 🔒" : "");
  $("#session-sub").textContent = info.profile === info.name ? "" : `logins: ${info.profile}`;
  $("#session-dot").className = "dot" + (S.runningChats.size ? " busy" : S.running ? " on" : "");
  const rules = (info.settings && info.settings.rules) || S.rules || [];
  const pill = $("#rules-pill");
  pill.hidden = !rules.length;
  if (rules.length) {
    const allowed = rules.filter(r => !r.startsWith("!"));
    pill.textContent = allowed.length ? `Limited to ${allowed.length === 1 ? allowed[0] : allowed.length + " sites"}` : `${rules.length} site${rules.length > 1 ? "s" : ""} blocked`;
    pill.title = "Site rules for this session:\n" + rules.join("\n") + "\n\nClick to change.";
  }
}

function drawSessionMenu() {
  const byProfile = {};
  for (const s of S.sessions) (byProfile[s.profile] = byProfile[s.profile] || []).push(s);
  let html = "";
  for (const profile of Object.keys(byProfile).sort()) {
    html += `<h4>Logins: ${esc(profile)}</h4>`;
    for (const s of byProfile[profile]) {
      html += `<button class="row${s.name === S.session ? " on" : ""}" data-session="${esc(s.name)}">
        <span class="dot${s.running ? " on" : ""}"></span><span class="grow">${esc(s.name)}</span>
        <span class="meta">${s.sealed ? "🔒" : ""}</span></button>`;
    }
  }
  html += `<hr><button class="row" data-action="new"><span class="grow">＋ New session</span></button>`;
  html += `<button class="row" data-action="edit"><span class="grow">Settings for “${esc(S.session)}”</span></button>`;
  $("#session-menu").innerHTML = html;
}

function toggleMenu(open) {
  const menu = $("#session-menu");
  const show = open === undefined ? menu.hidden : open;
  if (show) drawSessionMenu();
  menu.hidden = !show; $("#session-btn").setAttribute("aria-expanded", String(show));
}
$("#session-btn").onclick = (e) => { e.stopPropagation(); toggleMenu(); };
$("#session-menu").onclick = (e) => {
  const row = e.target.closest(".row"); if (!row) return;
  toggleMenu(false);
  if (row.dataset.session) selectSession(row.dataset.session);
  else if (row.dataset.action === "new") openSessionDialog(false);
  else if (row.dataset.action === "edit") openSessionDialog(true);
};
document.addEventListener("click", (e) => { if (!e.target.closest("#session-menu")) toggleMenu(false); });
$("#rules-pill").onclick = () => openSessionDialog(true);

async function selectSession(name) {
  if (!name) return;
  S.session = name; store.set("session", name);
  const info = S.sessions.find(s => s.name === name);
  S.profile = info ? info.profile : S.profile;
  S.rules = null; S.tab = null;
  drawSessionButton();
  closeScreen(); hideActivity();
  loadRules();
  // Chats first, then the socket: what it replays lands on the drawn chat.
  await refreshBrowser(); await loadChats(); openChatSocket();
}

async function loadRules() {
  try { const info = await api("GET", "/sessions/" + encodeURIComponent(S.session)); S.rules = (info.settings || {}).rules || []; drawSessionButton(); }
  catch (e) {}
}

function openSessionDialog(edit) {
  const dlg = $("#dlg-session");
  $("#ses-title").textContent = edit ? `Session “${S.session}”` : "New session";
  $("#ses-lead").textContent = edit ? "Changes apply from the AI's next step." : "A session is a browser the AI works in, with its own tabs and chats.";
  $("#ses-name-row").hidden = edit;
  $("#ses-sealed-row").hidden = edit;
  $("#ses-save").textContent = edit ? "Save changes" : "Create session";
  $("#ses-del").hidden = !edit || S.session === "default";
  const drawProfiles = (pick) => {
    $("#ses-profile").innerHTML = S.profiles.map(p =>
      `<option value="${esc(p.name)}"${p.name === pick ? " selected" : ""}>${esc(p.name)}</option>`).join("")
      + `<option value="__new__"${pick === "__new__" ? " selected" : ""}>New profile — fresh logins</option>`;
    $("#ses-newprofile-row").hidden = pick !== "__new__";
  };
  drawProfiles(edit ? S.profile : "__new__");
  $("#ses-newprofile").value = ""; $("#ses-name").value = "";
  $("#ses-rules").value = ""; $("#ses-strict").checked = false; $("#ses-runjs").checked = true;
  $("#ses-profile").onchange = () => {
    const isNew = $("#ses-profile").value === "__new__";
    $("#ses-newprofile-row").hidden = !isNew;
    if (isNew) $("#ses-newprofile").focus();
  };
  // A new session's name doubles as its profile's, unless someone says otherwise.
  $("#ses-name").oninput = () => { if (!edit) $("#ses-newprofile").placeholder = $("#ses-name").value.trim() || "e.g. work"; };
  $("#ses-profile-del").onclick = async () => {
    const name = $("#ses-profile").value;
    if (name === "__new__") return;
    if (name === "default") return toast("The default profile cannot be removed", true);
    if (!confirm(`Delete profile “${name}” and every login in it? This cannot be undone.`)) return;
    try {
      await api("DELETE", "/profiles/" + encodeURIComponent(name), undefined, { session: null });
      S.profiles = await api("GET", "/profiles", undefined, { session: null });
      drawProfiles(S.profile); toast("Profile deleted");
    } catch (e) { fail(e); }
  };
  if (edit) {
    api("GET", "/sessions/" + encodeURIComponent(S.session)).then(info => {
      const st = info.settings || {};
      $("#ses-rules").value = (st.rules || []).join("\n");
      $("#ses-strict").checked = !!st.strict;
      $("#ses-runjs").checked = st.run_js !== false;
    }).catch(fail);
  }
  $("#ses-del").onclick = async () => {
    if (!confirm(`Delete session “${S.session}”? Its tabs close. Its logs and chats are kept aside.`)) return;
    try { await api("DELETE", "/sessions/" + encodeURIComponent(S.session)); dlg.close(); S.session = "default"; await loadAll(); await selectSession("default"); toast("Session deleted"); }
    catch (e) { fail(e); }
  };
  $("#ses-save").onclick = async () => {
    const settings = {
      rules: $("#ses-rules").value.split("\n").map(s => s.trim()).filter(Boolean),
      strict: $("#ses-strict").checked, run_js: $("#ses-runjs").checked,
    };
    const name = edit ? S.session : $("#ses-name").value.trim().toLowerCase();
    if (!edit && !name) return toast("Give the session a name", true);
    try {
      let profile = $("#ses-profile").value;
      if (profile === "__new__") {
        profile = ($("#ses-newprofile").value.trim() || name).toLowerCase();
        if (!S.profiles.find(p => p.name === profile)) await api("POST", "/profiles", { name: profile }, { session: null });
        S.profiles = await api("GET", "/profiles", undefined, { session: null });
      }
      if (edit) {
        const body = { settings };
        if (profile !== S.profile) body.profile = profile;
        const out = await api("PATCH", "/sessions/" + encodeURIComponent(S.session), body);
        dlg.close(); toast(out.warning || "Session saved");
        await loadAll(); await selectSession(S.session);
      } else {
        const out = await api("POST", "/sessions", { name, profile, sealed: $("#ses-sealed").checked, settings }, { session: null });
        if (out.token) { S.tokens[name] = out.token; try { sessionStorage.setItem("abt.tok." + name, out.token); } catch (e) {} }
        dlg.close(); toast(`Session “${name}” created`);
        await loadAll(); await selectSession(name);
      }
    } catch (e) { fail(e); }
  };
  dlg.showModal();
  if (!edit) $("#ses-name").focus();
}

// --- the browser pane ------------------------------------------------------------------

async function refreshBrowser() {
  if (!S.session) return;
  // /browser answers without touching the browser. /status reads every tab,
  // and doing that under an agent's feet switches tabs mid-command.
  let status;
  try { status = await api("GET", "/browser?session=" + encodeURIComponent(S.session)); }
  catch (e) { fail(e); return; }
  S.running = !!status.running;
  drawSessionButton();
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
  if (!S.tab || !own.find(t => t.tab_id === S.tab)) S.tab = active ? active.tab_id : null;
  const shown = S.tabs.find(t => t.tab_id === S.tab);
  if (shown && document.activeElement !== $("#url")) $("#url").value = shown.url === "about:blank" ? "" : (shown.url || "");
  drawTabs();
  if (S.tab) openScreen(S.tab);
}

function drawTabs() {
  // Other sessions' tabs and unclaimed ones are the machinery, not the page
  // the person is using: only this session's tabs show.
  const own = S.tabs.filter(t => !t.locked && !t.unowned && !t.pending);
  $("#tabs").innerHTML = own.map(t => {
    const label = t.title || (t.url === "about:blank" ? "New tab" : t.url) || "New tab";
    return `<div class="tab${t.tab_id === S.tab ? " on" : ""}" data-tab="${esc(t.tab_id)}" title="${esc(t.url || "")}">${esc(label)}</div>`;
  }).join("");
}

$("#tabs").onclick = async (e) => {
  const el = e.target.closest(".tab"); if (!el) return;
  try { await run({ op: "tab_switch", tab_id: el.dataset.tab }); S.tab = el.dataset.tab; await refreshBrowser(); }
  catch (err) { fail(err); }
};

async function ensureBrowser(op) {
  const session = S.session;
  if (!session || S.starting) return;
  const last = S.lastStart[session] || 0;
  if (Date.now() - last < 15000) {
    viewMessage("The browser did not start.", "Try again", () => { S.lastStart[session] = 0; ensureBrowser(op); });
    return;
  }
  S.starting = true; S.lastStart[session] = Date.now();
  viewMessage(op === "browser_restart" ? "Restarting the browser…" : "Starting the browser…");
  try { await run({ op }); }
  catch (e) {
    if (!/already running/.test(e.message || "")) { S.starting = false; viewMessage(e.message, "Try again", () => { S.lastStart[session] = 0; ensureBrowser(op); }); return; }
  }
  S.starting = false;
  if (S.session === session) { await loadAll(); await refreshBrowser(); }
}

function viewMessage(text, action, onAction) {
  const box = $("#viewmsg");
  box.hidden = false; box.innerHTML = `<div>${esc(text)}</div>` + (action ? `<button>${esc(action)}</button>` : "");
  if (action) box.querySelector("button").onclick = onAction;
}

$("#restart").onclick = () => { S.lastStart[S.session] = 0; ensureBrowser("browser_restart"); };
async function nav(cmd) { try { await run(cmd); await refreshBrowser(); } catch (e) { fail(e); } }
$("#back").onclick = () => nav({ op: "back", diff: false });
$("#fwd").onclick = () => nav({ op: "forward", diff: false });
$("#reload").onclick = () => nav({ op: "reload", diff: false });
$("#newtab").onclick = async () => {
  try { const out = await run({ op: "tab_new" }); S.tab = out.tab_id; await refreshBrowser(); $("#url").focus(); } catch (e) { fail(e); }
};
$("#url").onkeydown = (e) => {
  if (e.key !== "Enter") return;
  let url = $("#url").value.trim(); if (!url) return;
  if (!/^[a-z]+:/i.test(url)) url = (/\s/.test(url) || !/\./.test(url)) ? "https://duckduckgo.com/?q=" + encodeURIComponent(url) : "https://" + url;
  $("#url").blur(); nav({ op: "goto", url, diff: false });
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
  viewMessage("Connecting…");
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.type === "frame") {
      $("#screen").src = "data:image/jpeg;base64," + m.data; S.meta = m.metadata;
      $("#viewmsg").hidden = true;
    } else if (m.ok === false) {
      const err = m.error || {};
      viewMessage(err.message || "This tab cannot be shown");
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
  if ((e.ctrlKey || e.metaKey) && ["b", "l"].includes(e.key.toLowerCase())) return;
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

// What the agent is doing, said on the page it is doing it to.
function showActivity(text) {
  $("#activity-text").textContent = text; $("#activity").hidden = false; $("#view").classList.add("working");
}
function hideActivity() { $("#activity").hidden = true; $("#view").classList.remove("working"); }

// --- layout -------------------------------------------------------------------------

function applyLayout() {
  const main = $("#main"), left = store.get("dock", "right") === "left", hidden = !!store.get("hidden", false);
  main.classList.toggle("dock-left", left); main.classList.toggle("dock-right", !left);
  main.classList.toggle("chat-hidden", hidden);
  $("#chat").style.width = store.get("width", 420) + "px";
  $("#toggle-chat").textContent = hidden ? "⇤" : "⇥";
  $("#toggle-chat").title = (hidden ? "Show" : "Hide") + " the chat (Ctrl+B)";
}
$("#dock").onclick = () => { store.set("dock", store.get("dock", "right") === "left" ? "right" : "left"); applyLayout(); };
const toggleChat = () => { store.set("hidden", !store.get("hidden", false)); applyLayout(); };
$("#toggle-chat").onclick = toggleChat;
$("#drawer").onclick = toggleChat;
document.addEventListener("keydown", (e) => {
  if (!(e.ctrlKey || e.metaKey)) return;
  const k = e.key.toLowerCase();
  if (k === "b") { e.preventDefault(); toggleChat(); }
  if (k === "l") { e.preventDefault(); $("#url").focus(); $("#url").select(); }
}, true);
$("#splitter").addEventListener("mousedown", (e) => {
  e.preventDefault();
  const left = store.get("dock", "right") === "left";
  const move = (ev) => {
    const width = left ? ev.clientX : window.innerWidth - ev.clientX;
    const clamped = Math.max(300, Math.min(window.innerWidth * 0.7, width));
    $("#chat").style.width = clamped + "px"; store.set("width", Math.round(clamped));
  };
  const up = () => { document.removeEventListener("mousemove", move); document.removeEventListener("mouseup", up); };
  document.addEventListener("mousemove", move); document.addEventListener("mouseup", up);
});

// --- model settings -----------------------------------------------------------------------

async function loadModels() {
  try { S.settings = await api("GET", "/app/settings", undefined, { operator: true, session: null }); }
  catch (e) { S.settings = { models: [] }; }
  drawModels();
}
function ready() { return !!(S.settings.models && S.settings.models.length && (S.settings.has_key || !/openrouter\.ai/.test(S.settings.endpoint || ""))); }
function shortModel(m) {
  if (!m) return "";
  if (m === "openrouter/free") return "Any free model";
  if (m === "openrouter/auto") return "Automatic";
  return m.split("/").pop().replace(/:free$/, " (free)");
}
function drawModels(chosen) {
  const models = S.settings.models || [];
  const pick = chosen || (S.chat && S.chat.model && models.includes(S.chat.model) ? S.chat.model : models[0]);
  $("#model").innerHTML = models.map(m => `<option value="${esc(m)}"${m === pick ? " selected" : ""}>${esc(shortModel(m))}</option>`).join("");
  $("#model-name").textContent = pick ? shortModel(pick) : "not set";
  if (!S.chat || !(S.chat.messages || []).length) drawHistory();
}
$("#model").onchange = () => { $("#model-name").textContent = shortModel($("#model").value); };
$("#model-btn").onclick = openModelDialog;
async function openModelDialog() {
  await loadModels();
  $("#set-endpoint").value = S.settings.endpoint || "https://openrouter.ai/api/v1";
  $("#set-key").value = "";
  $("#set-keyhint").textContent = S.settings.has_key ? `A key ending ${S.settings.key_hint} is saved.` : "No key saved yet.";
  $("#set-models").value = (S.settings.models || []).join("\n");
  $("#dlg-settings").showModal();
}
async function freeModels() {
  return api("GET", "/app/models/free", undefined, { operator: true, session: null });
}
$("#set-free").onclick = async () => {
  const b = $("#set-free"); b.disabled = true; b.textContent = "Looking…";
  try {
    await api("PUT", "/app/settings", { endpoint: $("#set-endpoint").value.trim() }, { operator: true, session: null });
    const found = await freeModels();
    const have = new Set($("#set-models").value.split("\n").map(s => s.trim()).filter(Boolean));
    const add = found.map(m => m.id).filter(id => !have.has(id));
    $("#set-models").value = [...have, ...add].join("\n");
    toast(add.length ? `Added ${add.length} free models` : "No new free models found");
  } catch (e) { fail(e); }
  b.disabled = false; b.textContent = "Add free OpenRouter models";
};
$("#set-save").onclick = async () => {
  const body = { endpoint: $("#set-endpoint").value.trim(), models: $("#set-models").value.split("\n").map(s => s.trim()).filter(Boolean) };
  if ($("#set-key").value.trim()) body.api_key = $("#set-key").value.trim();
  try { S.settings = await api("PUT", "/app/settings", body, { operator: true, session: null }); drawModels(); $("#dlg-settings").close(); toast("Model settings saved"); }
  catch (e) { fail(e); }
};
document.querySelectorAll("[data-close]").forEach(b => b.onclick = () => b.closest("dialog").close());

// First run: set up the model inside the chat, where the person already is.
function drawSetup() {
  $("#messages").innerHTML = `<div class="setup">
    <h3>Connect an AI model</h3>
    <p class="muted" style="margin:0">It reads the page and decides what to click and type. Two steps, once.</p>
    <ol>
      <li><label for="setup-key">Paste an OpenRouter key</label>
        <input type="password" id="setup-key" placeholder="${S.settings.has_key ? "A key is saved — paste to replace it" : "sk-or-…"}" autocomplete="off">
        <div class="hint">Free to create at openrouter.ai/keys. It stays on this computer.</div></li>
      <li><label>Pick a model</label>
        <button id="setup-find">Show free models</button>
        <div class="models" id="setup-models"></div></li>
    </ol>
    <div style="display:flex; gap:8px; margin-top:16px">
      <button class="primary" id="setup-save">Start</button>
      <button class="ghost" id="setup-other">Use another provider</button>
    </div></div>`;
  $("#setup-other").onclick = openModelDialog;
  $("#setup-find").onclick = async () => {
    const b = $("#setup-find"); b.disabled = true; b.textContent = "Looking…";
    try {
      const found = await freeModels();
      $("#setup-models").innerHTML = found.slice(0, 20).map((m, i) =>
        `<label><input type="radio" name="setup-model" value="${esc(m.id)}"${i === 0 ? " checked" : ""}> ${esc(m.name || m.id)}</label>`).join("")
        || `<div class="hint">No free models with tool support right now. Use another provider.</div>`;
      b.textContent = "Refresh list";
    } catch (e) { fail(e); b.textContent = "Show free models"; }
    b.disabled = false;
  };
  $("#setup-save").onclick = async () => {
    const key = $("#setup-key").value.trim();
    const picked = [...document.querySelectorAll('input[name="setup-model"]')];
    const chosen = picked.find(r => r.checked);
    if (!key && !S.settings.has_key) return toast("Paste your OpenRouter key first", true);
    if (!chosen) return toast("Click “Show free models” and pick one", true);
    // The chosen model first, the rest behind it to fall back on.
    const models = [chosen.value, ...picked.map(r => r.value).filter(v => v !== chosen.value)];
    const body = { endpoint: "https://openrouter.ai/api/v1", models };
    if (key) body.api_key = key;
    try { S.settings = await api("PUT", "/app/settings", body, { operator: true, session: null }); drawModels(); toast("Ready — tell the browser what to do"); $("#prompt").focus(); }
    catch (e) { fail(e); }
  };
}

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
  for (const e of S.buffers[id] || []) renderEvent(e);
  setBusy(S.runningChats.has(id));
}
$("#chatpick").onchange = (e) => openChat(e.target.value);
$("#chat-new").onclick = async () => { try { const c = await api("POST", "/app/chats", { model: $("#model").value || null }); await loadChats(c.id); $("#prompt").focus(); } catch (e) { fail(e); } };
$("#chat-del").onclick = async () => {
  if (!S.chat || !confirm("Delete this conversation?")) return;
  try { await api("DELETE", "/app/chats/" + encodeURIComponent(S.chat.id)); store.set("chat." + S.session, null); await loadChats(); toast("Conversation deleted"); } catch (e) { fail(e); }
};

function add(html) { const m = $("#messages"); m.insertAdjacentHTML("beforeend", html); m.scrollTop = m.scrollHeight; }
function bubble(role, text) {
  if (role === "assistant") return add(`<div class="msg assistant md">${markdown(text)}</div>`);
  add(`<div class="msg ${role}">${esc(text)}</div>`);
}

// A tool call in words a person would use.
function describe(name, args) {
  if (name === "browser_guidelines") return args.domain ? `Checked site notes for ${args.domain}` : "Read the toolkit's notes";
  if (name === "browser_session") return ({ start: "Started the browser", stop: "Stopped the browser", restart: "Restarted the browser", status: "Checked the browser" })[args.action] || "Checked the browser";
  const cmds = (args.commands || []);
  const said = cmds.map(c => {
    const what = c.text || c.value || c.css || c.level || c.ref || "";
    switch (c.op) {
      case "goto": { let host = c.url; try { host = new URL(c.url).host; } catch (e) {} return `Opened ${host}`; }
      case "click": return `Clicked ${c.text ? "“" + c.text + "”" : "an element"}`;
      case "input": return `Typed ${c.value && c.value.length < 40 ? "“" + c.value + "”" : "text"}`;
      case "press": return `Pressed ${c.key}`;
      case "select": return `Chose “${c.value || ""}”`;
      case "get_text": return "Read the page";
      case "find": case "find_full": return `Looked for ${what ? "“" + what + "”" : "an element"}`;
      case "scroll": return "Scrolled";
      case "wait_for": return "Waited for the page";
      case "back": return "Went back"; case "forward": return "Went forward"; case "reload": return "Reloaded";
      case "tab_new": return "Opened a tab"; case "tab_switch": return "Switched tab"; case "tab_close": return "Closed a tab";
      case "screenshot": return "Took a screenshot"; case "run_js": return "Ran a script";
      case "hover": return "Hovered";
      case "guidelines_note": return "Saved a note about this site";
      case "guidelines_read": case "guidelines_search": return "Read notes about this site";
      case "read_console": return "Checked the page's console";
      case "read_network": return "Checked the page's network requests";
      case "current_url": case "status": case "tab_list": case "browser_status": return "Checked where the browser is";
      case "alert": return "Answered a pop-up";
      case "diff": return "Checked what changed";
      case "tab_claim": return "Took over a tab"; case "tab_release": return "Let go of a tab";
      case "browser_start": return "Started the browser"; case "browser_restart": return "Restarted the browser";
      case "browser_stop": return "Stopped the browser";
      default: return (c.op || "worked on the page").replace(/_/g, " ");
    }
  });
  if (!said.length) return "Worked on the page";
  return said.length > 3 ? `${said.slice(0, 3).join(", ")} and ${said.length - 3} more` : said.join(", ");
}

function step(name, args, result, bad) {
  const shown = result === undefined ? "" : String(result).slice(0, 4000);
  add(`<details class="step ${bad ? "fail" : "ok"}"><summary><span class="mark">${bad ? "✗" : "✓"}</span><span>${esc(describe(name, args))}</span></summary>` +
      `<pre>${esc(name)} ${esc(JSON.stringify(args, null, 1))}</pre>${shown ? `<pre>${esc(shown)}</pre>` : ""}</details>`);
}

const EXAMPLES = [
  "Open example.com and tell me what the page says",
  "Search DuckDuckGo for today's weather in London and summarise it",
  "Go to news.ycombinator.com and list the top 5 stories",
];
function drawHistory() {
  if (!ready()) return drawSetup();
  $("#messages").innerHTML = "";
  const msgs = (S.chat && S.chat.messages) || [];
  const results = {};
  msgs.filter(m => m.role === "tool").forEach(m => results[m.tool_call_id] = m.content);
  for (const m of msgs) {
    if (m.role === "user") bubble("user", m.content);
    else if (m.role === "assistant") {
      for (const call of m.tool_calls || []) {
        let args = {}; try { args = JSON.parse(call.function.arguments || "{}"); } catch (e) {}
        const r = results[call.id]; step(call.function.name, args, r, r && r.includes('"ok":false'));
      }
      if (m.content && m.content.trim()) bubble("assistant", m.content);
    }
  }
  if (!msgs.length) {
    add(`<div class="empty"><h3>What should the browser do?</h3>
      <p>Describe a task in plain words. You will see each step here and on the page, and you can click in the page yourself at any time.</p>
      <div class="suggestions">${EXAMPLES.map(t => `<button data-example="${esc(t)}">${esc(t)}</button>`).join("")}</div></div>`);
    document.querySelectorAll("[data-example]").forEach(b => b.onclick = () => { $("#prompt").value = b.dataset.example; grow(); $("#prompt").focus(); });
  }
}

function openChatSocket() {
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
  else if (e.type === "tool_result") { step(e.name, pendingTool ? pendingTool.args : {}, e.text, e.error); pendingTool = null; }
  else if (e.type === "notice") bubble("notice", e.text);
  else if (e.type === "error") bubble("error", e.text);
}

async function onChatEvent(e) {
  if (e.ok === false) { bubble("error", (e.error && e.error.message) || "The chat is unavailable"); return; }
  const id = e.chat_id;
  const here = S.chat && S.chat.id === id;
  if (e.type === "resume") {
    S.runningChats.add(id); S.buffers[id] = [];
    if (here) { drawHistory(); setBusy(true); }
    drawSessionButton();
    return;
  }
  if (e.type === "done") {
    S.runningChats.delete(id); delete S.buffers[id];
    const opt = [...$("#chatpick").options].find(o => o.value === id); if (opt) opt.textContent = e.title;
    if (!S.runningChats.size) hideActivity();
    drawSessionButton();
    if (here) { await openChat(id); refreshBrowser(); }
    return;
  }
  if (e.type === "user") { S.runningChats.add(id); S.buffers[id] = []; if (here) setBusy(true); drawSessionButton(); }
  if (e.type === "error" && !S.runningChats.has(id)) { if (here) { bubble("error", e.text); setBusy(false); } return; }
  if (e.type === "tool_call") showActivity(describe(e.name, e.args || {}).replace(/^Opened/, "Opening").replace(/^Clicked/, "Clicking").replace(/^Typed/, "Typing").replace(/^Read/, "Reading").replace(/^Looked/, "Looking").replace(/^Pressed/, "Pressing") + "…");
  if (!S.buffers[id]) S.buffers[id] = [];
  S.buffers[id].push(e);
  if (here) renderEvent(e);
}

function setBusy(busy) {
  S.busy = busy; $("#send").hidden = busy; $("#stop").hidden = !busy;
  $("#prompt").placeholder = busy ? "Working… you can type your next message" : "Tell the browser what to do…";
}

function grow() { const p = $("#prompt"); p.style.height = "auto"; p.style.height = Math.min(p.scrollHeight, window.innerHeight * 0.4) + "px"; }
$("#prompt").addEventListener("input", grow);

async function send() {
  const text = $("#prompt").value.trim();
  if (!text || S.busy || !S.chat) return;
  if (!ready()) return drawSetup();
  if (!S.chatSock || S.chatSock.readyState !== 1) { openChatSocket(); return toast("Reconnecting — send again in a moment", true); }
  $("#prompt").value = ""; grow(); setBusy(true);
  if (!(S.chat.messages || []).length && document.querySelector(".empty")) $("#messages").innerHTML = "";
  S.chatSock.send(JSON.stringify({ type: "send", chat_id: S.chat.id, text, model: $("#model").value || null }));
}
$("#send").onclick = send;
$("#stop").onclick = () => { if (S.chatSock && S.chat) { S.chatSock.send(JSON.stringify({ type: "stop", chat_id: S.chat.id })); toast("Stopping after this step"); } };
$("#prompt").onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } };

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

// --- start -------------------------------------------------------------------------------

(async function boot() {
  applyTheme(); applyLayout();
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
