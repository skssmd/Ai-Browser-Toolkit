# Desktop App — Design

Date: 2026-09-28
Status: Approved (user: "finish the full setup"; decisions below were made in
the design conversation, the rest take the defaults recommended there)
Builds on: multi-profile sessions (spec 1) and session policy (spec 2).

## Purpose

One window: a live view of the browser on one side, a chat on the other. The
person picks a profile and a session, types a task, and a model of their choice
drives the browser through abt's own tool set — inside the session's sandbox,
never outside it.

## Decided in conversation

- One window; the browser pane is the **live screencast** of abt's own Chrome
  (spec 1), clickable and typeable by the person.
- The chat can be **docked left or right**, resized, and **hidden like a
  drawer** in one click (Ctrl+B). Side, width and hidden state persist.
- **Profile selector** with create/delete; **session selector** with
  create/delete and a settings dialog: profile, URL rules, strict, run_js
  (spec 2). Settings change at any time.
- **Conversation history per session**: a session holds any number of chats.
- **The user enters the API key, endpoint URL and model list**; a button fills
  the list with OpenRouter's current free, tool-capable models.
- The model drives abt through **the MCP tool set** (`command_list`,
  `browser_session`, `browser_guidelines`), so it sees exactly what an MCP
  client sees. The session is bound by the app; no tool takes a session.
- Sessions the app creates are **sealed** by default: the app holds the token,
  the model never sees it.

## Architecture

```
abt app ──► ensures the server is up (headless default profile) ──► pywebview window
                                                                     │ loads
            abt server ◄── HTTP + WebSockets ──  /app (single page, app_ui.py)
              ├─ /app/settings          operator token; key masked on read
              ├─ /app/models/free       GET {endpoint}/models, free + tools
              ├─ /app/chats             per-session chat store
              ├─ WS /app/chat           runs the agent loop, streams events
              ├─ WS /screencast         (spec 1)
              └─ /sessions, /profiles, /command-list   (spec 1, 2)
```

- **`appstate.py`** — `AppSettings` (`sessions/app.json`, owner-only) and
  `ChatStore` (`sessions/chats/<session>/<id>.json`).
- **`agent.py`** — the tool loop against any OpenAI-compatible
  `/chat/completions`: tools from `mcp.TOOLS`, the MCP instructions as the
  system prompt plus the session's rules, up to 40 steps per message, model
  fallback down the user's list when one fails (a free model without tool
  support, a rate limit), old tool results trimmed to keep context bounded.
  Pure apart from the injected `complete` and `call_tool`.
- **server** — tools run in-process through the same `execute` path as
  `/command-list`, under the session's lock and rules. The chat socket takes
  the session and its token at connect, like the screencast.
- **`app_ui.py`** — the page, one HTML string like `viewer.py`, no build step,
  no external assets.
- **`desktop.py`** — `abt app`: starts the server if needed, opens a
  pywebview window (`pip install "ai-browser-toolkit[app]"`), and hands the
  page the operator token and session tokens through pywebview's JS bridge, so
  neither is ever served over HTTP. Without pywebview it opens the default
  browser and the page asks for the operator token once.

## Security

- The operator token gates app settings, free-model lookup, and the
  screencast of any tab. The API key is stored owner-only and never returned
  in full.
- `/app/chat` and `/screencast` refuse any WebSocket whose Origin is not the
  local server.
- Everything the model does goes through the session: rules, `run_js`, tab
  locks and sealing all apply to it exactly as to any other client.

## Testing

Pure: tool-schema conversion, the loop with a scripted fake model (tool call,
final answer, fallback, stop), context trimming. Server, no browser: settings
masking and operator gating, chat CRUD and session scoping, the chat socket
driving a fake model through a real tool call. UI and desktop: a smoke check
that the page is served and names every endpoint it uses.
