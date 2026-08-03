# Guidelines

Experience-backed playbooks for driving real sites with the AI Browser Toolkit.
The point of this folder: a fresh agent should understand the *concepts* from
these notes and skip the trial-and-error that produced them.

## How to use these

1. Read `toolkit-workflow.md` first — the concepts of driving the toolkit
   (ops, targeting, refs, DOM diffs, batching, verification).
2. Then read the playbook for the site you are about to touch.
3. Site-specific playbooks capture the *traps*: canvas-rendered editors,
   offscreen iframes, stale exports, and the workarounds that work.

## Index

| File | When to read it |
|---|---|
| `toolkit-workflow.md` | Before every session — how the toolkit thinks |
| `google-docs.md` | Driving docs.google.com (rich paste, headings, tables, verification) |
| `google-sheets.md` | Driving sheets.google.com (canvas grid, name box, formulas, menus, charts) |
| `fojik-mlwbd.md` | Finding and downloading movies on fojik.site/MLWBD (WordPress search, verify gauntlet, boabd/R2) |

Docs and Sheets share the canvas problem but not the workaround: Docs is driven
by clipboard paste into the body, Sheets by the name box and formula bar. Read
the one you need, not both.

## Adding a playbook

After you have fought a site to the finish, write down the wins so nobody
fights it again. Keep it short and specific: what breaks, and the exact
command shapes that work. Update `toolkit-workflow.md` with any general
lesson that applies beyond one site.
