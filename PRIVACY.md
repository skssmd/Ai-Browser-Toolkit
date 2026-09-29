# Privacy Policy — AI Browser Toolkit

**Applies to:** AI Browser Toolkit (ABT), including the Windows installer
distributed as `skssmd.AIBrowserToolkit` on WinGet.
**Last updated:** 2026-09-29 — per-profile file folders, documents the AI saves, remembered pages, and how ABT closes the browsers it starts.
**Project:** <https://github.com/skssmd/Ai-Browser-Toolkit> (Apache-2.0).

## The short version

ABT is a local server that lets an AI agent drive a real Chrome or Edge window,
and an optional desktop app (`abt app`) with a chat that drives it for you. It has
no account, no sign-up, and no server of its own. It stores nothing on any machine
other than the one it runs on, and it collects no telemetry, no analytics and no
crash reports.

**What ABT is:** a data-curation and command layer between an AI agent and a real
browser. It has no model, no goals and no agenda of its own. The agent decides
what to do and writes it as a list of commands; ABT resolves each command against
the page at the moment it runs, and hands back a curated view of the result —
what changed, and what can be operated on next. Everything sensitive it does is
a consequence of commands something else wrote.

It does handle information that can be personal, and you should know exactly what:

- A **persistent browser profile** holds cookies, saved logins and authenticated
  sessions. It is ABT's own, created fresh and separate from the browser you use
  every day: ABT starts a **new** browser process against its own profile
  directory, and nothing is signed in until you sign in by hand. **Which account
  an agent can act as is the one you choose to sign in** — or, if you sign in to
  none, it cannot act as you at all. ABT does not read the profile's files, but
  anything able to drive the browser acts with whatever you signed in.
- **Session logs** record what the agent saw, what it ran and what came back —
  including page text — and **screenshots** record what was on screen. They are
  on by default so you can check afterwards whether the agent did the right
  thing. They are also unencrypted, and they are the most sensitive thing ABT
  writes. ABT's own documentation calls `logs/` secret.
- The **AI agent** decides what to do with the page text, the diffs and the
  screenshots ABT returns, and **that content leaves your device** to reach the
  agent's model provider. With an outside agent (Claude Code, Codex, an MCP
  client) the agent makes that call. **With the desktop app's chat, ABT makes it**:
  it sends the conversation and page content to the endpoint you configured, with
  the API key you entered, which ABT stores on this machine.
- **Profile folders** in `Documents\AI Browser Toolkit\<profile>` hold files you
  put there for the AI to upload, files the browser downloads, and documents the
  AI writes for you. Every session on a profile shares them, like its logins.
- The **browser** makes ordinary network requests to the sites the agent visits,
  carrying that profile's cookies, exactly as a browser you signed into would.

