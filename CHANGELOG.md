# Changelog

## 0.7.4 — 2026-09-29

- **Token usage in every chat.** Beside the model picker, the tokens the chat
  has used so far (in and out, over how many model calls, and what OpenRouter
  charged when it says); each Agents tile shows its session's total. Counted
  from the app's own model calls -- an MCP agent's tokens are its harness's,
  and ABT never sees them.
- **The app opens on the Agents grid.** Every agent's page at a glance; picking
  a chat from the list switches to its browser, and *Agents* brings the grid
  back.
- **The app's server hides every browser.** A server the app starts (`abt app`,
  the desktop starter) now runs CLI and MCP agents' browsers hidden too: the
  app shows their pages. `abt up` keeps windows; `abt app --headed` opts back
  in.

## 0.7.3 — 2026-09-29

- **No more MCP timeouts on background tabs.** When several agents share one
  windowed Chrome, only the front tab is drawn, and a screenshot of any other
  waited for ever -- holding the agent's session until the 60s deadline, so its
  every call timed out. A tab that is not drawn is now skipped in the log's
  frames instead.
- **Reconnecting reuses a session's tabs.** After a dropped connection or a
  restart, a session takes back its tabs that are still open, instead of
  opening a fresh tab and reopening its pages beside them -- which doubled its
  tabs on every reconnect. Remembered pages reopen once each.
- **Agents in the chat list.** Each agent's session (MCP, CLI or HTTP) is listed
  in the app as *Agent · <the name of its work>*; open it to watch its browser.
- **Listing tabs asks no tab.** Every tab is placed from one browser-wide call
  rather than a CDP session opened to each; the per-tab probe hung on Chrome's
  own start tab on a loaded runner.

## 0.7.2 — 2026-09-29

- **Agents view in the app.** The *Agents* button at the left of the browser
  toolbar shows every agent's page at once -- app chats and agents driving
  over the CLI or MCP, across profiles -- as live streams in a grid that
  adapts to how many there are (one, two, 2x2, 3x2, 3x3) and keeps each page's
  shape. Each tile shows who is driving, the profile, the step in progress,
  steps and time; click one to open it, or stop a chat's reply from it. The
  button shows how many are working. Streams run only while the grid is open,
  sized to their tile and view-only.
- **Helpers: one chat can run a team.** Turn on *Helpers* for a chat and it can
  split a task into roles -- a designer, an SEO expert, a security expert --
  and run up to five helper agents in parallel, each in its own session and
  tabs, confined to the chat's allowed sites. It shows you the plan first and
  starts nothing until you answer. It sees only their status, never their
  conversations, is told as each one finishes, reads their reports and writes
  a combined one. Without *Helpers* a chat is a single loop, as before.
- **Connect an agent in one tap.** From the Agents view, *Connect an agent*
  finds Claude Code, Codex, Cursor, VS Code, Gemini CLI, OpenCode and Windsurf
  on this computer. Connecting adds an `abt` MCP entry to its settings on the
  profile you pick (`claude mcp` for Claude Code); disconnecting removes only
  that entry. The file is backed up first, and one that is not plain JSON is
  left alone.
