# Privacy Policy — AI Browser Toolkit

**Applies to:** AI Browser Toolkit (ABT), including the Windows installer
distributed as `skssmd.AIBrowserToolkit` on WinGet.
**Last updated:** 2026-09-27.
**Project:** <https://github.com/skssmd/Ai-Browser-Toolkit> (Apache-2.0).

## The short version

ABT is a local server that lets an AI agent drive a real Chrome or Edge window. It
has no account, no sign-up, and no server of its own. It stores nothing on any
machine other than the one it runs on, and it collects no telemetry, no analytics
and no crash reports.

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
- The **AI agent** you run decides what to do with the page text, the diffs and
  the screenshots ABT returns. Depending on which model that agent uses, **that
  content leaves your device** to reach the model provider. ABT itself never
  contacts a model, and never reads or stores a model API key.
- The **browser** makes ordinary network requests to the sites the agent visits,
  carrying that profile's cookies, exactly as a browser you signed into would.

Those two flows — the pages the browser loads, and the content your agent hands
to a model — are the only data paths off the device. The single outbound request
ABT makes on its own is a fetch of a public playbook index, described in
[Playbook lookups](#playbook-lookups-the-only-outbound-request-abt-makes-on-its-own).

## 1. Who this policy covers

This policy covers the AI Browser Toolkit software: the `abt` command, the local
HTTP server, the MCP shim, the browser automation code, and the installer that
puts it on your machine.

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
- **The AI agent and model provider you choose to connect to ABT** — see
  [What leaves your device](#5-what-leaves-your-device).

## 2. What ABT accesses, stores, and whether it leaves the device

| Information | Where ABT handles it | Stored on disk by ABT | Leaves the device |
| --- | --- | --- | --- |
| Cookies, saved passwords, session storage, history, cache, download state in the persistent profile | Hands the directory to the browser as its user-data-dir; reads none of those files | No — the browser writes them, as in any Chrome profile | Only as ordinary web traffic to the sites an agent visits, carrying those cookies |
| Page and DOM content (text, element structure, frames, open shadow roots) | Returned to the caller of each op — usually a diff of what changed, a full page on navigation — and written into the session log | Yes, in `events.jsonl` | To the sites' own servers as page loads; to your model provider if your agent sends it there |
| Screenshots of the browser window | Written per command, and returned by the `screenshot` op | Yes, JPEG frames under `logs/<session-id>/shots/` | To your model provider if your agent sends them there |
| Session logs: what the agent saw, ran, and got back — every command, its parameters, its result, URL, tab, timing | Appended to a JSONL file as commands run | Yes, `events.jsonl` | To your model provider if your agent sends it there |
| Browser network activity: request URLs, method, status, timing, content length | Read on request (`read_network`), and into the session log | Yes, as part of the recorded result | No |
| Browser console output | Read on request (`read_console`) | Yes, as part of the recorded result | No |
| Messenger thread names, previews, message bodies, senders, timestamps | Held in memory, and written into the session log | Yes, in `events.jsonl` | To Messenger itself when an agent sends; to your model provider if your agent sends it there |
| Local file paths handed to `input` (uploads) or attached to a message | Passed to the page or to the site; the path string is recorded | Yes, as part of the recorded request | Only to the site the upload is aimed at |
| Playbook notes an agent writes (`guidelines_note`) | Written to a local playbook directory | Yes | Not until you run `abt guidelines submit` yourself |
| Machine details: browser choice, profile path, listening port, installed versions | Printed at startup and by `abt doctor` | Briefly, in `server.log` | No |

## 3. The persistent browser profile

ABT's premise is that the browser stays up between agent turns, so tabs, focus
and **logins** survive. That means one long-lived browser profile:

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
  see [No remote debugging port](#no-remote-debugging-port).

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
- **`messenger_*`** lists threads, reads messages and sends messages.
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

### Any other local process, and any web page

The HTTP server **binds to `127.0.0.1` only** (`src/abt/cli.py` `HOST`), so it is
not reachable from another machine. It is, however, **not authenticated at all**:
there is no token, no API key, no session, no origin check, no CORS headers and
no `Host` header validation. Anything that can open a TCP connection to that
loopback port has the same access as the agent. That includes:

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

### No remote debugging port

ABT never opens a remote debugging port itself and never listens on anything but
loopback. Setting `ABT_CDP_URL` opts into attaching to a browser you started
yourself; that connection is yours to make and yours to protect.

## 5. What leaves your device

Three flows carry information off the device, and only one of them is initiated
by ABT itself.

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
provider you have configured.** ABT does not make that call, does not choose the
provider, and does not read or store any API key — the key lives in your agent
process, and ABT's only configuration file holds no credentials.

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

### Playbook lookups: the only outbound request ABT makes on its own

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
phone-home. ABT does not call any model API and does not upload anything. It
contacts no AI service. The only network libraries it uses are an HTTP client
for the playbook index and the browser driver itself.

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
| **What came back** — every result and every error, including `read_network` rows and Messenger threads and messages | Did the result match the intent, or did it fail quietly? |

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
stops frames being written to disk. Each run gets its own directory:
`logs/<YYYYMMDD-HHMMSS>/` with `events.jsonl`, a `meta.json` summary, and
`shots/`.

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
| `guidelines/local/`, `guidelines/trusted/`, `guidelines/pending/` | data root | Playbooks read, trusted, or pulled but not yet trusted. An agent's own `guidelines_note` is written locally and is not shared until you run `abt guidelines submit`. |
| `server.log` | next to the source checkout | The launcher's stdout, including the resolved profile path, log directory and listening address. |
| `abt-attach-*` | system temp directory | Remote Messenger attachments downloaded at your or your agent's request. **Not deleted automatically.** |
| `.first-run-shown` | state root | An empty marker file. |
| A logon task or launch agent | Task Scheduler / launchd / systemd user unit | Only if you opt in with `abt autostart install` or tick the installer task. It starts the server at logon, so a browser that an agent can drive opens every time you sign in. |

### In-memory only

The network ring buffer (500 entries per page, cleared on main-frame navigation)
and the page console buffer (500 messages, 2,000 characters each) are held in
memory and never written to disk. Messenger cursors and job state are in memory
for the life of the process — but every Messenger route is recorded, so the
session log is the durable copy.

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
| `--no-run-js` | Disable arbitrary JavaScript execution in pages. |
| `ABT_URL_SCHEMES=http,https` | Restrict navigation to a scheme allow-list. With it set, the agent can no longer open a `file://` path on your machine or a `chrome://` page such as the password manager. |
| `--headless` | Run with no visible window, so nothing is shoulder-surfed. |
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
  flow, and it belongs to the agent, not to ABT.
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
| Logins, cookies, history, site storage | Sign out inside the browser window and use Chrome's own "Clear browsing data" on that profile, or delete the profile directory. `abt doctor` prints the path. There is no ABT command for this. |
| Playbooks, config, first-run marker | Delete the data root (and the state root on Linux, where they differ). Local notes go with it; a submitted playbook is a separate Git history. |
| Downloaded Messenger attachments | Delete `abt-attach-*` directories in your system temp folder. |
| Logon task / launch agent | `abt autostart uninstall`. |
| ABT itself | The WinGet/Inno uninstaller removes the program files and the logon task. **It does not remove the data root** — `%LOCALAPPDATA%\AIBrowserToolkit` (or the `~/Library/…`, `~/.local/…` equivalent) holding the profile, the logs, the config and the playbooks stays on disk. Delete it yourself. |

A browser profile deleted while the browser is running may be recreated. Stop
the server first.

## 9. Security notes

- **The loopback boundary is the only boundary.** There is no authentication on
  the server, on the log endpoints, or on the MCP shim. See
  [section 4](#4-how-agents-and-local-processes-reach-profile-data).
- **The profile directory is not encrypted by ABT** and is protected only by your
  operating system's file permissions and disk encryption. Anyone who can read
  your user profile on that machine can read the cookies.
- **Session logs and screenshots are not encrypted** and are protected only by
  file permissions. Back them up, sync them or delete them accordingly.
- **The WebSocket/CDP ports opened internally by the browser driver** are chosen
  by the driver, not by ABT, and are not exposed by ABT.
- **Anti-automation flags** (`--disable-blink-features=AutomationControlled`,
  `excludeSwitches: enable-automation`) are applied on the Selenium engine
  (`--engine selenium`) and not on the default Playwright engine. This is about
  site compatibility, not privacy; it is mentioned because sites can observe the
  difference.
- ABT never contacts a model provider and never handles an API key. If a report
  ever suggests otherwise, that is a bug — please report it.
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
