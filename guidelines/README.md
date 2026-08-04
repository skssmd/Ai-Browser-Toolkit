# Guidelines

Experience-backed playbooks for driving real sites with the AI Browser Toolkit.
The point of this folder: a fresh agent should understand the *concepts* from
these notes and skip the trial-and-error that produced them.

## How to use these

> **If you read one file here, read [`toolkit-workflow.md`](toolkit-workflow.md).**
> **Most sites have no playbook, and that is the normal case — not a dead end.**
> Finding nothing for your site below does not mean there is no guidance for
> it. It means `toolkit-workflow.md` *is* the guidance, and it is enough to
> drive an ordinary site well. Read it and proceed.

1. Read `toolkit-workflow.md` — **always, before anything else**. It is the
   concepts of driving the toolkit: ops, targeting, refs, reading the DOM diff
   instead of re-reading the page, batching, verification. This is where the
   expensive habits get fixed, and it applies to every site that will ever
   exist.
2. *Then*, only if the site you are touching has a playbook below, read that
   one too.
3. Site-specific playbooks exist for sites that broke the normal rules —
   canvas-rendered editors, offscreen iframes, stale exports. They are
   additions to step 1, never replacements for it.

**The failure this is written to prevent:** an agent looks for its site, finds
no entry, concludes the folder has nothing to offer, and goes on to rediscover
by trial and error that `find` returns refs, that a click already tells you what
changed, and that ops can be batched. All of that is in step 1.

## Index

Your site is probably not in this table. That is expected — see above; read
`toolkit-workflow.md` and drive the site with the ordinary ops.

| File | When to read it |
|---|---|
| `toolkit-workflow.md` | **Always, every session, whatever the site** — how the toolkit thinks |
| `google-docs.md` | Driving docs.google.com (rich paste, headings, tables, verification) |
| `google-sheets.md` | Driving sheets.google.com (canvas grid, name box, formulas, menus, charts) |
| `fojik-mlwbd.md` | Finding and downloading movies on fojik.site/MLWBD (WordPress search, verify gauntlet, boabd/R2) |
| `kayoanime.md` | Finding and downloading anime on kayoanime.com (WordPress search, Google Group, private Drive folders, virus-scan dialog) |
| `messenger.md` | Reading and replying on messenger.com, normal + E2EE threads, sending images/files through the hidden file input (contenteditable composer, multi-attachment) |

Docs and Sheets share the canvas problem but not the workaround: Docs is driven
by clipboard paste into the body, Sheets by the name box and formula bar. Read
the one you need, not both.

## Adding a playbook

After you have fought a site to the finish, write down the wins so nobody
fights it again. Keep it short and specific: what breaks, and the exact
command shapes that work. Update `toolkit-workflow.md` with any general
lesson that applies beyond one site.
