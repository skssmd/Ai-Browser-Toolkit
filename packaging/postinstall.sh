#!/bin/sh
# The app-menu entry: most desktops notice it at once, some only after these
# caches are refreshed. Best effort -- a server without them loses nothing.
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true

cat <<'EOF'
AI Browser Toolkit installed. Open it from your app menu: "AI Browser Toolkit".

Check what it needs and whether you have it:
    abt doctor

It drives an existing Google Chrome or Microsoft Edge and bundles neither.
On Linux `abt doctor` prints the install command rather than running it --
every route to Chrome here needs root, and this package will not ask for it.

To start the server at logon:
    abt autostart install --browser chrome
EOF
