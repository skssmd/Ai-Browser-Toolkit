# Changelog

## 0.7.0 — unreleased

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
- Sessions, profiles, rules, chats per session, an activity log with screenshots,
  uploads and downloads — all from the window. Light and dark themes.

### Other changes

- Diffs match a line only on the same text at the same tree address, so a
  control that moved — a dialog's "Decline" next to the one that opened it — is
  always reported.
- A guessed parameter name is answered with the op's real parameters.
- Profile browsers launch without popup blocking, as Playwright did.
- CI runs in four shards per platform, with a job timeout.

### Privacy

`PRIVACY.md` is updated: the desktop app sends your conversation, including page
text from tool results, to the model endpoint you configure, and stores your API
key locally; each profile's browser listens on a debugging port on
`127.0.0.1`; and the new files ABT keeps are listed with how to delete them.
