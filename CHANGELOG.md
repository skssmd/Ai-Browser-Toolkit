# Changelog

## Unreleased

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