Those two flows — the pages the browser loads, and the content that goes to a
model — are the only data paths off the device. Apart from the desktop app's model
calls, the outbound requests ABT makes on its own are a fetch of a public playbook
index, and — only when you press the button — the list of free models from
OpenRouter; both are described in [section 5](#5-what-leaves-your-device).

## 1. Who this policy covers

This policy covers the AI Browser Toolkit software: the `abt` command, the local
HTTP server, the MCP shim, the browser automation code, the desktop app
(`abt app`), and the installer that puts it on your machine.

It does **not** cover:

- **Google Chrome and Microsoft Edge.** ABT drives a separate Chrome or Edge
  instance that it starts itself, with a profile of its own — see
  [section 3](#3-the-persistent-browser-profile). What that browser collects,
  syncs or stores is governed by
  [Google's privacy policy](https://policies.google.com/privacy) and
  [Microsoft's privacy statement](https://privacy.microsoft.com/privacystatement),
  and by the settings in the browser's own UI.
- **The sites an agent visits**, which have their own policies, and whatever
  third parties those pages embed.
- **The AI agent and model provider you choose to connect to ABT**, including the
  endpoint you enter in the desktop app — see
  [What leaves your device](#5-what-leaves-your-device).

## 2. What ABT accesses, stores, and whether it leaves the device

| Information | Where ABT handles it | Stored on disk by ABT | Leaves the device |
| --- | --- | --- | --- |
| Cookies, saved passwords, session storage, history, cache, download state in the persistent profile | Hands the directory to the browser as its user-data-dir; reads none of those files | No — the browser writes them, as in any Chrome profile | Only as ordinary web traffic to the sites an agent visits, carrying those cookies |
| Page and DOM content (text, element structure, frames, open shadow roots) | Returned to the caller of each op — usually a diff of what changed, a full page on navigation — and written into the session log | Yes, in `events.jsonl` | To the sites' own servers as page loads; to your model provider if your agent sends it there |
| Screenshots of the browser window | Written per command, and returned by the `screenshot` op | Yes, JPEG frames under each session's log directory | To your model provider if your agent sends them there |
| The live view in the desktop app | Frames streamed from the tab to the app window as it changes, and your clicks and typing sent back | No — frames are shown, not saved | No |
| Session logs: what the agent saw, ran, and got back — every command, its parameters, its result, URL, tab, timing | Appended to a JSONL file as commands run | Yes, `events.jsonl` | To your model provider if your agent sends it there |
| Browser network activity: request URLs, method, status, timing, content length | Read on request (`read_network`), and into the session log | Yes, as part of the recorded result | No |
| Browser console output | Read on request (`read_console`) | Yes, as part of the recorded result | No |
| Local file paths handed to `input` (uploads) | Passed to the page or to the site; the path string is recorded. In any session but `default`, and always for the desktop app's chat, only files inside the profile's uploads folder are accepted | Yes, as part of the recorded request | Only to the site the upload is aimed at |
| Files you put in a profile's uploads folder, files the browser downloads, and documents the AI saves (`save_file`) | Listed by name, size and path (the `files` op); never read into a response | Yes, in `Documents/AI Browser Toolkit/<profile>/uploads` and `/downloads` | Uploads only to the site you or the agent upload them to |
| The addresses of each session's open pages, and which one was active | Noted after every command, so the session reopens them when its browser starts again (after a restart or a crash) | Yes, in the session record (`sessions/<name>.json`) until the next command replaces it | No |
| Desktop app settings: model endpoint, **API key**, model list | Read when the chat calls the model | Yes, `app.json` in the sessions folder, readable only by your user account | The key goes to the endpoint you configured, with every request |
| Desktop app chats: your messages, the model's replies, every tool call and its result | Sent to your model provider on each turn, and shown in the app | Yes, one JSON file per chat in the sessions folder | To your model provider, on every turn |
| Sessions: name, profile, URL rules, settings; a sealed session's token | Read on every command to decide where it runs and what it may do | Yes, in the sessions folder; tokens owner-only | No |
| Playbook notes an agent writes (`guidelines_note`) | Written to a local playbook directory | Yes | Not until you run `abt guidelines submit` yourself |
| Machine details: browser choice, profile path, listening port, installed versions | Printed at startup and by `abt doctor` | Briefly, in `server.log` | No |

## 3. The persistent browser profile

ABT's premise is that the browser stays up between agent turns, so tabs, focus
and **logins** survive. That means long-lived browser profiles: `default`, and any
**named profiles** you create (`abt profile new NAME`, or *New profile* in the
app). Each is a separate directory with its own logins, next to `default`:

| Platform | Default location |
| --- | --- |
| Source checkout | `<checkout>/profiles/default` |
| Windows (installed) | `%LOCALAPPDATA%\AIBrowserToolkit\profiles\default` |
| macOS (installed) | `~/Library/Application Support/AIBrowserToolkit/profiles/default` |
| Linux (installed) | `$XDG_DATA_HOME/aibrowsertoolkit/profiles/default`, else `~/.local/share/aibrowsertoolkit/profiles/default` |

`--profile <dir>` points it elsewhere, and `abt doctor` prints the resolved path
and whether it is writable. Run it if you are ever unsure where the data is.

### It never touches the browser you use every day

ABT starts a **new** browser process and points it at its own directory with
`--user-data-dir`. It does not connect to, attach to, or read a browser you
already had open, and ABT contains no setting, default or code path that points
at the browser's own profile directory. Two independent browsers, two independent
sets of cookies.

That profile starts **empty**. ABT creates the directory, launches the browser
and gets out of the way: there is no sign-in, no account import, no cookie
copying out of another profile, no reading of the browser's own data. Until you
sign in by hand in that window, there is no account for an agent to act as — it
can reach public pages and nothing else.

So the line between "the AI can see my work mail" and "the AI can see nothing I
have not handed it" is drawn by **you**, when you type your password into the
window. Signing into your work account exposes your work account. Signing into
nothing exposes nothing. Signing into one site does not sign any other site in,
and the toolkit has no way to sign in on your behalf.

Signing in by hand is a supported path, not a workaround. `abt browser
open-manual` launches your real installed browser **with no automation attached**
on the same dedicated profile; you sign in, close the window, and ABT picks the
session up afterwards. That is the intended route for sites — Google among them
— that refuse a browser that is being driven.

Two deliberate ways to give the separation up, both yours to choose:

- `--profile <dir>` pointed at some other profile, including one you already use.
  ABT does not stop you. That other browser must be closed, and from then on the
  agent acts as whoever is signed in there.
- `ABT_CDP_URL`, which attaches the server to a browser you started yourself —
  see [The browser's debugging port](#the-browsers-debugging-port).

One thing worth keeping separate: signing **the browser** into a Google or
Microsoft account is a different decision from signing **a site** in. Chrome and
Edge offer to sign in to sync bookmarks and passwords, and if you accept, that
profile's contents are then handled under that account's sync and telemetry
settings rather than ABT's. If you want an agent inside one site, do not sign the
browser itself in.

What is in that directory is whatever the browser puts there: cookies, saved
logins, session cookies, local storage, IndexedDB, history, cache, download
state. It is a normal Chrome or Edge profile directory, and it is not a sandbox.
Sign into a site there once and that login persists across restarts until you
sign out or delete the directory.

**What ABT does not do with it:** ABT does not enumerate, read, copy, encrypt,
export or delete any file inside the profile. There is no "clear cookies" op,
no profile export, and no profile sync. ABT creates the empty directory and
hands it to the browser (`--user-data-dir`).

**What it can do with it:** anything the browser can do while signed in. A page
an agent opens is fetched as the logged-in user, and the text of that page is
returned to the caller. See
[How an agent or a local process reaches profile data](#4-how-agents-and-local-processes-reach-profile-data).

## 4. How agents and local processes reach profile data

This is the part worth reading carefully, because it is the whole point of the
product and the part with the widest blast radius.

### The agent, over HTTP or MCP

Every interface is a door into the same browser, and each one is as powerful as
the browser:

- **`POST /command-list` on `127.0.0.1:8765`** (and `abt command-list` for the
  CLI, and `abt mcp` for MCP clients) runs operations against the browser the
  agent was pointed at. Each op returns text from the page it touched — usually
  only what changed, the whole page after a navigation — so the caller receives
  whatever the signed-in session can see: inbox contents, order history, private
  messages, internal dashboards, files the site serves to that account.
- **`find`, `find_full`, `get_text`** reach inside iframes and open shadow roots,
  so embedded widgets and third-party components are readable too.
- **`run_js`** executes arbitrary JavaScript in the page, which can read anything
  the page itself can read — including the site's own `localStorage`,
  `sessionStorage` and `IndexedDB`. It can be disabled per server with
  `--no-run-js`.
- **`read_network`** returns request URLs, methods, statuses and timings. Headers
  and bodies are never captured, and credential-bearing query parameters
  (`token`, `code`, `password`, `sig`, and 14 more) are replaced with
  `REDACTED` before the row is returned or logged.
- **`read_console`** returns page console output.
- **`input`** types into forms, including sign-in forms.

MCP is a thin shim: `abt mcp` speaks JSON-RPC over stdio and forwards
`command_list`, `browser_session` and `browser_guidelines` to that same loopback
server. Anyone who can start `abt mcp` inherits the full power of the profile —
an MCP client is an agent host, not a sandboxed plugin.

The point where content leaves the device is **your agent**, not ABT. ABT returns
text, diffs, frames and network rows to whatever called it. If that caller is
Claude Code, Codex, opencode, Cursor or anything else, whether the content is
sent to a model provider is governed by that agent's configuration and the
provider's terms. ABT has no visibility into it and no setting that governs it.

### Sessions: open and sealed

Every command runs in a **session** — a profile, its tabs, its rules and its log.

- An **open** session is chosen by name alone (`--session`, `ABT_SESSION`, a
  header). That keeps cooperating agents out of each other's tabs; it is **not**
  a security boundary, because any local process can name any open session.
- A **sealed** session — every session the desktop app creates, by default —
  requires a token on every command, every log read and every settings change.
  The token is stored hashed in the session record and in plain text in an
  owner-only file only the desktop app reads. A model in the app's chat never sees
  it, and no tool lets a model choose or leave its session.
- The **operator token**, in `sessions/operator.token`, lets the desktop app view
  and click any tab in the live view and manage model settings. It is kept across
  restarts.
- A session's **URL rules** (`app.example.com/admin`, `!app.example.com/api`)
  are enforced before a navigation and on the network: a link, a redirect or a
  `fetch()` from `run_js` to a blocked address fails in the browser itself.
  Cross-site embedded frames and background workers are not covered.
- **What a profile's sessions share.** Sessions on the same profile — sealed ones
  too — share its logins and cookies, and its uploads and downloads folders: a
  file one chat or agent downloads or saves can be listed, and uploaded, by any
  other session on that profile. Their tabs, rules, logs and chats stay separate.
  Keep work that must not mix on separate profiles.

### Any other local process, and any web page

The HTTP server **binds to `127.0.0.1` only** (`src/abt/cli.py` `HOST`), so it is
not reachable from another machine. **Open sessions are not authenticated**: there
is no token on them, no CORS headers and no `Host` header validation, so anything
that can open a TCP connection to that loopback port has the same access to an
open session — `default` included — as the agent. Sealed sessions refuse any
command without their token. The WebSockets behind the app's live view and chat
refuse any connection whose `Origin` is not the local server, so a web page cannot
watch or drive a tab through them. For open sessions, that exposure includes:

- any other process running as any user on the same machine, and any other user
  session on a shared or multi-user host;
- **a web page open in any browser on the machine.** Requests to `127.0.0.1`
  from a page are still delivered to the server even though the page cannot read
  the reply, and the server validates no `Origin` and no `Host` header. A
  malicious page can therefore issue side-effecting commands — navigate,
  click, type, run JavaScript — even though it cannot exfiltrate the responses
  directly.

Consequences to plan for:

- `GET /logs`, `GET /logs/{session_id}` and `GET /logs/{session_id}/shots/{name}`
  expose the **recorded history** of every session, and `GET /viewer` renders
  it as a page. A local caller can read the whole log viewer.
- `POST /browser/open-manual` launches a real browser window on the profile;
  `{"op": "run_js"}` runs code in the live page; `{"op": "shutdown"}` stops the
  server.
- `/docs`, `/redoc` and `/openapi.json` are served, publishing the API surface.

Practical mitigations are in [Controls](#7-controls). The short version: don't
run ABT on a shared machine, don't port-forward the port, and stop the server
when you are not using it.

### The browser processes ABT starts and stops

ABT starts one hidden or windowed Chrome per profile and ends it when no session
needs it. It also ends browsers in these cases, and only these:

- **Closing the desktop app** closes the browsers it was using. The server keeps
  running for anything else using it, and they start again on demand.
- **A browser left behind** by an ABT server that stopped without closing it —
  identified by its profile folder and ABT's own launch flag — is ended when the
  next server needs that profile. A Chrome window you opened yourself is never
  ended this way.
- **Force close**, only when you press it in the app (or call
  `POST /profiles/<name>/force-close` with the operator token): ends every
  browser holding that profile, including a window you opened on it. Anything
  unsaved in it is lost.

Stopping the server stops any reply the app's chat is still running, and the
process exits, so nothing keeps acting on a browser after you stop ABT.

### The browser's debugging port

With sessions (the default on the Playwright engine), ABT starts each profile's
browser with `--remote-debugging-port=0`: Chrome picks a free port **on
`127.0.0.1` only**. That is how several sessions share one browser, how URL rules
are enforced on the network, and how the app shows the live view. The port is not
published over ABT's API, but any process running as you can find it and drive
that browser directly, around sessions, rules and tokens — the same trust boundary
as the profile files themselves. Setting `ABT_CDP_URL` still attaches to a browser
you started yourself, and switches sessions off.

## 5. What leaves your device

These flows carry information off the device. The desktop app's chat, the
optional free-model lookup and the playbook index are initiated by ABT; the rest
are the browser's and your agent's.

### Pages an agent visits

The browser loads pages, and those pages load third-party content — ad networks,
analytics beacons, fonts, embedded widgets — which receive the profile's cookies
for their own domains. This is ordinary browser behaviour, but ABT makes it
automated and repeatable, and the profile is signed in to whatever **you** chose
to sign it into. Every site's own policy applies to what it collects during a
visit, and a site the agent reaches without being signed in sees an anonymous
browser.

### Your model provider, through your agent

Page text, diffs, screenshots, console output and network rows are handed to the
agent, and an agent's whole purpose is to send that context to a model. **Expect
content from your authenticated pages to be transmitted to whichever model
provider you have configured.** With an outside agent, ABT does not make that call
and does not hold the key.

### Your model provider, through the desktop app

The app's chat **is** an agent, and ABT runs it. On every turn ABT sends, to the
endpoint you entered (OpenRouter by default, or any OpenAI-compatible service):

- your API key, in the `Authorization` header;
- the whole conversation so far — your messages, the model's replies, and the
  result of every tool call, which includes page text from your signed-in
  sessions (older results are shortened);
- the list of tools and the session's URL rules, so the model knows its limits.

Screenshots are not sent. File contents are never sent: the model sees file names
and paths, not what is in them. `openrouter/free` and other routers may hand each
request to a different provider, each under its own terms; pick a single model if
that matters. **Fetch free models** sends one request for OpenRouter's public
model list, with your key if you have saved one.

### How much leaves: curated, not raw

The volume is small by design, and that design is the product. An agent reading
raw browser state re-sends the page on every turn whether or not anything
changed, and then spends a second model pass making sense of it. ABT does
neither:

- **Most ops return only what changed** — text that appeared, text that
  disappeared, and the controls that just became operable. A turn where nothing
  changed carries almost nothing.
- **A navigation is the exception**, and deliberately so: it returns the
  destination page's text in full, because the agent has to know where it landed
  before it can decide what to do next.
- **`find` returns shells without content**; `find_full` fetches content only
  where the agent asked for it, so surveying a page does not mean reading it.
- **Batching** means one agent turn can carry twenty actions without twenty
  round trips of page state.

This reduces how much of your browsing is transmitted. It does not reduce how
sensitive it is. A diff of a private page is still private content, and the first
time a value appears in a diff it appears whole.

### Playbook lookups

ABT keeps a library of site playbooks — notes that tell an agent how a
particular site is structured. To tell you when that library has been updated,
and to find a playbook for a domain you visit, ABT fetches a **public index
file**:

    https://raw.githubusercontent.com/skssmd/ABT-Playbooks/main/index.json

- It runs at most **once every 24 hours**, tracked in a local config file, and
  only on server start.
- It happens on the **first visit to a new domain** in a session, to look for a
  playbook for it.
- **No data about you, your pages, your profile or your browsing leaves with
  it.** It is an ordinary HTTPS GET of a fixed public URL. The domain you
  visited is matched against the downloaded index **locally**; it is not part of
  the request, and no identifier, header or machine detail is sent.
- `abt guidelines pull` additionally contacts `api.github.com` to resolve a
  commit SHA, and only when you run that command and confirm it.
- Turn it off with `abt guidelines lookup --off` (persisted) or
  `--no-guideline-lookup` (one run).

### Nothing else

ABT never collects an account, a name, an email address, an IP address, a device
identifier, an advertising identifier or a usage profile, and it has nowhere to
put them: there is no backend. There is no telemetry, no analytics, no usage
reporting, no crash reporting, no update check, no version ping and no
phone-home. ABT contacts an AI service only for the desktop app's chat, only the
endpoint you entered, and only when you send a message.

The repository also contains a benchmark harness under `benchmarks/` that calls
model APIs directly. It is a developer tool, is not part of the installed
package, and does nothing unless you run it yourself.

At install time, the platform's own package tooling reaches the network
according to its own policy — WinGet or the winget community repository, Scoop,
Homebrew, the AUR, the apt/rpm/apk repository, or PyPI. Those are the package
manager's transactions, not ABT's. `abt doctor --install-browser` will run
`winget install Google.Chrome` or `brew install --cask google-chrome` if you ask
it to and no browser is found.

## 6. Session logs, screenshots, and other files ABT writes

### Session logs (on by default)

Each command appends one line to `events.jsonl`, and the three things that line
holds are the three things you would want to check afterwards:

| In the log | What it lets you answer |
| --- | --- |
| **What the agent saw** — the page text that appeared and disappeared, plus a screenshot of the window after every command | Did it look at what it should have looked at? |
| **What it ran** — the operations in order, with their targets, typed values, URLs, tab and timings | Did it do what you asked, in the order it should have? |
| **What came back** — every result and every error, including `read_network` rows | Did the result match the intent, or did it fail quietly? |

Structurally, each line is: timestamp, session id, tab id, site, full URL,
operation, success flag, error type, duration, **the complete request** and
**the complete response**.

**Why it is on by default:** an agent is a black box acting on your accounts, and
this is the record you check it against. When a task is done — or has gone
sideways — `abt logs` and `GET /viewer` are how you find out what it actually saw
and did, in order, instead of taking its word for it. The same property is what
makes the log sensitive: it is a complete account of the session, so it belongs to
you and to anyone who can read the log directory or the loopback port.

| Platform | Default location |
| --- | --- |
| Source checkout | `<checkout>/logs` |
| Windows (installed) | `%LOCALAPPDATA%\AIBrowserToolkit\logs` |
| macOS (installed) | `~/Library/Logs/AIBrowserToolkit` |
| Linux (installed) | `$XDG_STATE_HOME/aibrowsertoolkit/logs`, else `~/.local/state/aibrowsertoolkit/logs` |

`--log-dir` changes it. `--no-log` turns the recorder off entirely — which also
stops frames being written to disk. With sessions, each session has its own
directory and each server run a folder inside it:
`logs/sessions/<session>/<YYYYMMDD-HHMMSS>/` with `events.jsonl`, a `meta.json`
summary, and `shots/`. A sealed session's log is readable over HTTP only with its
token. The desktop app shows a session's log under *Activity log*. Removing a
session moves its logs to `logs/removed-sessions/`, so a new session with the same
name does not inherit them.

**These files are not redacted.** Individual string fields are truncated at
4,000 characters and nothing else is filtered, so a value typed into a form —
including a password, if a person or an agent types one into a visible field —
is written in plain text. Password *field values* are deliberately never
captured from the DOM in page snapshots, and credential query parameters are
redacted, but the request itself is recorded verbatim. Treat `logs/` as
sensitive material.

### Screenshots (on by default)

A frame is captured after every navigation, click, typed value, key press, scroll
and tab change, and after every failed command whatever it was, as a 1280px-wide
JPEG at quality 60 — with a box marking the element the op targeted. Identical
consecutive frames are stored once. Frames are written to
`logs/<session-id>/shots/NNNNN.jpg` and served at
`GET /logs/{session_id}/shots/{name}`. `--shot-quality` and `--shot-width`
change the format.

A frame shows whatever was on screen: a signed-in inbox, a private message, a
bank balance. `--no-shots` turns frames off; `--shots-max-mb` (default 200 MB per
session) bounds the budget, after which capture stops for that session. The
`screenshot` op can return an image inline as base64 instead, which does not
write a file.

### Other files

Two roots sit alongside the profile, and both are outside the installed program
directory — which is why uninstalling does not take them with it.

| | Windows | macOS | Linux |
| --- | --- | --- | --- |
| Data root (profile, `config.json`, playbooks) | `%LOCALAPPDATA%\AIBrowserToolkit` | `~/Library/Application Support/AIBrowserToolkit` | `$XDG_DATA_HOME/aibrowsertoolkit`, else `~/.local/share/aibrowsertoolkit` |
| State root (logs, first-run marker) | `%LOCALAPPDATA%\AIBrowserToolkit` | `~/Library/Logs/AIBrowserToolkit` | `$XDG_STATE_HOME/aibrowsertoolkit`, else `~/.local/state/aibrowsertoolkit` |

| What | Where | Note |
| --- | --- | --- |
| `config.json` | data root | Playbook lookup settings and the last check timestamp. No credentials. |
| `sessions/` | beside the profiles (`<checkout>/sessions`, or the data root) | Session records (`<name>.json`: profile, settings, and the addresses of the session's open pages), sealed-session tokens (`<name>.token`), `operator.token`, the desktop app's `app.json` **including your model API key**, and `chats/<session>/` with every chat. Files are created readable only by your account on macOS and Linux; on Windows they inherit your user profile's permissions. Removed sessions' chats move to `removed-chats/`. |
| `Documents/AI Browser Toolkit/<profile>/uploads`, `/downloads` | your Documents folder | Files you put there for the AI to upload, files the browser downloaded, and documents the AI saved with `save_file` (text only, up to 2 MB, never overwriting an existing file unless asked). Shared by every session on the profile. Nothing is deleted automatically. |
| `guidelines/local/`, `guidelines/trusted/`, `guidelines/pending/` | data root | Playbooks read, trusted, or pulled but not yet trusted. An agent's own `guidelines_note` is written locally and is not shared until you run `abt guidelines submit`. |
| `server.log` | next to the source checkout | The launcher's stdout, including the resolved profile path, log directory and listening address. |
| An `abt` entry in an agent's MCP settings | `~/.claude.json` (via `claude mcp`), `~/.codex/config.toml`, `~/.cursor/mcp.json`, VS Code's `mcp.json`, `~/.gemini/settings.json`, `~/.config/opencode/opencode.json`, `~/.codeium/windsurf/mcp_config.json` | Only when you press *Connect* in the app for that agent. One entry, named `abt`, that runs ABT's MCP bridge on the profile you picked -- each agent it runs then names its own session, which is kept like any other; nothing else in the file changes, and the file is first copied to `<file>.abt-backup`. *Disconnect* removes the entry. |
| `.first-run-shown` | state root | An empty marker file. |
| A logon task or launch agent | Task Scheduler / launchd / systemd user unit | Only if you opt in with `abt autostart install` or tick the installer task. It starts the server at logon, so a browser that an agent can drive opens every time you sign in. |

### Helper agents

A chat with *Helpers* on can, after you approve its plan, start up to five
helper chats. Each is a sealed session of its own on the same profile — same
logins, same uploads and downloads folders — with the chat's allowed sites or
narrower ones, and its own session log and chat file. Each helper is another
conversation with your model provider, with your key, so a team of five costs
roughly five times the model traffic. Delete a helper like any chat.

### In-memory only

The desktop app's live view frames are streamed and never written to disk; a
reply that is still running is held in memory and saved to the chat when it
finishes. A message you send while it runs is held until the model reads it at
its next step, then saved with the chat. The network ring buffer (500 entries per page, cleared on main-frame navigation)
and the page console buffer (500 messages, 2,000 characters each) are held in
memory and never written to disk.

## 7. Controls

**Reduce or stop what is recorded**

| Control | Effect |
| --- | --- |
| `abt serve --no-log` | No session log and no frames written to disk. |
| `abt serve --no-shots` | No frames; the session log still runs. |
| `--shots-max-mb <n>` | Lower the per-session frame budget (default 200). |
| `--log-dir <dir>` | Put logs somewhere you can encrypt, quota-limit or sync. |
| `abt logs` | Read what has been recorded — the record of what the agent saw and ran. |
| `GET /viewer` | Browse the recorded history in a browser. |

**Reduce what an agent can do**

| Control | Effect |
| --- | --- |
| `--no-run-js` | Disable arbitrary JavaScript execution in pages. Per session: `abt session set NAME --no-run-js`, or the *Scripts* switch on a new chat and in its settings. |
| URL rules per session | `abt session set NAME --rules "app.example.com,!app.example.com/api"`, or *Allowed sites* in the app (`all` by default; an empty list blocks every site). Enforced before navigation and on the network. `--strict` checks images, scripts and styles too. |
| Sealed sessions | `abt session new NAME --sealed`, or the default in the app. Nothing without the token can drive it. |
| Uploads only from the profile's uploads folder | On by default for every session but `default`, and always for the app's chat; `uploads_only` in the session settings. The AI cannot hand a page `~/.ssh/id_rsa` or any other file outside the folder. |
| `--max-profiles`, `--profile-idle-minutes` | Cap how many browsers run, and stop idle ones. |
| `ABT_URL_SCHEMES=http,https` | Restrict navigation to a scheme allow-list. With it set, the agent can no longer open a `file://` path on your machine or a `chrome://` page such as the password manager. |
| Hidden browsers | The app's chats always run hidden — the app shows their pages. Sessions from the CLI or HTTP open a window unless the server was started `--headless`; `abt profile set NAME --headless` fixes it per profile. |
| `--profile <dir>` | Use a profile that holds no logins. A second server on a second `--port` and `--profile` gives you a clean session with no shared state. |
| Do not enable autostart unless you want a driven browser at every logon. `abt autostart uninstall` removes it. |
| `abt browser stop`, or `{"op": "shutdown"}` | Close the browser and stop the server. |

**Decide what the agent gets to see**

This is the highest-leverage control in the product, and it is a sign-in, not a
setting. The default profile is ABT's own and starts empty, so the agent has no
account until you give it one.

| Control | Effect |
| --- | --- |
| Sign in to nothing | The agent can reach public pages only. Nothing of yours is reachable, logged or transmitted. |
| Sign in to one site, in that window | The agent can act as you on that site, and only that site. It sees that site's pages, and nothing of every other account you own. |
| Do not point `--profile` at your everyday profile | That is the one step that hands an agent your real, fully signed-in browser. Nothing in ABT does it for you. |
| Do not sign the browser itself into a Google or Microsoft account | Otherwise Chrome's or Edge's own sync applies to that profile, on top of ABT. |
| Sign out, then clear browsing data in the browser | Ends the session without deleting the profile directory. |

**Reduce the local attack surface**

- The server is loopback-only. Do not port-forward or tunnel port 8765; if you
  need a remote agent, put your own authenticated proxy in front of it and
  treat it as you would any remote-control surface.
- Do not run ABT on a shared or multi-user machine, or as a service account.
- Stop the server when you are not driving a browser.

**Control the one outbound request**

- `abt guidelines lookup --off` — persist; `abt guidelines lookup --on` to
  restore.
- `--no-guideline-lookup` for a single run.

**Control your agent**

- Choose an agent and a model provider whose handling of your page content you
  accept, or one that runs locally. This is the only lever on the largest data
  flow. In the desktop app, that choice is *Models*: a local endpoint (for
  example Ollama at `http://localhost:11434/v1`) keeps the conversation on this
  machine.
- Keep the default dedicated profile for agent work, so the agent's
  authenticated sessions are not the same ones you use day to day.

## 8. Retention and deletion

**Nothing expires on a timer.** ABT has no retention schedule, no rotation and
no automatic pruning: session directories, `events.jsonl` and frames accumulate
until you delete them. A long-running install can accumulate a lot of logged
page text and screenshots.

Deletion is manual, and the paths are:

| What | How to delete it |
| --- | --- |
| Session logs and screenshots | Delete the session directories under your log directory, or the whole `logs` directory. |
| Desktop app chats | Delete a chat in the app, or the `sessions/chats/` folder. |
| The model API key | Clear it in *Models*, or delete `sessions/app.json`. |
| Session records, tokens and remembered pages | `abt session rm NAME`, or delete the `sessions/` folder. Deleting a chat in the app removes its session too. |
| Uploaded, downloaded and saved files | Delete them from `Documents/AI Browser Toolkit/<profile>/`. |
| Named profiles | `abt profile rm NAME`, or *Logins from → delete* in the app. |
| Logins, cookies, history, site storage | Sign out inside the browser window and use Chrome's own "Clear browsing data" on that profile, or delete the profile directory. `abt doctor` prints the path. There is no ABT command for this. |
| Playbooks, config, first-run marker | Delete the data root (and the state root on Linux, where they differ). Local notes go with it; a submitted playbook is a separate Git history. |
| Logon task / launch agent | `abt autostart uninstall`. |
| ABT itself | The WinGet/Inno uninstaller removes the program files and the logon task. **It does not remove the data root** — `%LOCALAPPDATA%\AIBrowserToolkit` (or the `~/Library/…`, `~/.local/…` equivalent) holding the profile, the logs, the config and the playbooks stays on disk. Delete it yourself. |

A browser profile deleted while the browser is running may be recreated. Stop
the server first.

## 9. Security notes

- **For open sessions, the loopback boundary is the only boundary.** They are not
  authenticated, and neither is the MCP shim. Sealed sessions and the operator
  token are the exception, and protect against other programs using ABT — not
  against a program running as you, which can read the same token files. See
  [section 4](#4-how-agents-and-local-processes-reach-profile-data).
- **Your model API key is stored unencrypted** in `sessions/app.json`, protected
  by file permissions only.
- **The profile directory is not encrypted by ABT** and is protected only by your
  operating system's file permissions and disk encryption. Anyone who can read
  your user profile on that machine can read the cookies.
- **Session logs and screenshots are not encrypted** and are protected only by
  file permissions. Back them up, sync them or delete them accordingly.
- **Each profile's browser listens on a debugging port on `127.0.0.1`**, chosen by
  Chrome, not published by ABT's API. See [The browser's debugging port](#the-browsers-debugging-port).
- **Anti-automation flag.** Every profile browser starts with
  `--disable-blink-features=AutomationControlled`. This is about site
  compatibility, not privacy; it is mentioned because sites can observe it.
- ABT contacts a model provider only for the desktop app's chat, and only the
  endpoint you configured. If a report ever suggests it contacts anything else,
  that is a bug — please report it.
- Reports go to
  [GitHub issues](https://github.com/skssmd/Ai-Browser-Toolkit/issues). Please do
  not paste cookies, tokens, session-log excerpts or page content into a public
  issue; a description of the mechanism is enough to fix it.

## 10. Third parties

ABT has no contractual relationship with any of these; they are listed because
they handle your information when you use the product.

| Party | What they receive | When |
| --- | --- | --- |
| Your AI agent / model provider (Anthropic, OpenAI, Google, OpenRouter, or a local model) | Page text, diffs, screenshots, console and network data from the pages your agent opened, subject to that agent's configuration | Every agent turn, if the agent sends context to a model |
| The model endpoint you enter in the desktop app (OpenRouter by default, and through `openrouter/free` whichever provider it routes to) | Your API key; the conversation, including page text from tool results; tool definitions and the session's URL rules | Every chat turn you start |
| OpenRouter (`openrouter.ai/api/v1/models`) | One request for the public model list, with your key if saved | Only when you press *Fetch free models* |
| Every site an agent visits, and the third parties embedded in those pages | Ordinary web request data plus the profile's cookies for that site; form values, searches and messages you or your agent submit | Every page load and submission |
| Google Chrome / Microsoft Edge | The profile contents, and whatever the browser's own sync and telemetry settings send | Whenever the browser is running |
| GitHub (`raw.githubusercontent.com`, `api.github.com`) | One GET for a public playbook index, containing no data about you | Once per 24 hours, and on first visit to a new domain |
| Your package manager (WinGet, Scoop, Homebrew, AUR, apt/rpm/apk, PyPI) | Package download requests | Install and update only |

**ABT sells nothing, shares nothing with advertisers, and has no data broker
relationship.** There is no data broker, no advertising identifier and no
cross-site tracking performed by ABT.

## 11. Changes to this policy

This policy lives in the repository at
[`PRIVACY.md`](https://github.com/skssmd/Ai-Browser-Toolkit/blob/main/PRIVACY.md)
and is versioned with the code. Changes are visible in the commit history of
that file, and the last-updated line at the top records when it was last
reviewed. If a change materially affects what ABT collects or transmits, it will
be called out in the release notes.

## 12. Contact

Privacy questions, and requests concerning data ABT holds, go to
<https://github.com/skssmd/Ai-Browser-Toolkit/issues>.

Because ABT stores your data locally and transmits almost none of it, most
questions are best answered by looking: `abt doctor` shows where the profile
lives, `abt logs` shows what has been recorded, and every file path is in
[section 3](#3-the-persistent-browser-profile) and
[section 6](#6-session-logs-screenshots-and-other-files-abt-writes) above.
