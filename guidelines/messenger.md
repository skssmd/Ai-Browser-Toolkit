# Messenger playbook

How to read, reply to, and send attachments on `messenger.com` with the
toolkit. Everything here was verified on live sessions; follow it and skip the
trial-and-error.

**Read this next part first.** The whole flow below is available as HTTP
endpoints. Use them. The rest of this file is what they do internally, and is
worth reading only when something breaks or you need a step they do not cover.

These endpoints are a **shortcut, not a wall**. They exist because the same
dozen ops always run together in the same order; they do not replace anything.
If a send does not fit their shape — a sticker, a poll, a reaction, an unsend,
a dialog nobody anticipated — drop straight back to the normal ops (`goto`,
`find`, `click`, `input`, `press`, `run_js`) and drive the page yourself, using
the rest of this file as the map. The browser is the same browser either way.

**On a long job, report as you go.** A task that takes minutes with no output
looks broken to whoever is waiting in the chat. After each step finishes, fire
a `POST /messenger/sendmessage/async` with a one-line progress update. It is
queued in a background tab, so it costs you nothing and never interrupts the
work in your current tab — which is exactly what the async endpoint is for.

## The Messenger API

| Endpoint | What it does |
|---|---|
| `GET /messenger/threads` | The sidebar: name, preview, time, and URL per thread |
| `GET /messenger/messages` | Messages in a thread, parsed into sender/time/text |
| `POST /messenger/sendmessage` | Send, and wait for the result |
| `POST /messenger/sendmessage/async` | Queue a send, answer immediately |
| `GET /messenger/jobs/{id}` | How a queued send went |

### Sending

```json
POST /messenger/sendmessage
{
  "thread_url": "https://www.messenger.com/t/927345869967156/",
  "message": "@Yaleed @Samin here is the capture",
  "mentions": ["Yaleed", "Samin"],
  "attachments": ["C:/shots/page.png", "https://example.com/logo.png"],
  "reply_to": "Step 1/4 DONE"
}
```

- **`mentions`** are real @-mentions, not text. Each name must appear in
  `message` as `@<name>`; that spot is typed through Messenger's suggestion
  popup and the popup's full name is what lands (`@Yaleed` → `@Yaleed Haque`).
  The response's `mentions` tells you who was actually tagged. A name with no
  suggestion **aborts before sending** — a half-written message stays a draft
  rather than going out wrong.
- **`attachments`** are local absolute paths, or `http(s)` links, which get
  downloaded to a temp file first because a file input takes a path, not a URL.
- **`reply_to`** is a substring of the message you are answering (the most
  recent match wins) or an index into the thread (negative counts from the end).
- Only `messenger.com` and `facebook.com` are accepted. This endpoint types
  into whatever it finds and then presses Enter; pointing it at another site is
  a footgun, so it refuses.

The response reports `sent`, `confirmed`, who was `mentioned`, what was
`replied_to`, and how many attachments were `staged`. `confirmed` is by
content — the message is looked for in the thread, never counted, because
Messenger virtualises a long thread and the number of rows on screen can *drop*
while a message is being added to it.

### Fire and forget

`POST /messenger/sendmessage/async` (or `"background": true`) answers with a
`job_id` straight away and does the work in a **new tab that it closes
afterwards**, restoring whatever tab you were on. Your page is never disturbed.
Poll `GET /messenger/jobs/{id}` for `state`: `queued` → `running` →
`sent`/`failed`. A failed job carries the same typed error a sync send raises.

### Reading

`GET /messenger/threads?url=https://www.messenger.com/` navigates and lists the
sidebar; omit `url` to read the sidebar already on screen. Each row gives
`name`, `preview`, `time`, `url`, and `e2ee`.

`GET /messenger/messages?thread_url=...&limit=50` opens the thread and returns
its messages, each parsed into `{sender, time, text, raw}`.

`&since_last=true` returns **only what arrived since your last read** of that
thread — the cheap way to poll a conversation. New rows are found by content,
not position, because Messenger trims the top of a long thread as it grows.
`&reset=true` forgets the cursor and treats everything as new.

Keep `limit` the same between polls. Since the cursor remembers rows rather
than a position, raising the limit reaches further back into history and those
older rows are, correctly, ones you have never seen — so they come back as new.

### From the CLI

```bash
abt messenger threads --url https://www.messenger.com/
abt messenger read -t https://www.messenger.com/t/<id>/ --new
abt messenger send "@Yaleed here it is" -t <thread-url> -m Yaleed -a C:/shots/page.png
abt messenger send "step 2 done" -t <thread-url> --async
abt messenger jobs <job-id>
```

`--reply-to "<substring>"` or `--reply-index -1` to answer a specific message;
`-m/--mention` and `-a/--attach` repeat.

## What you are actually driving

