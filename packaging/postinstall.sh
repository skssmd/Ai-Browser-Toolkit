#!/bin/sh
cat <<'EOF'
AI Browser Toolkit installed.

Check what it needs and whether you have it:
    abt doctor

It drives an existing Google Chrome or Microsoft Edge and bundles neither.
On Linux `abt doctor` prints the install command rather than running it --
every route to Chrome here needs root, and this package will not ask for it.

To start the server at logon:
    abt autostart install --browser chrome
EOF
