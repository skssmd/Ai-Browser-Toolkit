# Session Policy — Design

Date: 2026-09-28
Status: Approved (user: "finish the full setup"; open choices take the defaults
recommended in the design conversation)
Builds on: `2026-09-28-multi-profile-sessions-design.md` (spec 1)

## Purpose

A session can say which URLs its agent may reach, and whether the agent may run
scripts. The person launching an agent — at the CLI, or in the desktop app —
writes those rules; the agent cannot change them and cannot route around them.

## Settings

Three keys in a session's `settings`, all optional:

| Key | Type | Default | Meaning |
|---|---|---|---|
| `rules` | list of strings | `[]` | URL rules, below. Empty means no restriction. |
| `strict` | bool | `false` | Check every request, not just documents and API calls. |
| `run_js` | bool | server default | Whether `run_js` is allowed in this session. |

Settings change at any time (`abt session set`, `PATCH /sessions/NAME`, the
app). The change applies to the session's next command, and to the network
guard at once. A malformed value is `invalid_op`, never a 500.

## Rules

```
app.domain.com/admin        allow app.domain.com, paths under /admin
!app.domain.com/api         deny  app.domain.com, paths under /api
*.domain.com                allow domain.com and every subdomain
example.com:8080            a port is part of the host when written
```

- A rule is `[!]HOST[/PATH]`. Scheme is ignored. Host matching is exact and
  case-insensitive; `*.` matches the domain and all subdomains.
- A path matches on segment boundaries: `/admin` covers `/admin`, `/admin/`,
  `/admin/x`, never `/administrator`.
- **Deny wins.** A URL matching any deny rule is blocked.
- **Any allow rule makes the list an allow-list.** Then a URL must match an
  allow rule. With only deny rules, everything else is allowed.
- `about:`, `data:` and `blob:` URLs are always allowed: they fetch nothing.
  Any other non-HTTP scheme (`file:`, `chrome:`, `ftp:`) is blocked whenever
  the session has rules.

## Enforcement

**Op level.** `goto` and `tab_new {url}` check their URL before touching the
page. A blocked URL fails with the new error `url_blocked`, naming the rule,
with a hint that says to ask the person running the agent — not to find
another way in.

**Network level.** For every tab the session owns, the server holds its own
DevTools connection with the Fetch domain enabled and decides every paused
request against the rules: documents (including frames), `fetch`, XHR and
EventSource by default; every resource type with `strict`. A blocked request
fails with `BlockedByClient`, so a click that lands on a blocked page shows
Chrome's error page, and a `fetch()` from `run_js` rejects — `run_js` is not a
way around the rules.

This runs on threads of its own, not the session's Playwright thread: sync
Playwright only dispatches route callbacks while a command is in flight, which
would freeze every page's requests between an agent's commands.

**Popups.** A guard polls the browser's targets and guards a new page as soon
as its opener is guarded, before the owning session has looked at it. A page
whose first navigation already reached a blocked URL is sent to `about:blank`.

**Limits, stated.** Out-of-process iframes and workers are separate DevTools
targets and are not guarded; their documents are still covered when the frame
navigation passes through the page. A session without rules pays nothing: no
guard runs.

## run_js

`settings.run_js` overrides the server's `--no-run-js` default per session.
Off, `run_js` is refused with the existing hint and hidden from `/ops`.

## Surface

- `abt session new NAME --rules "a.com,!a.com/api" --strict --no-run-js`
- `abt session set NAME --rules ... --strict/--no-strict --run-js/--no-run-js`
  (`--rules ""` clears them)
- HTTP: `settings` on `POST`/`PATCH /sessions`.

## Errors

`url_blocked` — "this session's rules do not allow URL; rule: R". Hint: the
rules are set by whoever runs the session; ask them, do not work around it.

## Testing

Pure: rule parsing, matching, precedence, schemes, segment boundaries,
validation errors. Server, no browser: settings validation, `goto` refused
before the browser, `/ops` hides `run_js`. Live: a blocked document, a blocked
`fetch()` from `run_js`, an allowed page still loading, a popup to a blocked
URL.