- Two kinds of threads:
  - **Normal** threads: `https://www.messenger.com/t/<id>/`
  - **E2EE** threads: `https://www.messenger.com/e2ee/t/<id>/` (end-to-end
    encrypted, "Only people in this chat can read"). Same ops, same DOM.
- Messages render as `div[role=article]` elements. Each one's
  `textContent` is roughly `"<msg>\nMessage sent HH:MM by <name>: <msg>"`.
- The compose box is a `div[contenteditable=true]` with a
  `Write to <name>` placeholder — not a textarea, not an `<input>`.

## Opening a thread

`goto` the thread URL directly. A freshly-created group may not show in the
sidebar until you reload: re-`goto` the thread URL and it appears.

To find a thread by name, use the search box:

```
input css=input[aria-label="Search Messenger"] value=<name>
```

Search is fuzzy and mixes people/groups/pages ("New Group" results are group
*creation* entries, not chats). Read the results from the `[role=listbox]`
panel; names come through as `"<Title> <handle> <subtitle>"`.

## The composer (typing and clearing)

- Focus it, then `input` — but beware: `input` **appends** to whatever draft
  is already in the box. A stale draft ("i") will end up glued to your new
  text.
- Clearing does NOT work with `execCommand('selectAll'/'delete')` (React
  ignores it) and `clear()` on a contenteditable raises. The reliable way is
  real keystrokes:

  ```
  press css=div[contenteditable=true] key=ctrl+a
  press css=div[contenteditable=true] key=Backspace
  ```

- Verify the box is empty before typing: `b.innerText.trim()` should be `""`.
- Send with `press key=Enter` on the composer. Text-only messages post
  instantly; the article row shows `Message sent HH:MM by You`.

## Reading messages

```
run_js script="// div[role=article] -> textContent.trim()"
```

One element per message; the last entries in the list are the newest. In a
group, the row text starts with the **sender's name**, e.g.
`YaleedHaan screenshot o pari!...` — separate sender from body by the first
capital-letter run.

## Attachments (images/files)

Messenger's attach target is a single hidden `<input type=file>` (accept
`*/*`, `0x0`, not displayed). You cannot click the paperclip — it opens a
native file dialog WebDriver can't see. Drive the input directly:

1. **Unhide it** so the `input` op's `state="visible"` resolve passes:

   ```
   run_js script="// el.style.cssText = 'display:block !important; visibility:visible !important; opacity:0.01 !important; position:fixed !important; top:0; left:0; width:5px; height:5px; z-index:99999;'"
   ```

2. **Set the file(s)** with `input` — the value is a local absolute path.
   For multiple attachments, join the paths with `\n` (native multi-select):

   ```
   input css=input[type=file] clear=false value=<path>[\n<path2>]
   ```

   Selenium's `send_keys` on a file input is what fires React's change handler
   — JS `DataTransfer` cannot inject a real local file, and a plain
   `input.files` read afterwards shows `0` because React already consumed the
   change. That's expected, not a failure.

3. **Confirm the upload**: after ~3-6s there should be one `img[src^=blob]`
   per attachment and no visible `[role=progressbar]` / `[class*=spinner]`
   in the composer area.

4. **Send**: focus the composer and `press key=Enter`. The article row shows
   `Sending` then `Sent` — wait for the `Sent` state before reporting
   success.

## Screenshots from the toolkit

`op: screenshot` returns base64; save it to a temp PNG
(`[Convert]::FromBase64String`) and attach it like any file. Keep the PNGs in
one scratch dir so "send the previous one too" is a re-attach, not a re-shot.

## Traps

- `execCommand('selectAll')` + `delete` does NOT clear the Messenger composer;
  use Ctrl+A + Backspace via `press`.
- The E2EE PIN setup dialog: PIN fields are `maxlen=6`, and the dialog needs
  `pin.scrollIntoView({block:'center'})` before typing or Selenium raises
  `MoveTargetOutOfBoundsException`.
- The file input is hidden and has no label — do not search for it by
  aria/name, `input[type=file]` is the only one on the page.
- "New Group" in search results is the *create* action, not a chat.
- In a shared group, reply policy can be scoped to one person ("don't listen
  to anyone but me") — only act on that sender's messages, ignore the rest.
- Sidebar chat rows: normal threads link to `/t/<id>/`, E2EE to
  `/e2ee/t/<id>/` — click the right one or you open the wrong conversation.
- Some screenshots/models cannot read images; use `div[role=article]`
  text/diffs to detect new messages instead of `screenshot`.
- The left rail's own links (Chats, Marketplace, Requests, Archive) are
  `a[href*="/t/"]` too, and they point at **whichever thread is currently
  open** — so a naive scrape both invents four threads and, worse, shadows the
  real row for the open one. A conversation is an anchor inside a
  `[role=row]`; filter on that before deduping by URL.
- Message rows read as `"<sender> <body> Enter, Message sent HH:MM by
  <sender>: <body>"` — the body twice, plus the label of the reply button that
  only exists on hover. `GET /messenger/messages` strips all three.
