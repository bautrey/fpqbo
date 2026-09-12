#!/bin/bash
# Install the new-customer watcher as a user LaunchAgent.
#
# Run this after a fresh clone, a reinstall, or on a new machine. Without it the
# watcher script sits in the repo and nothing ever runs it — which is not a
# hypothetical: the watcher spent 2026-09-09 to 2026-09-12 scheduled under cron
# and never once executed, and the log read as "nothing happening" the whole time.
#
# It must be a LaunchAgent rather than a cron entry. cron runs in the "Background"
# security session, where the default keychain is System.keychain and the login
# keychain is not in the search list, so `security find-generic-password` returns
# 44. An explicit keychain path, `list-keychains -d user` and `unlock-keychain`
# all return 36. There is no cron-side workaround. A user LaunchAgent runs in the
# Aqua session and can read the login keychain.

set -euo pipefail
LABEL=com.burkeautrey.fpqbo.watch-new-customers
SRC="$(cd "$(dirname "$0")" && pwd)/$LABEL.plist"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"

[ -f "$SRC" ] || { echo "missing $SRC" >&2; exit 1; }
mkdir -p "$HOME/Library/LaunchAgents"
cp "$SRC" "$DEST"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$DEST"

echo "installed $LABEL"
echo "verify:  launchctl print gui/$(id -u)/$LABEL | grep 'last exit code'"
echo "alive?:  cat \"$(git rev-parse --show-toplevel)/docs/scratch/.watch-last-success\""
echo "remove:  launchctl bootout gui/$(id -u)/$LABEL && rm \"$DEST\""
