#!/bin/sh
# Prove a freshly built bundle actually runs.
#
# This is the reason the build matrix is native rather than one host
# cross-building five targets: the relocated interpreter, the launcher shim,
# and Playwright's Node driver import are the three things that break
# silently, and all three are exercised by starting the server.
#
# Verified by hand on windows-x86_64 before this file existed: built in the
# repo, unpacked in an unrelated directory, server answered /status in six
# seconds with its profile under %LOCALAPPDATA%.
set -eu

dir="$1"
if [ -f "$dir/abt.cmd" ]; then
    abt="$dir/abt.cmd"
else
    abt="$dir/bin/abt"
fi

"$abt" --version

# Proves doctor works from inside a bundle, where paths.py and the relocated
# interpreter are both in play. Exit code is ignored on purpose: doctor exits
# non-zero when no browser is present, and whether a runner has one is not
# what this test is about.
"$abt" doctor --json || true

# From the PID, not $RANDOM: this is /bin/sh, where dash leaves $RANDOM unset
# and any fallback constant collides with a server the developer already has
# running. Concatenating $RANDOM onto a prefix also overflows -- 8 + 32767 is
# port 832767, which bind() rejects outright.
port=$((20000 + $$ % 20000))

# --browser is stated explicitly and --no-start-browser is mandatory.
# `abt serve` prompts when --browser is missing and stdin is a tty, and a
# runner that prompts waits forever -- see src/abt/autostart.py's docstring,
# where the same trap is recorded for logon tasks.
"$abt" serve --browser chrome --no-start-browser --port "$port" >smoke.log 2>&1 &

i=0
while [ $i -lt 60 ]; do
    if curl -fsS "http://127.0.0.1:$port/status" >/dev/null 2>&1; then
        "$abt" shutdown --port "$port"
        echo "smoke test passed on port $port"
        exit 0
    fi
    i=$((i + 1))
    sleep 1
done

echo "server never answered on port $port"
cat smoke.log
exit 1
