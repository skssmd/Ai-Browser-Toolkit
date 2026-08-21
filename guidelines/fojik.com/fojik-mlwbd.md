# Fojik / MLWBD playbook

How to find and download a movie or series on fojik (the MLWBD network) with the
toolkit. Everything here was verified on a live session; follow it and skip the
trial-and-error.

## What you are actually driving

- `fojik.site` is a WordPress front-end that redirects to `fojik.com` (also
  branded MLWBD / MLWBD.App). Same content, several domains.
- The site indexes links only — every download row is a `<form>` that posts an
  **encrypted token** to a relay host (`search.technews24.site/blog.php`), which
  bounces you through two or three "secure link verification" pages before you
  reach the real file host. Nothing on fojik itself hosts files.

## Finding something

The search is a plain WordPress search — drive it by URL, no need to touch the
search box:

```
goto https://fojik.com/?s=my+hero+academia
```

The search page's results now come back **in the navigation diff itself**: after
the fix to the toolkit, `dom_diff.text` on a navigation holds the full landed-on
page, so the result titles, ratings, and year are all in the response. No
separate `get_text` needed.

To get the links to the results, survey with `find_full {"css": ".title a"}`.
Targeting is by **exact visible text** — a substring like `find {"text": "Judas
Gintama 001-367"}` matches nothing. Use the CSS survey and pick by `ref` instead.

## The detail page

Tabs: Info / Trailer / **Links** / Cast / Synopsis / Screenshots. The Links tab
is already open by default; the download rows live in `.links_table`:

```
tr#link-110510 | 4K UHD     | Dual Audio | -> form#110510
tr#link-110509 | 1080p HEVC | Dual Audio | -> form#110509
tr#link-110508 | 720p HEVC  | Dual Audio | -> form#110508
tr#link-110507 | 480p       | Dual Audio | -> form#110507
```

Each row is a `form#<N>` (method POST, action `search.technews24.site/blog.php`,
`target="_blank"`) with two hidden fields: `FU` (the encrypted payload) and `FN`
(the filename). The row's anchor is
`javascript:document.getElementById('<N>').submit();`.

## The verify gauntlet

Open the chosen row **in the current tab** — the form's `target="_blank"` would
hide the whole flow from you:

```json
{"op": "run_js", "script": "var f=document.getElementById('110509'); f.target='_self'; f.submit(); return f.action;"}
```

Then it is a fixed two-step dance:

1. Land on `sharelink-1.shop/dld2.php?i=...` (countdown page). Wait for the
   button, click it:
   ```json
   {"op": "wait_for", "css": "#maindownload", "state": "visible", "timeout": 15}
   {"op": "click", "css": "#maindownload", "force": true}
   ```
   Auto-redirects to `freethemesy.shop/dld2.php`.
2. Same page again — `wait_for` + `force` click. This time the **links table**
   is revealed on the page (season/quality rows with mirror hosts).

## The links table

Each row is `Label : host | host | ...`. Host labels seen:

| Label | Meaning | Notes |
|---|---|---|
| GDrive | Google Drive | via `go2.php` redirect |
| GDS | Google Drive Server | via `go2.php` → final host |
| PXD | pixeldrain.com | direct file host |
| TRNSIT | transfer.it | **often expired** — skip |
| MEGA | mega.nz | via `go.php` redirect |
| UTB / 1Fi | misc | via `go.php` redirect |

The GDS mirror is the reliable one. Its `go2.php` link leads to
`sharelink-3.shop/dld2/` — the "Verification complete. Download is active."
page.

## sharelink-3: the theater page

That page's button is **only for show** — the redirect happens on its own.
Click it once it is clickable and then just wait:

```json
{"op": "wait_for", "css": "a.butt.btn", "state": "clickable", "timeout": 20}
{"op": "click", "ref": "<the button>"}
// ~5s later:
{"op": "status"}   // url is now the real host, e.g. boabd.com/file/<id>
```

## The final host: boabd.com

`boabd.com/file/<id>` is MLWBD's file host. It asks for a Gmail login for the
regular "Download File" path — **ignore it**. Scroll the page and submit the
**R2 Direct Download** form instead (works with no login):

```json
{"op": "find_full", "text": "R2 Direct Download"}   // button el_2, form el_1
{"op": "click", "ref": "<the button>", "force": true}
```

The response's `text.added` will read `["Thank you for downloading!", "R2
Alternative Download", ...]` — that is the confirmation. Two presigned
`*.r2.cloudflarestorage.com` links now exist on the page (read them with
`run_js` over `a[href*="r2.cloudflarestorage"]`).

The presigned URLs are **bound to the browser session**: `curl` gets a 403, and
a `goto` to them bounces back to the boabd page. Trigger the download with a
**real anchor click** (`click` on the R2 link, no `force`). The file lands in
the browser's Downloads folder; the toolkit cannot read download status back, so
verify by reading the newest file in `%USERPROFILE%\Downloads`.

## Traps

- **Full-page ad overlay.** A `position:absolute; z-index:2147483647` div
  intercepts every click. Use `"force": true` on element clicks.
- **Clicking the wrapping element does nothing.** On search results, both the
  `<div class="title">` and the inner `<a>` match a text search. Force-clicking
  the *div* does not navigate — click the anchor's ref.
- **`text` matching is exact, not substring.** Use CSS surveys + refs.
- **TRNSIT links expire.** A transfer.it link returned "can't find this
  transfer / it may have expired or been removed". Always fall back to GDS.
- **The verify pages and R2 link are theater or session-bound.** Don't fight
  them with curl or raw navigation; use the browser the way the site intends.
- **Tabs you don't open yourself get closed** by the human operator — the ad
  popups open `about:blank`/Opera-GX tabs. Re-check `status` before trusting a
  tab id.
- **Multi-format pages are long.** `get_text` on a season page dumps every
  episode's every mirror. Query the links table with `run_js` instead, and grep
  the specific quality row.

## When not to use the browser at all

For downloading, prefer the direct host links (R2, pixeldrain, MEGA) over
clicking through fojik's relay every time. The browser is the right tool when
the links are hidden behind the verify flow and you need the session-bound
presigned URL.
