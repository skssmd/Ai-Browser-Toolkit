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
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA2NCA2NCI+PHN0eWxlPi5kaXNjLC5nYXB7ZmlsbDojMTExO3N0cm9rZTojMTExfS5tYXJre2ZpbGw6I2ZmZn1AbWVkaWEgKHByZWZlcnMtY29sb3Itc2NoZW1lOmRhcmspey5kaXNjLC5nYXB7ZmlsbDojZmZmO3N0cm9rZTojZmZmfS5tYXJre2ZpbGw6IzExMX19PC9zdHlsZT48Y2lyY2xlIGNsYXNzPSJkaXNjIiBjeD0iMzIiIGN5PSIzMiIgcj0iMzEiIGZpbGw9IiMxMTExMTEiLz48ZyB0cmFuc2Zvcm09InRyYW5zbGF0ZSgzMiAzMikgc2NhbGUoMC43OCkgdHJhbnNsYXRlKC0zMi41IC0zMS41KSI+PHBhdGggY2xhc3M9Im1hcmsiIGQ9Ik02IDU2IEwxOSA4IEwyNyA4IEwxNCA1NiBaIiBmaWxsPSIjZmZmZmZmIi8+PHBhdGggY2xhc3M9Im1hcmsiIGQ9Ik0yMCA1NiBMMzMgOCBMNDEgOCBMMjggNTYgWiIgZmlsbD0iI2ZmZmZmZiIvPjxwYXRoIGNsYXNzPSJtYXJrIiBkPSJNNTEuMDAgNi4wMCBMNTIuNzYgMTIuMjQgTDU5LjAwIDE0LjAwIEw1Mi43NiAxNS43NiBMNTEuMDAgMjIuMDAgTDQ5LjI0IDE1Ljc2IEw0My4wMCAxNC4wMCBMNDkuMjQgMTIuMjRaIiBmaWxsPSIjZmZmZmZmIi8+PHBhdGggY2xhc3M9ImdhcCIgZD0iTTM0LjUwIDI1LjAwIEwzNC41MCA1My44MCBMNDEuOTQgNDcuMDggTDQ2Ljk4IDU4LjEyIEw1Mi4wMiA1NS44NCBMNDcuMTAgNDUuMDQgTDU3LjA2IDQ1LjA0WiIgZmlsbD0iIzExMTExMSIgc3Ryb2tlPSIjMTExMTExIiBzdHJva2Utd2lkdGg9IjciIHN0cm9rZS1saW5lam9pbj0ibWl0ZXIiIHN0cm9rZS1taXRlcmxpbWl0PSIxMCIvPjxwYXRoIGNsYXNzPSJtYXJrIiBkPSJNMzQuNTAgMjUuMDAgTDM0LjUwIDUzLjgwIEw0MS45NCA0Ny4wOCBMNDYuOTggNTguMTIgTDUyLjAyIDU1Ljg0IEw0Ny4xMCA0NS4wNCBMNTcuMDYgNDUuMDRaIiBmaWxsPSIjZmZmZmZmIi8+PC9nPjwvc3ZnPg==">
<style>
  :root {
    color-scheme: light;
    --bg: #FAFAF9; --panel: #FFFFFF; --raised: #F3F3F1; --ink: #1C1C1C; --muted: #6F6F6F;
    --line: #E4E4E2; --live: #16A34A; --live-soft: rgba(22,163,74,.12); --bad: #C2410C;
    --bad-soft: rgba(194,65,12,.10); --btn: #1C1C1C; --btn-ink: #FFFFFF; --code: #F3F3F1;
    --user: #1C1C1C; --user-ink: #FFFFFF; --shadow: 0 8px 28px rgba(0,0,0,.14);
    --scroll: #CFCFCB; --scroll-hover: #A3A3A0;
  }
  :root[data-theme="dark"] {
    color-scheme: dark;
    --bg: #161616; --panel: #1E1E1E; --raised: #262626; --ink: #EDEDED; --muted: #9A9A9A;
    --line: #333333; --live: #22C55E; --live-soft: rgba(34,197,94,.14); --bad: #F97316;
    --bad-soft: rgba(249,115,22,.12); --btn: #EDEDED; --btn-ink: #161616; --code: #262626;
    --user: #EDEDED; --user-ink: #161616; --shadow: 0 8px 28px rgba(0,0,0,.5);
    --scroll: #3F3F3F; --scroll-hover: #5C5C5C;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      color-scheme: dark;
      --bg: #161616; --panel: #1E1E1E; --raised: #262626; --ink: #EDEDED; --muted: #9A9A9A;
      --line: #333333; --live: #22C55E; --live-soft: rgba(34,197,94,.14); --bad: #F97316;
      --bad-soft: rgba(249,115,22,.12); --btn: #EDEDED; --btn-ink: #161616; --code: #262626;
      --user: #EDEDED; --user-ink: #161616; --shadow: 0 8px 28px rgba(0,0,0,.5);
      --scroll: #3F3F3F; --scroll-hover: #5C5C5C;
    }
  }
  * { box-sizing: border-box; }
  [hidden] { display: none !important; }

  /* Scrollbars: thin, rounded, in the theme's greys, no arrow buttons. The
     standard properties cover current Chromium (WebView2); the -webkit- rules
     cover older engines and draw the rounded thumb. */
  * { scrollbar-width: thin; scrollbar-color: var(--scroll) transparent; }
  *:hover { scrollbar-color: var(--scroll-hover) transparent; }
  ::-webkit-scrollbar { width: 10px; height: 10px; }
  ::-webkit-scrollbar-track, ::-webkit-scrollbar-corner { background: transparent; }
  ::-webkit-scrollbar-button { display: none; }
  ::-webkit-scrollbar-thumb {
    background: var(--scroll); border-radius: 999px; border: 3px solid transparent; background-clip: content-box;
  }
  ::-webkit-scrollbar-thumb:hover { background-color: var(--scroll-hover); }
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

  /* --- model settings: how to connect --- */
  .seg { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin: 14px 0 4px; }
  .seg label {
    display: flex; align-items: center; gap: 9px; padding: 9px 11px; cursor: pointer;
    border: 1px solid var(--line); border-radius: 9px; background: var(--panel);
  }
  .seg label:has(input:checked) { border-color: var(--ink); background: var(--raised); }
  .seg input { accent-color: var(--ink); margin: 0; outline: none; }
  .seg label:has(input:focus-visible) { outline: 2px solid var(--ink); outline-offset: 2px; }
  .seg span { display: flex; flex-direction: column; line-height: 1.3; font-weight: 600; }
  .seg small { font-weight: 400; color: var(--muted); font-size: 12px; }
  .soon {
    display: flex; flex-direction: column; gap: 3px; margin: 12px 0 4px; padding: 10px 12px;
    border: 1px dashed var(--line); border-radius: 9px; color: var(--muted);
  }
  .soon b { color: var(--ink); font-weight: 600; }
  #set-keyfields[hidden], .soon[hidden] { display: none; }

  /* --- the chat's context line: profile and allowed sites --- */
  #context {
    display: flex; align-items: center; gap: 6px; padding: 4px 10px;
    border-bottom: 1px solid var(--line); font-size: 12px; min-height: 30px;
  }
  #context-btn { display: flex; align-items: center; gap: 7px; padding: 2px 6px; font-weight: 500; font-size: 12px; color: var(--muted); }
  #context[hidden] { display: none; }
  #screen:not([src]) { visibility: hidden; }
  #context-btn:hover { color: var(--ink); }
  #live-btn { display: flex; align-items: center; gap: 6px; font-weight: 600; font-size: 12.5px; padding: 4px 9px; }
  #live-btn.on { background: var(--ink); color: var(--panel); }
  .live-glyph { font-size: 14px; line-height: 1; }
  .live-count {
    min-width: 17px; height: 17px; padding: 0 5px; border-radius: 999px; font-size: 11px;
    display: inline-grid; place-items: center; background: var(--live); color: #fff;
  }
  #live { position: absolute; inset: 0; background: var(--bg); padding: 12px; overflow: hidden; }
  #live[hidden] { display: none; }
  #live-grid { display: grid; gap: 12px; justify-content: center; align-content: center; height: calc(100% - 40px); margin-top: 40px; }
  .live-tile {
    display: flex; flex-direction: column; background: var(--panel); border: 1px solid var(--line);
    border-radius: 10px; overflow: hidden; cursor: pointer; min-width: 0;
  }
  .live-tile:hover { border-color: var(--ink); }
  .live-tile.working { border-color: var(--live); box-shadow: 0 0 0 1px var(--live); }
  .live-tile .shot { position: relative; background: var(--raised); overflow: hidden; }
  .live-tile .shot img { width: 100%; height: 100%; object-fit: contain; display: block; }
  .live-tile .shot img:not([src]) { visibility: hidden; }
  .live-tile .shot .wait {
    position: absolute; inset: 0; display: grid; place-items: center; color: var(--muted); font-size: 12px;
  }
  .live-tile .bar { display: flex; flex-direction: column; gap: 2px; padding: 7px 10px 8px; font-size: 12px; min-width: 0; }
  .live-tile .row1, .live-tile .row2 { display: flex; align-items: center; gap: 7px; min-width: 0; }
  .live-tile .name { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
  .live-tile .chip { font-size: 11px; color: var(--muted); border: 1px solid var(--line); border-radius: 999px; padding: 0 7px; white-space: nowrap; }
  .live-tile .step { color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
  .live-tile .meta { color: var(--muted); white-space: nowrap; font-variant-numeric: tabular-nums; }
  .live-tile .stop { font-size: 11px; padding: 1px 8px; }
  #connect-btn { position: absolute; top: 12px; right: 14px; z-index: 2; font-size: 12.5px; background: var(--panel); border: 1px solid var(--line); }
  #connect-list { display: flex; flex-direction: column; gap: 6px; margin-top: 12px; }
  .connect-row {
    display: flex; align-items: center; gap: 10px; padding: 9px 11px;
    border: 1px solid var(--line); border-radius: 9px; background: var(--panel);
  }
  .connect-row .who { flex: 1; min-width: 0; }
  .connect-row .who b { display: block; }
  .connect-row .who small { color: var(--muted); display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .connect-row.absent { opacity: .55; }
  .connect-row button { font-size: 12px; }
  #live-empty {
    position: absolute; inset: 0; display: flex; flex-direction: column; gap: 4px;
    align-items: center; justify-content: center; color: var(--muted); text-align: center;
  }
  #live-empty[hidden] { display: none; }
  #live-empty b { color: var(--ink); font-weight: 600; }
  #nav .sep { width: 1px; align-self: stretch; margin: 4px 2px; background: var(--line); }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--line); flex: none; }
  .dot.on { background: var(--live); }
  .dot.busy { background: var(--live); animation: pulse 1.2s ease-in-out infinite; }
  @keyframes pulse { 50% { opacity: .35; } }
  .pill {
    font-size: 12px; padding: 2px 9px; border-radius: 999px; border: 1px solid var(--line);
    color: var(--muted); cursor: pointer; background: transparent;
  }
  .pill.warn { color: var(--bad); border-color: var(--bad); }

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
  .chat-menu { left: auto; right: 0; top: calc(100% + 6px); width: 280px; }
  /* New chat: one bordered card above the message box. Rows read label → value. */
  .creator { margin-top: auto; display: flex; flex-direction: column; gap: 10px; }
  .card {
    border: 1px solid var(--line); border-radius: 12px; background: var(--panel);
    box-shadow: 0 1px 2px rgba(0,0,0,.04);
  }
  .card-head { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-bottom: 1px solid var(--line); }
  .card-head .glyph {
    width: 28px; height: 28px; border-radius: 8px; display: grid; place-items: center; flex: none;
    background: var(--raised); font-size: 14px;
  }
  .card-head b { display: block; font-size: 13.5px; }
  .card-head small { display: block; color: var(--muted); font-size: 12px; line-height: 1.35; }
  .card-row {
    display: grid; grid-template-columns: 96px 1fr; align-items: center; gap: 10px;
    padding: 8px 12px; border-bottom: 1px solid var(--line); min-height: 42px;
  }
  .card-row:last-child { border-bottom: none; }
  .card-row > .k { color: var(--muted); font-size: 12.5px; }
  .card-row > .v { display: flex; align-items: center; gap: 6px; min-width: 0; flex-wrap: wrap; }
  .card-row .v > * { min-width: 0; }
  .card-row .v .dd, .card-row .v select { flex: 1 1 140px; }
  .card-row input[type=text] { flex: 1 1 120px; padding: 5px 8px; }
  .card-row.stack { align-items: start; }
  .card-row.stack > .k { padding-top: 6px; }
  .summary-btn {
    flex: 1; display: flex; align-items: center; gap: 8px; text-align: left;
    padding: 5px 9px; background: transparent;
  }
  .summary-btn .what { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .summary-btn .edit { color: var(--muted); font-size: 12px; }
  .rules-edit { display: flex; flex-direction: column; gap: 5px; width: 100%; }
  .rules-edit textarea {
    width: 100%; min-height: 64px; resize: vertical; padding: 6px 8px;
    font: 12px/1.5 ui-monospace, "Cascadia Mono", Consolas, monospace;
  }
  .rules-edit small { color: var(--muted); font-size: 11.5px; line-height: 1.4; }
  .toggles { display: flex; gap: 16px; flex-wrap: wrap; }
  .tgl { display: inline-flex; align-items: center; gap: 7px; cursor: pointer; font-size: 12.5px; user-select: none; }
  .tgl input {
    appearance: none; -webkit-appearance: none; margin: 0; width: 28px; height: 16px; border-radius: 999px;
    background: var(--line); position: relative; cursor: pointer; transition: background .15s; flex: none;
  }
  .tgl input::after {
    content: ""; position: absolute; top: 2px; left: 2px; width: 12px; height: 12px; border-radius: 50%;
    background: var(--panel); box-shadow: 0 1px 2px rgba(0,0,0,.25); transition: transform .15s;
  }
  .tgl input:checked { background: var(--live); }
  .tgl input:checked::after { transform: translateX(12px); }
  .tgl input:focus-visible { outline: 2px solid var(--live); outline-offset: 2px; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .chips button {
    font-size: 12px; padding: 4px 10px; border-radius: 999px; color: var(--muted);
    max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .chips button:hover { color: var(--ink); }
  @media (prefers-reduced-motion: reduce) { .tgl input, .tgl input::after { transition: none; } }
  .files-menu { left: auto; right: 0; top: calc(100% + 6px); width: 320px; }
  .menu-empty { color: var(--muted); font-size: 12px; padding: 4px 8px 8px; }

  #splitter { width: 5px; cursor: col-resize; background: var(--line); flex: none; }
  #splitter:hover { background: var(--muted); }
  #chat { width: 420px; min-width: 300px; max-width: 70vw; display: flex; flex-direction: column; background: var(--panel); }
  #main.chat-hidden #chat, #main.chat-hidden #splitter { display: none; }
  #chathead { display: flex; gap: 6px; padding: 8px 10px; border-bottom: 1px solid var(--line); align-items: center; }
  /* dropdowns: a button and a menu drawn like the rest, over a hidden select */
  .dd { position: relative; min-width: 0; display: flex; }
  .dd-btn {
    display: flex; align-items: center; gap: 6px; width: 100%; min-width: 0; text-align: left;
  }
  .dd-label { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .dd-chev { color: var(--muted); font-size: 11px; flex: none; }
  .dd-menu {
    position: absolute; top: calc(100% + 4px); left: 0; min-width: 100%; max-width: min(420px, 90vw);
    max-height: 320px; overflow: auto; z-index: 30; background: var(--panel); border: 1px solid var(--line);
    border-radius: 10px; box-shadow: var(--shadow); padding: 5px;
  }
  .dd.up .dd-menu { top: auto; bottom: calc(100% + 4px); }
  .dd.right .dd-menu { left: auto; right: 0; }
  .dd-opt {
    display: flex; align-items: center; gap: 6px; width: 100%; text-align: left; border: none;
    background: transparent; padding: 7px 9px; border-radius: 7px; white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis;
  }
  .dd-opt:hover, .dd-opt:focus-visible { background: var(--raised); outline: none; }
  .dd-opt.on { font-weight: 600; }
  .dd-group {
    padding: 8px 10px 3px; margin-top: 4px; font-size: 11.5px; color: var(--muted);
    border-top: 1px solid var(--line);
  }
  .dd-group:first-child { border-top: none; margin-top: 0; padding-top: 4px; }
  #archive-btn { font-size: 12px; color: var(--muted); padding: 4px 8px; white-space: nowrap; }
  #archive-btn:hover { color: var(--ink); }
  #archive-btn[hidden] { display: none; }
  .archive-menu { left: auto; right: 0; top: calc(100% + 6px); width: 320px; max-height: 60vh; }
  .archive-menu .row .grow { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .dd-tick { width: 14px; flex: none; color: var(--live); }
  .dd.quiet .dd-btn { border-color: transparent; background: transparent; }
  .dd.quiet .dd-btn:hover, .dd.quiet .dd-btn[aria-expanded="true"] { background: var(--raised); }
  #chathead .dd { flex: 1; }
  #chathead .dd-btn { font-weight: 600; }
  #composer .dd { flex: 1; }
  #composer .dd-btn { font-size: 12px; color: var(--muted); }

  #messages { flex: 1; overflow-y: auto; padding: 14px 14px 6px; display: flex; flex-direction: column; gap: 10px; }
  .msg { padding: 8px 12px; border-radius: 12px; white-space: pre-wrap; word-wrap: break-word; max-width: 92%; }
  .msg.user { background: var(--user); color: var(--user-ink); align-self: flex-end; border-bottom-right-radius: 4px; }
  .msg.assistant { background: var(--raised); border-bottom-left-radius: 4px; }
  .msg.notice { color: var(--muted); font-size: 12px; background: none; padding: 0 2px; }
  .plan-card { border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; background: var(--panel); display: flex; flex-direction: column; gap: 8px; }
  .plan-card .plan-head { font-weight: 600; }
  .plan-card .plan-summary { margin: 0; color: var(--muted); }
  .plan-card ol { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 5px; }
  .plan-card li span { display: block; color: var(--muted); font-size: 12.5px; }
  .plan-card .plan-actions { display: flex; gap: 6px; }
  .plan-card.answered .plan-actions { display: none; }
  .msg.steer .steer-note { display: block; margin-top: 3px; font-size: 11px; opacity: .7; }
  .msg.steer.queued { opacity: .75; border: 1px dashed currentColor; }
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
  dialog.wide { width: 92vw; height: 88vh; max-width: none; padding: 14px 16px; display: none; flex-direction: column; }
  dialog.wide[open] { display: flex; }
  .log-head { display: flex; align-items: center; margin-bottom: 10px; }
  .log-head h2 { margin: 0; }
  #log-frame { flex: 1; width: 100%; border: 1px solid var(--line); border-radius: 8px; background: var(--bg); }
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
<div id="main" class="dock-right">
  <section id="browser" aria-label="Browser">
    <div id="tabs"></div>
    <div id="nav">
      <button class="ghost" id="live-btn" title="Agents: every agent's page, working side by side">
        <span class="live-glyph" aria-hidden="true">▦</span><span>Agents</span><span class="live-count" id="live-count" hidden></span>
      </button>
      <span class="sep" aria-hidden="true"></span>
      <button class="icon ghost" id="back" title="Back">←</button>
      <button class="icon ghost" id="fwd" title="Forward">→</button>
      <button class="icon ghost" id="reload" title="Reload">⟳</button>
      <input id="url" placeholder="Type an address and press Enter (Ctrl+L)" spellcheck="false" aria-label="Address">
      <button class="icon ghost" id="newtab" title="New tab">＋</button>
      <span style="position:relative">
        <button class="icon ghost" id="files-btn" title="Files: what the AI may upload, and what was downloaded">📁</button>
        <div class="menu files-menu" id="files-menu" hidden></div>
      </span>
      <button class="icon ghost" id="restart" title="Restart this browser. It starts and recovers on its own; use this if a page is stuck.">⏻</button>
      <span class="sep" aria-hidden="true"></span>
      <button class="icon ghost" id="theme" title="Theme: follows your system. Click to switch."></button>
      <button class="icon ghost" id="dock" title="Move the chat to the other side">⇆</button>
      <button class="icon ghost" id="toggle-chat" title="Hide the chat (Ctrl+B)">⇥</button>
    </div>
    <div id="view">
      <img id="screen" tabindex="0" alt="The live browser page. Click and type here to use it yourself." draggable="false">
      <div id="viewmsg">Starting the browser…</div>
      <div id="activity" hidden><span class="dot busy"></span><span class="text" id="activity-text"></span></div>
      <div id="live" hidden>
        <button class="ghost" id="connect-btn" title="Let Claude Code, Codex, Cursor and others use ABT, each in a session of its own">＋ Connect an agent</button>
        <div id="live-grid"></div>
        <div id="live-empty" hidden><b>No agents are working right now.</b><span>Their pages show up here, side by side, while they work. Connect Claude Code, Codex or another agent with the button above.</span></div>
      </div>
    </div>
  </section>
  <div id="splitter" title="Drag to resize"></div>
  <aside id="chat" aria-label="Chat">
    <div id="chathead">
      <select id="convpick" title="Your chats. Each has its own browser, logins and rules."></select>
      <button id="chat-new" title="Start a new chat (Ctrl+N)">＋ New chat</button>
      <span style="position:relative">
        <button class="ghost" id="archive-btn" hidden title="Archived chats">Archived</button>
        <div class="menu archive-menu" id="archive-menu" hidden></div>
      </span>
      <span style="position:relative">
        <button class="icon ghost" id="chat-menu-btn" title="More for this chat">⋯</button>
        <div class="menu chat-menu" id="chat-menu" hidden>
          <button class="row" data-action="settings"><span class="grow">Chat settings</span><span class="meta">logins, sites, scripts</span></button>
          <button class="row" data-action="log"><span class="grow">Activity log</span><span class="meta">every step, with screenshots</span></button>
          <hr>
          <button class="row" data-action="delete"><span class="grow">Delete chat</span></button>
        </div>
      </span>
    </div>
    <div id="context" hidden>
      <button class="ghost" id="context-btn" title="This chat's browser: whose logins it uses. Click to change its settings.">
        <span class="dot" id="session-dot"></span>
        <span id="context-text">New chat</span>
      </button>
      <button class="pill" id="rules-pill" hidden title="This chat can only reach some sites. Click to change."></button>
    </div>
    <div id="messages"></div>
    <div id="composer">
      <textarea id="prompt" rows="1" placeholder="Tell the browser what to do…" aria-label="Message"></textarea>
      <div class="row">
        <select id="model" title="Model for this message"></select>
        <button class="icon ghost" id="model-btn" title="Model settings: your API key, the endpoint and the model list">⚙</button>
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
  <p class="lead">The AI that reads the page and decides what to do.</p>
  <div class="seg" role="radiogroup" aria-label="How to connect">
    <label><input type="radio" name="set-auth" value="oauth"><span>Sign in<small>OAuth</small></span></label>
    <label><input type="radio" name="set-auth" value="key" checked><span>OpenRouter<small>personal API key</small></span></label>
  </div>
  <div id="set-oauth" class="soon" hidden>
    <b>Sign-in isn't available yet.</b>
    <span>Use an OpenRouter API key for now. It's free to create at openrouter.ai/keys.</span>
  </div>
  <div id="set-keyfields">
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
  </div>
  <div class="actions">
    <span class="spacer"></span>
    <button data-close>Cancel</button>
    <button id="set-save" class="primary">Save</button>
  </div>
</dialog>

<dialog id="dlg-connect">
  <h2>Connect an agent</h2>
  <p class="lead">One tap gives an agent its own session — its own tabs, rules and log — and sets it up to use ABT. It works alongside every other agent and shows up here in Agents.</p>
  <label class="field"><span>Profile / logins for new connections</span>
    <select id="connect-profile"></select></label>
  <div id="connect-list"></div>
  <p class="hint" style="margin-top:10px">Restart the agent after connecting so it picks ABT up. Only an entry named <code>abt</code> is added to its settings; a backup of the file is kept beside it.</p>
  <div class="actions"><span class="spacer"></span><button data-close>Done</button></div>
</dialog>

<dialog id="dlg-session">
  <h2 id="ses-title">Chat settings</h2>
  <p class="lead" id="ses-lead">A session is a browser the AI works in, with its own tabs and chats.</p>
  <label class="field" id="ses-name-row"><span>Name</span>
    <input type="text" id="ses-name" placeholder="e.g. research" spellcheck="false">
    <span class="hint">Lowercase letters, numbers and dashes.</span></label>
  <label class="field"><span>Profile / logins</span>
    <span style="display:flex; gap:6px">
      <select id="ses-profile" style="flex:1"></select>
      <button class="icon" id="ses-profile-del" type="button" title="Delete this profile and its logins (only if no session uses it)">🗑</button>
    </span>
    <span class="hint">A profile keeps logins and cookies. Chats on the same profile share them.</span></label>
  <label class="field" id="ses-newprofile-row" hidden><span>New profile name</span>
    <input type="text" id="ses-newprofile" placeholder="e.g. work" spellcheck="false"></label>
  <label class="field"><span>Allowed sites</span>
    <textarea id="ses-rules" spellcheck="false" placeholder="all&#10;app.example.com/admin&#10;!app.example.com/api"></textarea>
    <span class="hint">One per line. <code>all</code> allows every site; a site or page allows just that; <code>!</code> blocks one. Only what is listed works: an empty list blocks every site.</span></label>
  <details class="more"><summary>More</summary>
    <label class="check"><input type="checkbox" id="ses-runjs" checked><span>Let the AI run scripts on the page<small>Scripts still cannot reach blocked sites.</small></span></label>
    <label class="check"><input type="checkbox" id="ses-strict"><span>Also check images, styles and scripts against the site list<small>Stricter, but pages that load from other sites may break.</small></span></label>
    <label class="check"><input type="checkbox" id="ses-agentic"><span>Can start helper agents<small>Plans the work, asks you first, then runs up to 5 helpers in parallel and gathers their reports.</small></span></label>
    <label class="check" id="ses-sealed-row"><input type="checkbox" id="ses-sealed" checked><span>Only this app can use it<small>Other programs and agents on this computer cannot drive it.</small></span></label>
  </details>
  <div class="actions">
    <button id="ses-del" hidden>Delete session</button>
    <span class="spacer"></span>
    <button data-close>Cancel</button>
    <button id="ses-save" class="primary">Create session</button>
  </div>
</dialog>

<dialog id="dlg-log" class="wide">
  <div class="log-head"><h2 id="log-title">Activity log</h2><span class="spacer"></span><button data-close>Close</button></div>
  <iframe id="log-frame" title="Activity log"></iframe>
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
  starting: false, lastStart: {}, downloadsSeen: {}, follow: null, draft: false, convs: [], pendingSend: null,
  live: { on: false, rows: [], socks: {}, timer: null, aspect: 16 / 10 },
  draftSettings: { profile: "default", newProfile: "", rules: "all", runJs: true, strict: false, agentic: false, rulesOpen: false },
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
  if (!S.draft && !S.sessions.find(s => s.name === S.session)) S.session = "default";
  const current = S.sessions.find(s => s.name === S.session);
  S.profile = current ? current.profile : "default";
  drawSessionButton();
}

function drawSessionButton() {
  // The chat's context: whose logins its browser uses, and any site limits.
  $("#context").hidden = !S.session;
  if (!S.session) {
    $("#context-text").textContent = "New chat";
    $("#session-dot").className = "dot";
    $("#rules-pill").hidden = true;
    return;
  }
  const info = S.sessions.find(s => s.name === S.session) || { name: S.session, profile: S.profile };
  $("#context-text").textContent = `Profile: ${info.profile}` + (info.sealed ? " 🔒" : "");
  $("#session-dot").className = "dot" + (S.runningChats.size ? " busy" : S.running ? " on" : "");
  const st = info.settings || {};
  const rules = st.rules || S.rules || [];
  const listed = st.only_listed ? rules : (rules.some(r => !r.startsWith("!")) ? rules : ["all", ...rules]);
  const summary = rulesSummary(listed.join("\n"));
  const pill = $("#rules-pill");
  pill.hidden = summary === "All sites";
  pill.classList.toggle("warn", summary === "No sites");
  pill.textContent = summary;
  pill.title = "Allowed sites:\n" + (listed.join("\n") || "(none)") + "\n\nClick to change.";
}
$("#context-btn").onclick = () => { if (S.session) openSessionDialog(true); };
$("#rules-pill").onclick = () => openSessionDialog(true);

$("#chat-menu-btn").onclick = () => { if (S.session) $("#chat-menu").hidden = !$("#chat-menu").hidden; };
document.addEventListener("click", (e) => { if (!e.target.closest("#chat-menu, #chat-menu-btn")) $("#chat-menu").hidden = true; });
$("#chat-menu").onclick = (e) => {
  const row = e.target.closest(".row"); if (!row) return;
  $("#chat-menu").hidden = true;
  if (row.dataset.action === "settings") openSessionDialog(true);
  else if (row.dataset.action === "log") openLog();
  else if (row.dataset.action === "delete") deleteChat();
};

async function selectSession(name, chatId) {
  if (!name) return;
  S.draft = false;
  S.session = name; store.set("session", name);
  const info = S.sessions.find(s => s.name === name);
  S.profile = info ? info.profile : S.profile;
  S.rules = null; S.tab = null;
  drawSessionButton();
  closeScreen(); hideActivity();
  loadRules();
  // Chats first, then the socket: what it replays lands on the drawn chat.
  await refreshBrowser(); await loadChats(chatId); openChatSocket();
}

async function loadRules() {
  try {
    const name = S.session;
    const info = await api("GET", "/sessions/" + encodeURIComponent(name));
    const settings = info.settings || {};
    S.rules = settings.rules || []; drawSessionButton();
    // Chats made before sessions carried `headless` would open a window.
    if (name.startsWith("chat-") && settings.headless === undefined) {
      await api("PATCH", "/sessions/" + encodeURIComponent(name), { settings: { headless: true } });
    }
  }
  catch (e) {}
}

function openSessionDialog(edit) {
  const dlg = $("#dlg-session");
  $("#ses-title").textContent = "Chat settings";
  $("#ses-lead").textContent = "This chat's browser. Changes apply from the AI's next step.";
  $("#ses-name-row").hidden = edit;
  $("#ses-sealed-row").hidden = edit;
  $("#ses-save").textContent = edit ? "Save changes" : "Create session";
  $("#ses-del").hidden = true;
  const drawProfiles = (pick) => {
    $("#ses-profile").innerHTML = S.profiles.map(p =>
      `<option value="${esc(p.name)}"${p.name === pick ? " selected" : ""}>${esc(p.name)}</option>`).join("")
      + `<option value="__new__"${pick === "__new__" ? " selected" : ""}>New profile — fresh logins</option>`;
    $("#ses-newprofile-row").hidden = pick !== "__new__";
  };
  drawProfiles(edit ? S.profile : "__new__");
  $("#ses-newprofile").value = ""; $("#ses-name").value = "";
  $("#ses-rules").value = ""; $("#ses-strict").checked = false; $("#ses-runjs").checked = true; $("#ses-agentic").checked = false;
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
      // Before `only_listed`, an empty list meant any site: show that as `all`.
      const rules = st.rules || [];
      $("#ses-rules").value = (st.only_listed || rules.some(r => !r.startsWith("!")) ? rules : ["all", ...rules]).join("\n");
      $("#ses-strict").checked = !!st.strict;
      $("#ses-agentic").checked = !!st.agentic;
      // A helper cannot start helpers of its own.
      $("#ses-agentic").closest("label").hidden = !!st.role;
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
      only_listed: true,
      strict: $("#ses-strict").checked, run_js: $("#ses-runjs").checked, agentic: $("#ses-agentic").checked,
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
  if (!S.session || S.live.on) return;
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
  // Read from Chrome's own page list: never queues behind an agent's command.
  try { S.tabs = await api("GET", "/app/tabs"); } catch (e) { S.tabs = []; }
  if (!S.tabs.length && !S.runningChats.size) {
    // No tab at all: either the session let its last one go, or the browser
    // died. Ask the session, which knows the difference.
    try { await run({ op: "tab_list" }); }
    catch (e) { if (e.type === "browser_dead") return ensureBrowser("browser_restart"); }
  }
  if (S.follow) {
    // The agent just opened or switched a tab: show that one.
    const wanted = S.follow === "newest" ? S.tabs[S.tabs.length - 1] : S.tabs.find(t => t.tab_id === S.follow);
    if (wanted) S.tab = wanted.tab_id;
    S.follow = null;
  }
  if (!S.tab || !S.tabs.find(t => t.tab_id === S.tab)) S.tab = S.tabs.length ? S.tabs[0].tab_id : null;
  const shown = S.tabs.find(t => t.tab_id === S.tab);
  if (shown && document.activeElement !== $("#url")) $("#url").value = shown.url === "about:blank" ? "" : (shown.url || "");
  drawTabs();
  if (S.tab) openScreen(S.tab);
  // Listing downloads makes one call through the session's connection;
  // leave it until the agent is not mid-command.
  if (!S.runningChats.size) checkDownloads();
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

// Looking at a tab is instant: it only changes what the live view shows. The
// session's own current tab -- where the agent's next click lands -- moves
// with it only while no agent is working, so watching never redirects one.
$("#tabs").onclick = (e) => {
  const el = e.target.closest(".tab"); if (!el) return;
  S.tab = el.dataset.tab;
  const shown = S.tabs.find(t => t.tab_id === S.tab);
  $("#url").value = shown && shown.url !== "about:blank" ? shown.url : "";
  drawTabs(); openScreen(S.tab);
  if (!S.runningChats.size) run({ op: "tab_switch", tab_id: S.tab }).catch(() => {});
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
    if (/holding the profile/.test(e.message || "")) { S.starting = false; return offerForceClose(session, op); }
    if (!/already running/.test(e.message || "")) { S.starting = false; viewMessage(e.message, "Try again", () => { S.lastStart[session] = 0; ensureBrowser(op); }); return; }
  }
  S.starting = false;
  if (S.session === session) { await loadAll(); await refreshBrowser(); }
}

// Another browser holds this chat's profile: usually a Chrome window someone
// opened on it. Closing it is the person's call, so it is a button.
function offerForceClose(session, op) {
  const info = S.sessions.find(x => x.name === session) || {};
  const profile = info.profile || S.profile || "default";
  viewMessage(`Another browser is using the “${profile}” profile, so this one can't start. Close that Chrome window, or force it closed here (anything unsaved in it is lost).`,
    "Force close the browser", async () => {
      viewMessage("Closing it…");
      try {
        const out = await api("POST", `/profiles/${encodeURIComponent(profile)}/force-close`, undefined, { operator: true, session: null });
        toast(out.closed ? "Closed the browser holding the profile" : "Nothing was holding it any more");
      } catch (e) { fail(e); }
      S.lastStart[session] = 0; ensureBrowser(op);
    });
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

// --- Agents: every agent's page, side by side --------------------------------------
//
// Cheap by design: the list is read lock-free, streams run only while the grid
// is open, each is sized to its tile, Chrome sends a frame only when a page
// changes, and the main view's stream is closed meanwhile.

const LIVE_MAX_STREAMS = 9;

const LIVE_WORDS = {
  goto: "Opening a page", click: "Clicking", input: "Typing", press: "Pressing a key", select: "Choosing",
  get_text: "Reading the page", find: "Looking for something", find_full: "Looking for something",
  scroll: "Scrolling", wait_for: "Waiting for the page", back: "Going back", forward: "Going forward",
  reload: "Reloading", tab_new: "Opening a tab", tab_switch: "Switching tab", tab_close: "Closing a tab",
  screenshot: "Taking a screenshot", run_js: "Running a script", hover: "Hovering", save_file: "Saving a document",
  files: "Checking files", browser_start: "Starting the browser", browser_restart: "Restarting the browser",
  status: "Checking the browser", tab_list: "Checking tabs",
};

function liveDuration(seconds) {
  seconds = Math.max(0, Math.round(seconds));
  const m = Math.floor(seconds / 60), s = seconds % 60;
  return m ? `${m}m ${String(s).padStart(2, "0")}s` : `${s}s`;
}

async function toggleLive(on) {
  S.live.on = on === undefined ? !S.live.on : on;
  $("#live-btn").classList.toggle("on", S.live.on);
  $("#live").hidden = !S.live.on;
  if (S.live.on) {
    closeScreen();
    await loadLive();
    clearInterval(S.live.timer);
    S.live.timer = setInterval(() => { if (!document.hidden) loadLive(); }, 2000);
  } else {
    clearInterval(S.live.timer); S.live.timer = null;
    for (const key of Object.keys(S.live.socks)) closeLiveStream(key);
    refreshBrowser();
  }
}
$("#live-btn").onclick = () => toggleLive();

async function loadLive() {
  let data;
  try { data = await api("GET", "/app/live", undefined, { operator: true, session: null }); }
  catch (e) { return; }
  const working = data.sessions.filter(r => r.working).length;
  $("#live-count").hidden = !working; $("#live-count").textContent = working;
  if (!S.live.on) return;
  // Working first, then most recent; tiles only for pages there is a tab for.
  S.live.rows = data.sessions.filter(r => r.browser && r.tab).slice(0, LIVE_MAX_STREAMS);
  S.live.now = data.now;
  drawLive();
}

function liveKey(r) { return `${r.session}|${r.tab}`; }

function layoutLive(n) {
  // Fixed shapes, the way people expect them: 1 full, 2 side by side, 3-4 as
  // 2x2, 5-6 as 3x2, 7-9 as 3x3. Tiles are then sized to fit, keeping the
  // page's own shape.
  const cols = n <= 1 ? 1 : n === 2 ? 2 : Math.ceil(Math.sqrt(n));
  const rows = Math.ceil(n / cols);
  const box = $("#live"), gap = 12, bar = 50, top = 40;  // `top` leaves room for Connect
  const W = box.clientWidth - 24, H = box.clientHeight - 24 - top, a = S.live.aspect;
  const cellW = (W - gap * (cols - 1)) / cols;
  const cellH = (H - gap * (rows - 1)) / rows - bar;
  const w = Math.min(cellW, cellH * a);
  return { cols, w: Math.max(120, Math.floor(w)), h: Math.max(75, Math.floor(w / a)) };
}

function drawLive() {
  const rows = S.live.rows, grid = $("#live-grid");
  $("#live-empty").hidden = rows.length > 0;
  const keep = new Set(rows.map(liveKey));
  for (const key of Object.keys(S.live.socks)) if (!keep.has(key)) closeLiveStream(key);
  if (!rows.length) { grid.innerHTML = ""; return; }
  const { cols, w, h } = layoutLive(rows.length);
  grid.style.gridTemplateColumns = `repeat(${cols}, ${w}px)`;
  // Reuse tiles by key, so a stream's picture never blinks on a refresh.
  const existing = new Map([...grid.children].map(el => [el.dataset.key, el]));
  grid.innerHTML = "";
  for (const r of rows) {
    const key = liveKey(r);
    let tile = existing.get(key);
    if (!tile) {
      tile = document.createElement("div");
      tile.className = "live-tile"; tile.dataset.key = key;
      tile.innerHTML = `<div class="shot"><img alt=""><div class="wait">Connecting…</div></div><div class="bar"></div>`;
      tile.onclick = (e) => { if (!e.target.closest(".stop")) openFromLive(r.session, r.tab); };
    }
    tile.classList.toggle("working", r.working);
    tile.querySelector(".shot").style.height = h + "px";
    const step = r.working ? (LIVE_WORDS[r.op] || (r.op || "Working").replace(/_/g, " ")) + "…" :
      (r.page_title || r.url || "Idle");
    const time = r.since ? liveDuration((r.working ? S.live.now : r.at) - r.since) : "";
    tile.querySelector(".bar").innerHTML =
      `<div class="row1">${r.working ? '<span class="dot busy"></span>' : '<span class="dot on"></span>'}` +
      `<span class="name" title="${esc(r.title)}">${r.role ? "<i>" + esc(r.role) + "</i> · " : ""}${esc(r.title)}</span>` +
      `<span class="chip" title="Profile / logins">${esc(r.profile)}</span>` +
      (r.chat_running && r.chat_running.length ? `<button class="stop ghost" title="Stop this chat's reply">Stop</button>` : "") +
      `</div><div class="row2"><span class="step" title="${esc(r.url || "")}">${esc(step)}</span>` +
      `<span class="meta">${r.steps ? r.steps + " steps" : ""}${time ? " · " + time : ""}</span></div>`;
    const stop = tile.querySelector(".stop");
    if (stop) stop.onclick = async () => {
      try { await api("POST", `/app/live/${encodeURIComponent(r.session)}/stop`, undefined, { operator: true, session: null }); toast("Stopped"); }
      catch (e) { fail(e); }
    };
    grid.appendChild(tile);
    openLiveStream(key, r, tile, w);
  }
}

async function openLiveStream(key, r, tile, width) {
  const have = S.live.socks[key];
  if (have && have.readyState <= 1) return;
  const op = await operatorToken();
  const px = Math.min(960, Math.round(width * (window.devicePixelRatio || 1)));
  const q = new URLSearchParams({ tab: r.tab, session: r.session, token: op, view: "1", w: String(px), q: "45" });
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/screencast?${q}`);
  S.live.socks[key] = ws;
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.type !== "frame") return;
    const img = tile.querySelector("img");
    img.src = "data:image/jpeg;base64," + m.data;
    tile.querySelector(".wait").hidden = true;
    const md = m.metadata || {};
    if (md.deviceWidth && md.deviceHeight) {
      const a = md.deviceWidth / md.deviceHeight;
      if (Math.abs(a - S.live.aspect) > 0.05) { S.live.aspect = a; drawLive(); }
    }
  };
  ws.onclose = () => { if (S.live.socks[key] === ws) delete S.live.socks[key]; };
}

function closeLiveStream(key) {
  const ws = S.live.socks[key];
  delete S.live.socks[key];
  if (ws) { try { ws.close(); } catch (e) {} }
}

async function openConnect() {
  const dlg = $("#dlg-connect");
  $("#connect-profile").innerHTML = S.profiles.map(p => `<option value="${esc(p.name)}">${esc(p.name)}</option>`).join("");
  await drawConnect();
  dlg.showModal();
}
async function drawConnect() {
  let rows;
  try { rows = await api("GET", "/app/connect", undefined, { operator: true, session: null }); }
  catch (e) { return fail(e); }
  rows.sort((a, b) => (b.installed - a.installed) || a.name.localeCompare(b.name));
  $("#connect-list").innerHTML = rows.map(r => {
    const state = r.session ? `Connected — session “${esc(r.session)}”` : r.installed ? "Not connected" : "Not found on this computer";
    const action = r.session ? `<button data-off="${esc(r.id)}">Disconnect</button>` :
      `<button class="primary" data-on="${esc(r.id)}"${r.installed ? "" : " disabled"}>Connect</button>`;
    return `<div class="connect-row${r.installed || r.session ? "" : " absent"}"><span class="who"><b>${esc(r.name)}</b>` +
      `<small title="${esc(r.config)}">${state}</small></span>${action}</div>`;
  }).join("");
  document.querySelectorAll("[data-on]").forEach(b => b.onclick = async () => {
    b.disabled = true;
    try {
      const out = await api("POST", `/app/connect/${encodeURIComponent(b.dataset.on)}`, { profile: $("#connect-profile").value }, { operator: true, session: null });
      toast(`${out.name} connected. Restart it to start using ABT.`);
      await loadAll();
    } catch (e) { fail(e); }
    drawConnect();
  });
  document.querySelectorAll("[data-off]").forEach(b => b.onclick = async () => {
    b.disabled = true;
    try { const out = await api("DELETE", `/app/connect/${encodeURIComponent(b.dataset.off)}`, undefined, { operator: true, session: null }); toast(`${out.name} disconnected`); }
    catch (e) { fail(e); }
    drawConnect();
  });
}
$("#connect-btn").onclick = openConnect;

async function openFromLive(session, tab) {
  await toggleLive(false);
  if (session !== S.session) await selectSession(session);
  S.tab = tab; S.follow = null;
  openScreen(tab);
}
window.addEventListener("resize", () => { if (S.live.on && S.live.rows.length) drawLive(); });

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
    } else if (m.type === "file_chooser") {
      toast("File pickers don't open here. Put the file in this profile's uploads folder (📁) and ask the AI to upload it.");
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
  // Ctrl+V is left alone so the browser raises "paste" -- see the handler.
  if ((e.ctrlKey || e.metaKey) && ["b", "l", "v"].includes(e.key.toLowerCase())) return;
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
  if (k === "n") { e.preventDefault(); enterDraft(); }
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

  if (!S.chat || !(S.chat.messages || []).length) drawHistory();
}

$("#model-btn").onclick = openModelDialog;
async function openModelDialog() {
  await loadModels();
  $("#set-endpoint").value = S.settings.endpoint || "https://openrouter.ai/api/v1";
  $("#set-key").value = "";
  $("#set-keyhint").textContent = S.settings.has_key ? `A key ending ${S.settings.key_hint} is saved.` : "No key saved yet.";
  $("#set-models").value = (S.settings.models || []).join("\n");
  document.querySelector('input[name="set-auth"][value="key"]').checked = true;
  drawAuth();
  $("#dlg-settings").showModal();
}
// Sign-in is a placeholder for now: choosing it explains, and saves nothing.
function drawAuth() {
  const oauth = document.querySelector('input[name="set-auth"]:checked').value === "oauth";
  $("#set-oauth").hidden = !oauth;
  $("#set-keyfields").hidden = oauth;
  $("#set-save").disabled = oauth;
}
document.querySelectorAll('input[name="set-auth"]').forEach(r => r.onchange = drawAuth);
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

// The session's log -- every command, its result, a screenshot per step --
// in the log viewer, inside the app so a sealed session's token stays here.
async function openLog() {
  const q = new URLSearchParams({ session: S.session });
  const token = await sessionToken(S.session);
  if (token) q.set("token", token);
  $("#log-title").textContent = `Activity log — ${S.session}`;
  $("#log-frame").src = "/viewer?" + q;
  $("#dlg-log").showModal();
}

// --- chats ------------------------------------------------------------------------------

async function loadChats(pick) {
  if (!S.session) return;
  let list = [];
  try { list = await api("GET", "/app/chats"); } catch (e) { fail(e); }
  if (!list.length) { const c = await api("POST", "/app/chats", { model: $("#model").value || null }); list = [c]; }
  const id = pick || (list.find(c => c.messages > 0) || list[0]).id;
  await openChat(id);
  loadConversations();
}
async function openChat(id) {
  try { S.chat = await api("GET", "/app/chats/" + encodeURIComponent(id)); } catch (e) { return fail(e); }
  store.set("chat." + S.session, id);
  drawModels(); drawHistory();
  for (const e of S.buffers[id] || []) renderEvent(e);
  setBusy(S.runningChats.has(id));
}

// The chat list: every conversation, whichever session it lives in. Picking
// one switches the browser to its session.
// The chat list, newest activity first, in three bands: what happened in the
// last half hour, the rest of the last day, and an archive for anything older.
// Any new message or step moves a chat back to the top, archived or not.
const RECENT_MS = 30 * 60 * 1000, ARCHIVE_MS = 24 * 60 * 60 * 1000;

function convAge(c) {
  const t = Date.parse(c.updated || "");
  return c.running ? 0 : (isNaN(t) ? Infinity : Date.now() - t);
}

function ago(c) {
  const ms = convAge(c);
  if (ms < 60e3) return "just now";
  const m = Math.round(ms / 60e3); if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60); if (h < 24) return `${h} h ago`;
  const d = Math.round(h / 24); if (d < 31) return d === 1 ? "yesterday" : `${d} days ago`;
  return new Date(Date.parse(c.updated)).toLocaleDateString();
}

async function loadConversations() {
  try { S.convs = await api("GET", "/app/overview", undefined, { operator: true, session: null }); }
  catch (e) { return; }
  const current = S.session && S.chat ? `${S.session}|${S.chat.id}` : "__draft__";
  const key = c => `${c.session}|${c.chat_id}`;
  const shown = S.convs
    .filter(c => c.messages > 0 || key(c) === current)
    .sort((a, b) => convAge(a) - convAge(b));
  const option = c => `<option value="${esc(key(c))}"${key(c) === current ? " selected" : ""}>` +
    `${c.lead ? "↳ " : ""}${c.running ? "● " : ""}${esc(c.title || "New chat")}${c.profile !== "default" ? " — " + esc(c.profile) : ""}</option>`;
  // A helper sits right under its lead, whatever its own last activity.
  const leads = new Map(shown.filter(c => !c.lead).map(c => [c.session, c]));
  const grouped = [];
  for (const c of shown.filter(c => !c.lead)) {
    grouped.push(c);
    grouped.push(...shown.filter(h => h.lead === c.session));
  }
  grouped.push(...shown.filter(h => h.lead && !leads.has(h.lead)));
  shown.splice(0, shown.length, ...grouped);
  const recent = shown.filter(c => convAge(c) <= RECENT_MS);
  const earlier = shown.filter(c => convAge(c) > RECENT_MS && convAge(c) <= ARCHIVE_MS);
  // The chat that is open stays in the list even once it is old.
  const reopened = shown.filter(c => convAge(c) > ARCHIVE_MS && key(c) === current);
  S.archived = shown.filter(c => convAge(c) > ARCHIVE_MS && key(c) !== current);

  const groups = [];
  if (S.draft) groups.push(`<option value="__draft__" selected>New chat</option>`);
  const band = (label, list) => { if (list.length) groups.push(`<optgroup label="${esc(label)}">${list.map(option).join("")}</optgroup>`); };
  band("Last 30 minutes", recent);
  band("Earlier today", earlier);
  band("From the archive", reopened);
  $("#convpick").innerHTML = groups.join("") || `<option value="__draft__">New chat</option>`;

  const btn = $("#archive-btn");
  btn.hidden = !S.archived.length;
  btn.textContent = `Archived · ${S.archived.length}`;
  btn.title = `Archived chats (${S.archived.length}): no activity for a day. Open one to carry on.`;
  if (!$("#archive-menu").hidden) drawArchive();
}

function drawArchive() {
  $("#archive-menu").innerHTML = `<h4>Archived · no activity for a day</h4>` + (S.archived || []).map(c =>
    `<button class="row" data-conv="${esc(c.session)}|${esc(c.chat_id)}" title="${esc(c.title || "New chat")}">` +
    `<span class="grow">${esc(c.title || "New chat")}</span><span class="meta">${esc(ago(c))}${c.profile !== "default" ? " · " + esc(c.profile) : ""}</span></button>`
  ).join("");
}
$("#archive-btn").onclick = () => {
  const menu = $("#archive-menu");
  if (menu.hidden) drawArchive();
  menu.hidden = !menu.hidden;
};
$("#archive-menu").onclick = (e) => {
  const row = e.target.closest("[data-conv]"); if (!row) return;
  $("#archive-menu").hidden = true;
  const [session, chatId] = row.dataset.conv.split("|");
  if (session === S.session) openChat(chatId).then(loadConversations);
  else selectSession(session, chatId);
};
document.addEventListener("click", (e) => { if (!e.target.closest("#archive-menu, #archive-btn")) $("#archive-menu").hidden = true; });
$("#convpick").onchange = (e) => {
  const value = e.target.value;
  if (value === "__draft__") return;
  const [session, chatId] = value.split("|");
  if (session === S.session) openChat(chatId).then(loadConversations);
  else selectSession(session, chatId);
};

// A new chat starts as a draft: the settings for its browser, then the first
// message. Sending it creates the chat's own sealed session and starts it.
function enterDraft() {
  S.draft = true; S.session = null; S.chat = null; S.tabs = []; S.tab = null;
  if (S.chatSock) { try { S.chatSock.close(); } catch (e) {} }
  S.chatSock = null; S.runningChats = new Set(); S.buffers = {};
  setBusy(false); closeScreen(); hideActivity(); drawTabs(); drawSessionButton();
  $("#url").value = "";
  viewMessage("This chat's browser opens here when you send the first message.");
  drawHistory(); loadConversations();
  $("#prompt").focus();
}
$("#chat-new").onclick = () => enterDraft();

function rulesSummary(text) {
  const rules = (text || "").split("\n").map(r => r.trim()).filter(Boolean);
  const allow = rules.filter(r => !r.startsWith("!")), block = rules.length - allow.length;
  if (!allow.length) return "No sites";
  const all = allow.some(r => ["all", "*"].includes(r.toLowerCase()));
  const head = all ? "All sites" : allow.length === 1 ? `Only ${allow[0]}` : `Only ${allow.length} sites`;
  return block ? `${head}, ${block} blocked` : head;
}

function drawCreator() {
  const d = S.draftSettings;
  const profiles = S.profiles.map(p => `<option value="${esc(p.name)}"${p.name === d.profile ? " selected" : ""}>${esc(p.name)}</option>`).join("");
  add(`<div class="creator">
    <div class="card" role="group" aria-label="New chat settings">
      <div class="card-head">
        <span class="glyph" aria-hidden="true">✦</span>
        <span><b>New chat</b><small>It gets its own browser. Set it up, then type what to do below. Change it later from ⋯.</small></span>
      </div>
      <div class="card-row">
        <span class="k" title="A profile keeps logins and cookies. Chats on the same profile share them.">Profile / logins</span>
        <span class="v">
          <select id="new-profile" aria-label="Profile / logins">${profiles}<option value="__new__"${d.profile === "__new__" ? " selected" : ""}>＋ New profile (signed out)</option></select>
          <input type="text" id="new-profile-name" placeholder="Name it, e.g. work" spellcheck="false" aria-label="New profile name" value="${esc(d.newProfile || "")}"${d.profile === "__new__" ? "" : " hidden"}>
        </span>
      </div>
      <div class="card-row stack">
        <span class="k" title="Where the AI may go. Only what is listed works.">Allowed sites</span>
        <span class="v">
          <button class="summary-btn" id="rules-toggle" aria-expanded="${d.rulesOpen ? "true" : "false"}"${d.rulesOpen ? " hidden" : ""}>
            <span class="what" id="rules-what">${esc(rulesSummary(d.rules))}</span><span class="edit">Edit…</span>
          </button>
          <span class="rules-edit" id="rules-edit"${d.rulesOpen ? "" : " hidden"}>
            <textarea id="new-rules" spellcheck="false" aria-label="Allowed sites" placeholder="all&#10;app.example.com/admin&#10;!app.example.com/api">${esc(d.rules || "")}</textarea>
            <small>One per line. <code>all</code> allows every site, a site or page allows just that, <code>!</code> blocks one. An empty list blocks every site.</small>
          </span>
        </span>
      </div>
      <div class="card-row">
        <span class="k">Allow</span>
        <span class="v toggles">
          <label class="tgl" title="Let the AI run its own JavaScript on pages. Off keeps it to clicks, typing and reading."><input type="checkbox" id="new-runjs"${d.runJs ? " checked" : ""}>Scripts</label>
          <label class="tgl" title="Also check images, styles and scripts the page loads against the site list, not just pages."><input type="checkbox" id="new-strict"${d.strict ? " checked" : ""}>Strict sites</label>
          <label class="tgl" title="Let this chat plan a task, then — after you approve — run up to 5 helper agents in parallel, each in its own role, and gather their reports."><input type="checkbox" id="new-agentic"${d.agentic ? " checked" : ""}>Helpers</label>
        </span>
      </div>
    </div>
    <div class="chips" aria-label="Examples">${EXAMPLES.map(t => `<button data-example="${esc(t)}" title="${esc(t)}">${esc(t)}</button>`).join("")}</div>
  </div>`);
  const keep = () => {
    d.profile = $("#new-profile").value; d.newProfile = $("#new-profile-name").value;
    d.rules = $("#new-rules").value; d.runJs = $("#new-runjs").checked; d.strict = $("#new-strict").checked;
    d.agentic = $("#new-agentic").checked;
    $("#new-profile-name").hidden = d.profile !== "__new__";
    $("#rules-what").textContent = rulesSummary(d.rules);
  };
  ["#new-profile", "#new-profile-name", "#new-rules", "#new-runjs", "#new-strict", "#new-agentic"].forEach(sel => {
    $(sel).addEventListener("input", keep); $(sel).addEventListener("change", keep);
  });
  $("#new-profile").addEventListener("change", () => { if (d.profile === "__new__") $("#new-profile-name").focus(); });
  $("#rules-toggle").onclick = () => {
    d.rulesOpen = true; $("#rules-toggle").hidden = true; $("#rules-edit").hidden = false; $("#new-rules").focus();
  };
  enhanceSelect($("#new-profile"));
  document.querySelectorAll("[data-example]").forEach(b => b.onclick = () => { $("#prompt").value = b.dataset.example; grow(); $("#prompt").focus(); });
}

async function createChatSession() {
  const d = S.draftSettings;
  const name = "chat-" + Math.random().toString(16).slice(2, 8);
  let profile = d.profile || "default";
  if (profile === "__new__") {
    profile = (d.newProfile || "").trim().toLowerCase() || name;
    if (!S.profiles.find(p => p.name === profile)) await api("POST", "/profiles", { name: profile }, { session: null });
  }
  const settings = {
    rules: (d.rules || "").split("\n").map(r => r.trim()).filter(Boolean),
    only_listed: true, run_js: !!d.runJs, strict: !!d.strict, agentic: !!d.agentic,
    // The app shows the page itself; its browsers need no window of their own.
    headless: true,
  };
  const out = await api("POST", "/sessions", { name, profile, sealed: true, settings }, { session: null });
  if (out.token) { S.tokens[name] = out.token; try { sessionStorage.setItem("abt.tok." + name, out.token); } catch (e) {} }
  await loadAll();
  return name;
}

async function deleteChat() {
  if (!S.session || !S.chat) return;
  // `default` holds chats from before each chat had its own session; for it,
  // only the conversation goes. Any other chat takes its session with it.
  const whole = S.session !== "default";
  const question = whole
    ? "Delete this chat? Its browser tabs close. Its activity log and files are kept aside."
    : "Delete this conversation?";
  if (!confirm(question)) return;
  try {
    if (whole) await api("DELETE", "/sessions/" + encodeURIComponent(S.session));
    else await api("DELETE", "/app/chats/" + encodeURIComponent(S.chat.id));
    toast("Chat deleted");
    await loadAll(); enterDraft();
  } catch (e) { fail(e); }
}

function add(html) { const m = $("#messages"); m.insertAdjacentHTML("beforeend", html); m.scrollTop = m.scrollHeight; }
function bubble(role, text) {
  if (role === "assistant") return add(`<div class="msg assistant md">${markdown(text)}</div>`);
  add(`<div class="msg ${role}">${esc(text)}</div>`);
}

// A tool call in words a person would use.
function describe(name, args) {
  if (name === "propose_plan") return `Proposed a plan: ${(args.workers || []).length} helpers`;
  if (name === "start_worker") return `Started a helper: ${args.role || ""}`;
  if (name === "workers") return "Checked on the helpers";
  if (name === "wait_for_workers") return "Waiting for the helpers";
  if (name === "read_report") return `Read ${args.worker || "a helper"}'s report`;
  if (name === "stop_worker") return `Stopped ${args.worker || "a helper"}`;
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
      case "save_file": return `Saved ${c.name ? "“" + c.name + "”" : "a document"} to downloads`;
      case "files": return "Checked the profile's files";
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
  if (S.draft) return drawCreator();
  const msgs = (S.chat && S.chat.messages) || [];
  const results = {};
  msgs.filter(m => m.role === "tool").forEach(m => results[m.tool_call_id] = m.content);
  for (const m of msgs) {
    if (m.role === "error" || m.role === "notice") bubble(m.role, m.content);
    else if (m.role === "user" && m.update) bubble("notice", m.content);  // from ABT, not the person
    else if (m.role === "user") bubble("user", m.content);
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
    ws.onopen = () => {
      // The first message of a chat made from a draft waits for this.
      if (S.pendingSend && S.chat) {
        const text = S.pendingSend; S.pendingSend = null;
        setBusy(true);
        ws.send(JSON.stringify({ type: "send", chat_id: S.chat.id, text, model: $("#model").value || null }));
      }
    };
    ws.onmessage = (ev) => onChatEvent(JSON.parse(ev.data));
    ws.onclose = () => { if (S.chatSock === ws) S.chatSock = null; };
  });
}

let pendingTool = null;
// The reply as it is being written: one bubble, re-rendered as pieces arrive,
// replaced by the finished message when it lands.
function liveText(piece) {
  // Its own id: `#live` is the Agents grid, and sharing it once wrote the
  // reply over the browser view and then deleted the grid with the bubble.
  let el = $("#reply-live");
  if (!el) { add(`<div class="msg assistant md" id="reply-live"></div>`); el = $("#reply-live"); el._text = ""; }
  el._text += piece; el.innerHTML = markdown(el._text);
  const m = $("#messages"); m.scrollTop = m.scrollHeight;
}
function endLive() { const el = $("#reply-live"); if (el) el.remove(); }
// The lead's plan, for the person to approve before any helper starts.
function planCard(args) {
  const workers = Array.isArray(args.workers) ? args.workers : [];
  const rows = workers.map((w, i) =>
    `<li><b>${esc(w.role || "Helper " + (i + 1))}</b><span>${esc(w.task || "")}</span></li>`).join("");
  add(`<div class="plan-card"><div class="plan-head">Plan — ${workers.length} helper${workers.length === 1 ? "" : "s"} in parallel</div>` +
    (args.summary ? `<p class="plan-summary">${esc(args.summary)}</p>` : "") +
    `<ol>${rows}</ol><div class="plan-actions"><button class="primary" data-plan="go">Start them</button>` +
    `<button data-plan="edit">Change it</button></div></div>`);
  const card = [...document.querySelectorAll(".plan-card")].pop();
  card.querySelector('[data-plan="go"]').onclick = () => { $("#prompt").value = "Go ahead with the plan."; grow(); send(); card.classList.add("answered"); };
  card.querySelector('[data-plan="edit"]').onclick = () => { $("#prompt").value = "Change the plan: "; grow(); $("#prompt").focus(); };
}

function renderEvent(e) {
  if (e.type === "delta") return liveText(e.text);
  if (e.type !== "delta") endLive();
  if (e.type === "user") bubble("user", e.text);
  else if (e.type === "assistant") bubble("assistant", e.text);
  else if (e.type === "tool_call" && e.name === "propose_plan") { pendingTool = e; planCard(e.args || {}); }
  else if (e.type === "tool_call") { pendingTool = e; }
  else if (e.type === "tool_result") {
    const args = pendingTool ? pendingTool.args : {};
    step(e.name, args, e.text, e.error); pendingTool = null;
    // Follow the agent between tabs, so the view shows what it is working on.
    const cmds = args.commands || [];
    const switched = [...cmds].reverse().find(c => c.op === "tab_switch" && c.tab_id);
    if (cmds.some(c => c.op === "tab_new")) S.follow = "newest";
    else if (switched) S.follow = switched.tab_id;
    if (S.follow) refreshBrowser();
  }
  else if (e.type === "steer" && e.update) {
    bubble("notice", e.text);  // from ABT (a helper finished), not from the person
  }
  else if (e.type === "steer") {
    add(`<div class="msg user steer queued" data-steer="${esc(e.id)}">${esc(e.text)}<span class="steer-note">Read at the next step</span></div>`);
  }
  else if (e.type === "steer_read") {
    const el = document.querySelector(`.msg.steer[data-steer="${CSS.escape(e.id)}"]`);
    if (el) { el.classList.remove("queued"); const n = el.querySelector(".steer-note"); if (n) n.textContent = "Read"; }
  }
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
    if (here) endLive();
    S.runningChats.delete(id); delete S.buffers[id];
    loadConversations();
    if (!S.runningChats.size) hideActivity();
    drawSessionButton();
    if (here) { await openChat(id); refreshBrowser(); }
    return;
  }
  if (e.type === "user") { S.runningChats.add(id); S.buffers[id] = []; if (here) setBusy(true); drawSessionButton(); loadConversations(); }
  if (e.type === "error" && !S.runningChats.has(id)) { if (here) { bubble("error", e.text); setBusy(false); } return; }
  if (e.type === "tool_call") showActivity(describe(e.name, e.args || {}).replace(/^Opened/, "Opening").replace(/^Clicked/, "Clicking").replace(/^Typed/, "Typing").replace(/^Read/, "Reading").replace(/^Looked/, "Looking").replace(/^Pressed/, "Pressing") + "…");
  if (e.type === "delta") { if (here) liveText(e.text); return; }
  if (!S.buffers[id]) S.buffers[id] = [];
  S.buffers[id].push(e);
  if (here) renderEvent(e);
}

function setBusy(busy) {
  // Send stays: a message sent while it works steers it at the next step.
  S.busy = busy; $("#stop").hidden = !busy;
  $("#send").textContent = busy ? "Steer" : "Send";
  $("#send").title = busy ? "Send now — the AI reads it at its next step and adjusts" : "Send (Enter)";
  $("#prompt").placeholder = busy ? "Working… type to steer it — read at the next step" : "Tell the browser what to do…";
}

function grow() { const p = $("#prompt"); p.style.height = "auto"; p.style.height = Math.min(p.scrollHeight, window.innerHeight * 0.4) + "px"; }
$("#prompt").addEventListener("input", grow);

async function send() {
  const text = $("#prompt").value.trim();
  if (!text) return;
  if (S.busy && S.draft) return;
  if (!ready()) return drawSetup();
  if (S.draft) {
    // The first message makes the chat: its session, its browser, then this.
    $("#prompt").value = ""; grow(); setBusy(true);
    try {
      const name = await createChatSession();
      S.pendingSend = text;
      await selectSession(name);
    } catch (e) { setBusy(false); $("#prompt").value = text; fail(e); }
    return;
  }
  if (!S.chat) return;
  if (!S.chatSock || S.chatSock.readyState !== 1) { openChatSocket(); return toast("Reconnecting — send again in a moment", true); }
  const steering = S.busy;
  $("#prompt").value = ""; grow();
  if (!steering) setBusy(true);
  if (!(S.chat.messages || []).length && document.querySelector(".empty")) $("#messages").innerHTML = "";
  S.chatSock.send(JSON.stringify({ type: "send", chat_id: S.chat.id, text, model: $("#model").value || null }));
}
$("#send").onclick = send;
$("#stop").onclick = () => { if (S.chatSock && S.chat) { S.chatSock.send(JSON.stringify({ type: "stop", chat_id: S.chat.id })); toast("Stopped"); } };
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

// --- dropdowns ---------------------------------------------------------------------
//
// Native <select> lists are drawn by the operating system: white in a dark
// theme, another font, another arrow. Each select is kept -- hidden -- as the
// one source of truth, so every line that reads .value or sets .innerHTML still
// works, and this draws a button and a menu that look like the rest.

function enhanceSelect(sel, opts = {}) {
  const wrap = document.createElement("div");
  wrap.className = "dd" + (opts.className ? " " + opts.className : "");
  const button = document.createElement("button");
  button.type = "button"; button.className = "dd-btn";
  button.setAttribute("aria-haspopup", "listbox"); button.setAttribute("aria-expanded", "false");
  if (sel.title) button.title = sel.title;
  const label = document.createElement("span"); label.className = "dd-label";
  const chevron = document.createElement("span"); chevron.className = "dd-chev"; chevron.textContent = "▾";
  button.append(label, chevron);
  const menu = document.createElement("div");
  menu.className = "dd-menu"; menu.setAttribute("role", "listbox"); menu.hidden = true;
  sel.parentNode.insertBefore(wrap, sel);
  wrap.append(sel, button, menu);
  sel.hidden = true; sel.tabIndex = -1;

  const sync = () => {
    const current = sel.options[sel.selectedIndex];
    label.textContent = current ? current.textContent : (opts.empty || "");
    button.disabled = !sel.options.length;
  };
  const close = () => { menu.hidden = true; button.setAttribute("aria-expanded", "false"); };
  const choose = (value) => {
    close();
    if (sel.value !== value) { sel.value = value; sel.dispatchEvent(new Event("change")); }
    sync(); button.focus();
  };
  const open = () => {
    const option = (o) => {
      const i = o.index;
      return `<button type="button" role="option" class="dd-opt${i === sel.selectedIndex ? " on" : ""}" data-value="${esc(o.value)}"${o.selected ? ' aria-selected="true"' : ""}>` +
        `<span class="dd-tick">${i === sel.selectedIndex ? "✓" : ""}</span><span>${esc(o.textContent)}</span></button>`;
    };
    // An <optgroup> shows as a divider with its label above its options.
    menu.innerHTML = [...sel.children].map(node => node.tagName === "OPTGROUP"
      ? `<div class="dd-group" role="presentation">${esc(node.label)}</div>` + [...node.children].map(option).join("")
      : option(node)).join("");
    menu.hidden = false; button.setAttribute("aria-expanded", "true");
    const on = menu.querySelector(".on") || menu.querySelector(".dd-opt");
    if (on) { on.scrollIntoView({ block: "nearest" }); on.focus(); }
  };
  button.onclick = () => { menu.hidden ? open() : close(); };
  menu.onclick = (e) => { const o = e.target.closest(".dd-opt"); if (o) choose(o.dataset.value); };
  menu.onkeydown = (e) => {
    const items = [...menu.querySelectorAll(".dd-opt")];
    const at = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown") { e.preventDefault(); (items[at + 1] || items[0]).focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); (items[at - 1] || items[items.length - 1]).focus(); }
    else if (e.key === "Escape") { e.preventDefault(); close(); button.focus(); }
    else if (e.key === "Tab") close();
  };
  button.onkeydown = (e) => { if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); open(); } };
  document.addEventListener("click", (e) => { if (!wrap.contains(e.target)) close(); });
  // Code changes the options and the value directly; keep the button in step.
  new MutationObserver(sync).observe(sel, { childList: true, subtree: true, attributes: true, characterData: true });
  sel.addEventListener("change", sync);
  const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value");
  Object.defineProperty(sel, "value", {
    get() { return setter.get.call(this); },
    set(v) { setter.set.call(this, v); sync(); },
  });
  sync();
  return { sync };
}

// --- files: uploads, downloads, the page's file picker ----------------------------

async function loadFiles() {
  try { return await api("GET", "/app/files"); } catch (e) { return null; }
}

// A download that landed since the last look gets a toast, once.
async function checkDownloads() {
  const session = S.session;
  const out = await loadFiles(); if (!out || S.session !== session) return;
  const names = out.downloads.files.map(f => f.name);
  const seen = S.downloadsSeen[session];
  S.downloadsSeen[session] = new Set(names);
  if (!seen) return;
  for (const name of names) if (!seen.has(name)) toast(`Downloaded ${name} — in Files`);
}

function fileRows(list, which) {
  if (!list.files.length) return `<div class="menu-empty">${which === "uploads" ? "Nothing here yet. Put files here for the AI to upload." : "Nothing downloaded yet."}</div>`;
  return list.files.slice(0, 12).map(f =>
    `<button class="row" data-open="${which}" data-name="${esc(f.name)}" title="Open ${esc(f.name)}">` +
    `<span class="grow">${esc(f.name)}</span><span class="meta">${sizeOf(f.size)}</span></button>`).join("");
}
function sizeOf(n) { return n < 1024 ? `${n} B` : n < 1048576 ? `${Math.round(n / 1024)} KB` : `${(n / 1048576).toFixed(1)} MB`; }

async function toggleFiles(open) {
  const menu = $("#files-menu");
  const show = open === undefined ? menu.hidden : open;
  if (!show) { menu.hidden = true; return; }
  const out = await loadFiles();
  if (!out) return toast("This session has no folders yet", true);
  menu.innerHTML = `<h4>Uploads — the only files the AI can hand to a page</h4>${fileRows(out.uploads, "uploads")}
    <button class="row" data-folder="uploads"><span class="grow">Open the uploads folder</span></button>
    <hr><h4>Downloads</h4>${fileRows(out.downloads, "downloads")}
    <button class="row" data-folder="downloads"><span class="grow">Open the downloads folder</span></button>`;
  menu.hidden = false;
}
$("#files-btn").onclick = () => toggleFiles();
document.addEventListener("click", (e) => { if (!e.target.closest("#files-menu, #files-btn")) $("#files-menu").hidden = true; });
$("#files-menu").onclick = async (e) => {
  const row = e.target.closest(".row"); if (!row) return;
  const body = row.dataset.folder ? { which: row.dataset.folder } : { which: row.dataset.open, name: row.dataset.name };
  try { await api("POST", "/app/files/open", body); $("#files-menu").hidden = true; } catch (err) { fail(err); }
};

// Ctrl+V in the live view types the clipboard into the page.
document.addEventListener("paste", (e) => {
  if (document.activeElement !== $("#screen")) return;
  const text = (e.clipboardData && e.clipboardData.getData("text")) || "";
  if (!text) return;
  e.preventDefault(); sendInput({ type: "text", text });
});

// --- start -------------------------------------------------------------------------------

(async function boot() {
  applyTheme(); applyLayout();
  enhanceSelect($("#convpick"), { className: "quiet", empty: "New chat" });
  enhanceSelect($("#model"), { className: "quiet up", empty: "No model set" });
  enhanceSelect($("#ses-profile"));
  await waitForBridge();
  try {
    await operatorToken();
    await loadAll();
    await loadModels();
    // The app opens on a new chat; earlier ones are in the list.
    enterDraft();
  } catch (e) { fail(e); }
  // Lock-free now, so the tab strip stays live while an agent works too.
  setInterval(() => { if (!document.hidden) refreshBrowser(); }, 3000);
  // The chat list's "replying" dots, for chats in other sessions.
  setInterval(() => { if (!document.hidden) loadConversations(); }, 5000);
  // The Agents button's count: how many are working, even with the grid closed.
  setInterval(() => { if (!document.hidden && !S.live.on) loadLive(); }, 5000);
  loadLive();
})();
</script>
</body>
</html>
"""
