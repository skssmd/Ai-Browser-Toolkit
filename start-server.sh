#!/usr/bin/env bash
# ============================================================================
#  start-server.sh -- bring the AI Browser Toolkit server up, safely.
#  Linux, macOS, and Windows (Git Bash / WSL). Windows cmd users: start-server.bat
#
#  `abt serve` never returns; running it inside an agent's tool call wedges that
#  call forever. This script launches it DETACHED with its output redirected to
#  a file (so no inherited pipe is held open), then polls /status until the
#  server answers and exits. Always safe to run: if a server is already up it
#  changes nothing and exits 0.
#
#  Usage:
#    ./start-server.sh                 check, install deps, start, wait for ready
#    ./start-server.sh --status        only report whether the server is up
#    ./start-server.sh --no-wait       start and return immediately (no polling)
#    ./start-server.sh --browser edge --port 9000 --headless
#                                      any other flags are passed to `abt serve`
#
#  Exit codes: 0 = server is up   1 = failed to come up   2 = deps failed
# ============================================================================

set -u

REPO="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
VENV="$REPO/.venv"
OUTLOG="$REPO/server.log"
ERRLOG="$REPO/server.err"

PORT=8765
BROWSER=chrome
MODE=start
NOWAIT=
ARGS=()
# No browser is launched at startup any more, so the server answers in about a
# second. The old 180s budget existed only to cover Chrome on a cold profile.
WAIT_SECONDS=30

while [ $# -gt 0 ]; do
    case "$1" in
        --status)  MODE=status; shift ;;
        --no-wait) NOWAIT=1; shift ;;
        --port|-p) PORT="$2"; ARGS+=(--port "$2"); shift 2 ;;
        --browser) BROWSER="$2"; shift 2 ;;
        *)         ARGS+=("$1"); shift ;;
    esac
done

STATUS_URL="http://127.0.0.1:$PORT/health"

# A server on a non-default port gets its own log files, so starting one never
# truncates the logs of the server already running on 8765.
if [ "$PORT" != 8765 ]; then
    OUTLOG="$REPO/server-$PORT.log"
    ERRLOG="$REPO/server-$PORT.err"
fi

# Windows keeps the executables in .venv/Scripts, everyone else in .venv/bin.
if [ -d "$VENV/Scripts" ]; then
    VBIN="$VENV/Scripts"; EXT=".exe"
else
    VBIN="$VENV/bin"; EXT=""
fi
VPY="$VBIN/python$EXT"
ABT="$VBIN/abt$EXT"

probe() {
    if command -v curl > /dev/null 2>&1; then
        curl -s -m 5 -o /dev/null "$STATUS_URL"
    elif command -v wget > /dev/null 2>&1; then
        wget -q -T 5 -O /dev/null "$STATUS_URL"
    else
        # No HTTP client: fall back to the venv's Python.
        "$VPY" -c "import sys,urllib.request; urllib.request.urlopen('$STATUS_URL', timeout=5)" \
            > /dev/null 2>&1
    fi
}

# --- 1. is it already running? ----------------------------------------------
if probe; then
    echo "[abt] Server already running on 127.0.0.1:$PORT -- nothing to do."
    exit 0
fi

if [ "$MODE" = status ]; then
    echo "[abt] No server on 127.0.0.1:$PORT."
    exit 1
fi

echo "[abt] No server on 127.0.0.1:$PORT -- starting one."

# --- 2. dependencies --------------------------------------------------------
if [ ! -x "$VPY" ]; then
    echo "[abt] Creating virtualenv at $VENV ..."
    BASEPY=
    for candidate in python3 python py; do
        if command -v "$candidate" > /dev/null 2>&1 && "$candidate" -c "import sys" > /dev/null 2>&1; then
            BASEPY="$candidate"
            break
        fi
    done
    if [ -z "$BASEPY" ]; then
        echo "[abt] ERROR: no Python found on PATH. Install Python 3.11+ first." >&2
        exit 2
    fi
    if ! "$BASEPY" -m venv "$VENV"; then
        echo "[abt] ERROR: could not create the virtualenv." >&2
        exit 2
    fi
    # Re-resolve: the layout is only knowable once the venv exists.
    if [ -d "$VENV/Scripts" ]; then VBIN="$VENV/Scripts"; EXT=".exe"; else VBIN="$VENV/bin"; EXT=""; fi
    VPY="$VBIN/python$EXT"
    ABT="$VBIN/abt$EXT"
fi

# Cheap import check -- if the package and its deps resolve, skip pip entirely.
NEED_INSTALL=
[ -x "$ABT" ] || NEED_INSTALL=1
if [ -z "$NEED_INSTALL" ]; then
    "$VPY" -c "import abt, selenium, fastapi, uvicorn, pydantic, httpx, typer" > /dev/null 2>&1 \
        || NEED_INSTALL=1
fi

if [ -n "$NEED_INSTALL" ]; then
    echo "[abt] Installing dependencies (editable install of $REPO) ..."
    "$VPY" -m pip install --quiet --upgrade pip
    if ! "$VPY" -m pip install --quiet -e "$REPO"; then
        echo "[abt] ERROR: pip install failed." >&2
        exit 2
    fi
    if ! "$VPY" -c "import abt, selenium, fastapi, uvicorn, pydantic, httpx, typer" > /dev/null 2>&1; then
        echo "[abt] ERROR: dependencies still missing after install." >&2
        exit 2
    fi
    echo "[abt] Dependencies OK."
else
    echo "[abt] Dependencies already satisfied."
fi

# --- 3. launch detached -----------------------------------------------------
# setsid/nohup plus the redirects are what keep the caller from being held open
# by a process that never exits: nothing inherits this script's stdout/stderr.
echo "[abt] Launching: abt serve --browser $BROWSER ${ARGS[*]:-}"
if command -v setsid > /dev/null 2>&1; then
    setsid "$ABT" serve --browser "$BROWSER" ${ARGS[@]+"${ARGS[@]}"} \
        > "$OUTLOG" 2> "$ERRLOG" < /dev/null &
else
    nohup "$ABT" serve --browser "$BROWSER" ${ARGS[@]+"${ARGS[@]}"} \
        > "$OUTLOG" 2> "$ERRLOG" < /dev/null &
fi
SERVER_PID=$!
disown "$SERVER_PID" 2> /dev/null || true

if [ -n "$NOWAIT" ]; then
    echo "[abt] Launched detached (pid $SERVER_PID). Check readiness with: $0 --status"
    exit 0
fi

# --- 4. poll until ready ----------------------------------------------------
echo "[abt] Waiting up to ${WAIT_SECONDS}s for $STATUS_URL ..."
tries=$(( WAIT_SECONDS / 2 ))
i=0
while [ "$i" -lt "$tries" ]; do
    sleep 2
    if probe; then
        echo "[abt] Server is up on 127.0.0.1:$PORT."
        exit 0
    fi
    if ! kill -0 "$SERVER_PID" 2> /dev/null; then
        echo "[abt] ERROR: the server process exited." >&2
        break
    fi
    i=$(( i + 1 ))
done

echo "[abt] ERROR: server did not answer within ${WAIT_SECONDS}s." >&2
echo "[abt] --- last lines of $ERRLOG ---" >&2
[ -f "$ERRLOG" ] && tail -n 20 "$ERRLOG" >&2
exit 1
