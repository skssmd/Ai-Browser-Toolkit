# Messenger (hidden, reference only)

The toolkit had a Messenger shortcut: HTTP routes under `/messenger/*` (send,
read threads and messages, background send jobs), `abt messenger` commands, and
a messenger.com site playbook. It is taken out of the product for now: automating
a Meta account this way is against Messenger's terms, so nothing in `src/`,
`tests/` or `guidelines/` exposes or loads it. It lives outside `src/`, so the
wheel, the bundles and the installer never carry it.

| File | What it was |
|---|---|
| `messenger.py` | `src/abt/messenger.py`: send, list threads, read messages, the job and cursor registries. |
| `server_routes.py` | The Messenger part of `create_app` in `src/abt/server.py`: the registries and the `/messenger/*` routes. |
| `cli_commands.py` | The `abt messenger send/threads/read/jobs` commands from `src/abt/cli.py`. |
| `test_messenger.py`, `messenger.html` | Its tests and their fixture page, and the per-session jobs test. |
| `guidelines-messenger.com/` | The site playbook, formerly `guidelines/messenger.com/`. |

## Putting it back

1. Move `messenger.py` back to `src/abt/`, and its tests and fixture to `tests/`.
2. Paste the two parts of `server_routes.py` back into `create_app`, and import
   `from . import messenger as messenger_api`.
3. Paste `cli_commands.py` back into `src/abt/cli.py` (it needs
   `from urllib.parse import urlencode`), and add `"messenger"` back to the
   subcommand list in `tests/test_surface_parity.py`.
4. Move the playbook back to `guidelines/messenger.com/` and restore its entry in
   `guidelines/index.json`; add `"messenger_send"` back to `shots.py`'s ops that
   record a frame.
