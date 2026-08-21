#!/bin/sh
# Leave no systemd user unit pointing at files that are about to vanish.
abt autostart uninstall >/dev/null 2>&1 || true
exit 0