- **Every MCP agent names its own session.** Without `--session`, the MCP
  browser tools require a `session`: a short name for the task ("ebay price
  research"), used on every call. It is made on first use, on the bridge's
  `--profile`, and is the name the Agents view shows. Parallel agents in one
  harness -- several OpenCode agents, say -- used to share one session and
  navigate each other's pages away; now each has its own tabs, and an agent
  that restarts with the same name picks its tabs back up. `abt mcp --session`
  still fixes one for the connection. An entry written by an earlier Connect
  shows *Connect again* to switch over. For OpenCode, Connect writes
  `opencode.jsonc` when there is one -- OpenCode reads it, and an entry in
  `opencode.json` beside it was ignored.

## 0.7.1 — 2026-09-29

- **The AI can save documents.** A new `save_file` op writes a document the AI
  composed -- notes, a report, what it found -- into the downloads folder. Text
  formats only (`.md`, `.txt`, `.csv`, …), a plain file name, up to 2 MB; an
  existing file is kept and the new one gets a numbered name. It needs no
  browser. The app's chat is told to use it.
- **Folders per profile, not per session.** Uploads and downloads now live in
  `Documents/AI Browser Toolkit/<profile>/`, shared by every chat and agent on
  that profile like its logins -- one place to look instead of one folder per
  chat.
- **Back where it was.** Every session remembers its open pages and which one
  was active, and reopens them when its browser starts again -- after a
  `browser_restart`, a crash, or a server restart. The session's site rules
  still apply; a page that no longer loads is skipped. For app chats and for
  agents driving a session over the CLI or MCP alike.
- **A stopped server really stops.** A chat reply still running at shutdown
  kept the old process alive for up to five minutes, still driving its browser
  -- restarting it whenever the new server took the profile, which then lost
  its own browser in turn. Replies are stopped at shutdown and the process exits.
- **Steer a running chat.** A message sent while the app's AI is working joins
  at its next step; it takes it into account and keeps going, instead of
  stopping to reply. The model is also told to end its turn only when the task
  is done.
- **Hidden in the app, a window from the CLI.** Whether a profile's browser
  has a window now follows the session that starts it: the app's chats run
  hidden (the app shows the page), CLI and HTTP sessions follow the server's
  default, a window unless it was started with `--headless`. A profile's own
  setting (`abt profile set --headed/--headless`) still wins. `abt app` no
  longer starts the server `--headless`.

## 0.7.0 — 2026-09-28

One server now runs many sessions, each in its own browser profile, in
parallel — and there is a desktop app to drive them with a model of your choice.

### Sessions and profiles

- **Sessions.** Every command runs in a session: a profile (its logins), its own
  tabs, its own log. Name one with `--session`, `ABT_SESSION`, the
  `X-ABT-Session` header, or `abt mcp --session`. Say nothing and you are in
  `default`, which behaves as before.
- **Named profiles**, each its own Chrome with its own logins, started on demand
  and stopped when idle (`abt profile new|rm|set`, `--max-profiles`,
  `--profile-idle-minutes`).
- **Parallel.** Sessions on different profiles, and on the same profile, run at
  the same time.
- **Tab ownership.** A tab belongs to the session that opened it, and popups
  follow it. Other sessions on the profile see it as locked (`tab_locked`);
  `tab_claim` and `tab_release` move one.
- **Sealed sessions** need a token on every command (`abt session new NAME
  --sealed`). Open sessions are for cooperating agents and are not a security
  boundary.

### Rules and files

- **URL rules per session**: `app.example.com/admin` allows, `!…` blocks, any
  allow rule makes the list an allow-list. Enforced before navigation and on the
  network, so a link, a redirect or a `fetch()` from `run_js` cannot get round
  them (`url_blocked`). `--strict` checks every request.
- **`run_js` per session**, on or off.
- **Session folders** in `Documents/AI Browser Toolkit/<session>/`: `uploads`
  is the only place a page's file input takes files from (`file_blocked`
  otherwise — `~/.ssh` included), `downloads` is where downloads land. The new
  `files` op lists both, names and paths only, and can open the uploads folder
  for the person. File pickers never open in a session; the command that caused
  one says how to upload instead.

### Desktop app (`abt app`)

- The session's browser, live and clickable, beside a chat that streams the
  model's replies and shows each step in plain words.
- Any OpenAI-compatible endpoint; first-run setup finds OpenRouter's free models
  with tool support, and the chat falls back down your model list when one fails.
- Replies run on the server: switching session or profile, or closing the
  window, leaves them running; coming back replays what was missed.
- **Every chat is its own session.** New chat opens a short settings card —
  which profile's logins, which sites it may visit (`all` by default), scripts —
  and the first message creates a sealed session with those settings.
- The chat list keeps the newest activity on top, divides the last 30 minutes
  from the rest of the day, and moves chats idle for a day to an Archived menu;
  carrying one on brings it back.
- Closing the window closes its browsers; the server stays up. A browser left
  behind by a server that died is ended on the next launch, and a profile held
  by another window can be force-closed from the app.
- An activity log with screenshots, uploads and downloads, light and dark
  themes, and a logo of its own.

### Install

- **Windows installer** with a choice of the desktop app, the command line, or
  both; Start-menu and desktop shortcuts that open the app with no console. The
  server, and its logon task, start with no window.
- Bundles leave out pip (packages go in at build time) and Selenium.

### Other changes

- Diffs match a line only on the same text at the same tree address, so a
  control that moved — a dialog's "Decline" next to the one that opened it — is
  always reported.
- A guessed parameter name is answered with the op's real parameters.
- Profile browsers launch without popup blocking, as Playwright did.
- CI and the release's test run go in four shards, each with a job timeout.

### Selenium retired

- **Playwright is the only engine.** Selenium is no longer a dependency, is not
  bundled and is never imported, which takes about 23 MB off every install.
  `--engine selenium` is refused. The exception names, key names and waits the
  page layer uses are now the toolkit's own, with the same names and values, so
  nothing a caller sees changes.

### Privacy

`PRIVACY.md` is updated: the desktop app sends your conversation, including page
text from tool results, to the model endpoint you configure, and stores your API
key locally; each profile's browser listens on a debugging port on
`127.0.0.1`; and the new files ABT keeps are listed with how to delete them.
