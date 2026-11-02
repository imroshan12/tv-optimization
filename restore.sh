#!/usr/bin/env bash
# Undo setup.sh, using the record it kept in state/.
#
# Usage: ./restore.sh <device ip:port>          re-enable what it disabled, remove what it installed
#        ./restore.sh <device ip:port> --keep   re-enable what it disabled, keep the launcher and AirPlay
set -euo pipefail
cd "$(dirname "$0")"
T="${1:?usage: restore.sh <device ip:port> [--keep]}"
adb connect "$T" >/dev/null 2>&1 || true
[ "$(adb -s "$T" get-state 2>/dev/null)" = device ] || { echo "cannot reach $T: is Wireless debugging on?" >&2; exit 1; }

if [ -f state/disabled.txt ]; then
  sort -u state/disabled.txt | while read -r pkg; do
    adb -s "$T" shell pm enable --user 0 "$pkg" </dev/null
  done
else
  echo "no state/disabled.txt: this copy of the repo disabled nothing"
fi

if [ "${2:-}" != "--keep" ] && [ -f state/installed.txt ]; then
  # Only the apps setup.sh installed. Nothing that came with the device is ever uninstalled.
  while read -r pkg; do
    adb -s "$T" shell pm uninstall "$pkg" </dev/null || true
  done < state/installed.txt
fi

echo
echo "Done. Still disabled on the device, which may include what it shipped with:"
adb -s "$T" shell pm list packages -d
