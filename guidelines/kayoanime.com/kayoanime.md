# Kayoanime playbook

How to find and download anime on `kayoanime.com` with the toolkit. Everything
here was verified on live sessions; follow it and skip the trial-and-error.

## What you are actually driving

- `kayoanime.com` is a WordPress front-end. No download forms here �?" the
  actual content lives in **Google Drive folders** ("private drives"), and the
  post links to them directly.
- The private drives sit behind a **Google Group**. The post says: "To access
  the private drive just open [Google Group] and join, ignore the rest."
- Not every folder is actually locked. In practice the *box* folders
  (`BOX 1/2/3`, `1080p [Private Drive]`) are denied, but the per-show folders
  (`Movie`, `OVAs`, `Thousand-Year Blood War`, etc.) are often shared publicly.
  **Try the folders one by one before giving up.**

## Finding something

Plain WordPress search �?" drive it by URL, no need to touch the search box:

```
goto https://kayoanime.com/?s=black+clover
```

Search terms are space-separated (`+` or `%20`). One-word searches are
case-insensitive but literal (`dragonball` vs `dragon ball` return different
result sets �?" search both). Results are batch posts, one per series:

```
Black Clover (Seasons 1-4 + Movie + OVAs) 1080p Dual Audio HEVC
```

The post title is the link. Extract the href with `run_js` over `a` elements,
then `goto` it (anchor `.textContent` contains the full title, the `href` is
`https://kayoanime.com/<slug>/`).

## The post page

- Info table (Type, Status, Aired, Genres, ...) at the top.
- Download section with a Google Group link and the drive links. Survey with
  `run_js` over `a` and keep the `drive.google.com/drive/folders/<id>` targets:

  ```
  Google Group           -> https://tinyurl.com/9yh733xs
  1080p [Private Drive]  -> https://drive.google.com/drive/folders/14BM8MC...
  Movie                  -> https://drive.google.com/drive/folders/1yb5OiO...
  OVAs                   -> https://drive.google.com/drive/folders/1fwrzm6...
  ```

## Joining the Google Group (only if a folder needs it)

The Group link resolves to
`groups.google.com/g/kayoanime-naruto-shippuden/c/mJvLAi43420`. Not signed in,
the page shows "You don't have permission to access this content" plus a
**Join group** button.

The join flow is a page dialog (visible in the diff):

```json
{"op": "run_js", "script": "// find the 'Join group' button and click it"}
```

A dialog opens: display name, a subscription radio group (Each email / Digest /
Abridged / **No email**), a "Subscribe me to email updates" checkbox, and
Cancel / Join group buttons. Pick "No email" and confirm.

Joining does **not** guarantee folder access �?" the locked `BOX`/`Private
Drive` folders may still return "You need access". Don't block on the group;
jump straight to the accessible folders instead.

## Drive folder access check

`goto` the folder. Two outcomes, both readable from the diff:

- **Access Denied**: "You need access / Request access, or switch to an
  account with access." -> move on to the next folder.
- **Open**: title is "Folder - Google Drive". List the contents. File rows are
  `[data-id]` elements; the names often do not come through `aria-label`, so
  read them from `document.body.innerText` (lines ending in `.mkv`):

  ```
  Black Clover - Sword of the Wizard King [1080p][HEVC x265 10bit][Dual-Audio][Multi-Subs].mkv
  ```

## Downloading a file

Open the row menu (the **kebab** on the file row):

```json
{"op": "run_js", "script": "// button[aria-label*='More actions'] scoped inside the row's [data-id]"}
```

Scoped is the key word �?" the page-level `[aria-label="More actions"]` opens
the folder's own menu (Sort by / Help), not the file's. Click the row's kebab,
then the **Download** menuitem. In the row menu there are two items: "Download
original" and "Download"; either gets the file.

## The virus-scan dialog (files over ~2GB)

Files bigger than Google's scan limit open a **page-level** dialog (not a
native alert, so it shows up in `body.innerText` / the diff):

```
Can't scan file for viruses
"<name>" (2.6GB) exceeds the maximum file size that Google can scan.
This file might harm your computer, so only download this file if you
understand the risks.
```

Find it by text and click **Download anyway**:

```json
{"op": "run_js", "script": "// div containing 'exceeds the maximum file size' -> its button 'Download anyway'.click()"}
```

The dialog container has class `lb-k`; its buttons are Cancel / Download
anyway.

## After the click

- The file downloads to the browser's default Downloads folder. The toolkit
  cannot read download progress back �?" verify by listing the OS Downloads dir
  (`Downloads/*.mkv`, or `*.crdownload` while in flight).
- A native JS dialog (rare on Drive) would need the `alert` op; the Drive
  virus-scan prompt is NOT one of those.

## Traps

- `dragonball` vs `dragon ball` are different searches on the same site.
- The page-level "More actions" menu is not the row menu. Always scope the
  kebab lookup to the file's `[data-id]` row.
- `BOX 3` may point at the same folder as `BOX 2` (duplicate link) �?" don't
  waste a cycle on it.
- The Google Group name (Naruto Shippuden) is a red herring: every post uses
  the same group link.
- Some screenshots/models cannot read images; rely on `dom_diff` text instead
  of `screenshot` for prompt detection.
