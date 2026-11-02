#!/usr/bin/env bash
# Clean up an Android TV / Google TV device: disable background apps, add a home screen with one
# character per app, and add AirPlay so a Mac can mirror to it. Everything can be undone with restore.sh.
#
# Run it in an ordinary terminal, on the same network as the device:
#   ./setup.sh <device ip:port> --dry-run     report what it would do, change nothing
#   ./setup.sh <device ip:port>               asks before each step
#
# Options: --yes  accept the steps, keeping every optional app
#          --list <file>  disable this list instead of lists/ (a tested list for your model)
#          --no-debloat  --no-launcher  --no-airplay
set -euo pipefail
cd "$(dirname "$0")"
ROOT=$PWD

# The versions this was tested with. Change them only together with a new test on a device.
CLEANYOURTV_URL=https://github.com/Gathin23/cleanyourtv
CLEANYOURTV_COMMIT=572ce2cbe98b53654cea3d262ee8558a5872dfd1
AIRPLAY_URL=https://github.com/jqssun/android-airplay-server/releases/download/v0.0.36/app-release.apk
AIRPLAY_SHA256=b8c7c595ed93f91562feedce92c27800f08f9c84df424f6ac2045e82324cf2a4

# Never disabled by this script. On Google TV the setup wizard owns the Wi-Fi saved at first setup and holds
# the Google Cast credentials, so disabling it can drop Wi-Fi and break casting.
KEEP_RE='^(com\.google\.android\.tungsten\.setupwraith|com\.google\.android\.apps\.tv\.launcherx|com\.google\.android\.apps\.mediashell|com\.android\.vending|com\.google\.android\.gms)$'

TARGET="" DRY=0 YES=0 LIST="" DEBLOAT=1 LAUNCHER=1 AIRPLAY=1
NOT_DISABLED=0 DID_LAUNCHER=0 AIRPLAY_NAME=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --yes) YES=1 ;;
    --list) LIST="${2:?--list needs a file}"; shift ;;
    --no-debloat) DEBLOAT=0 ;;
    --no-launcher) LAUNCHER=0 ;;
    --no-airplay) AIRPLAY=0 ;;
    -h|--help) sed -n 2,11p "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "unknown option: $1" >&2; exit 2 ;;
    *) TARGET=$1 ;;
  esac
  shift
done
[ -n "$TARGET" ] || { echo "usage: ./setup.sh <device ip:port> [--dry-run] (see --help)" >&2; exit 2; }
[[ "$TARGET" == *:* ]] || { echo "give the port as well: the one on the device's Wireless debugging screen" >&2; exit 2; }

say() { printf '\n== %s\n' "$*"; }
die() { printf 'stopped: %s\n' "$*" >&2; exit 1; }
ask() { [ "$YES" = 1 ] && return 0; local a; read -r -p "$1 [y/N] " a </dev/tty; [[ "$a" =~ ^[Yy] ]]; }
# Disabling an app someone may use is opt-in: --yes keeps them.
ask_optional() { [ "$YES" = 1 ] && return 1; local a; read -r -p "$1 [y/N] " a </dev/tty; [[ "$a" =~ ^[Yy] ]]; }
A() { adb -s "$TARGET" shell "$@" </dev/null; }
wait_for_tv() { for _ in 1 2 3 4 5; do [ "$(adb -s "$TARGET" get-state 2>/dev/null)" = device ] && return 0; sleep 2; done; return 1; }

mkdir -p state build .cache

# ---------- checks ----------
say "Checking this computer and the device"
command -v adb >/dev/null || die "adb is missing (macOS: brew install --cask android-platform-tools)"
command -v python3 >/dev/null || die "python3 is missing"
command -v git >/dev/null || die "git is missing"
adb connect "$TARGET" >/dev/null 2>&1 || true
if ! wait_for_tv; then
  echo "Could not reach $TARGET. Check that:"
  echo "  - Wireless debugging is on, and this is the port on its main screen"
  echo "  - you have paired once: adb pair <ip>:<pairing port>"
  echo "  - on macOS, your terminal is allowed under System Settings > Privacy & Security > Local Network"
  exit 1
fi
SDK=$(A getprop ro.build.version.sdk | tr -d '\r')
MODEL=$(A getprop ro.product.model | tr -d '\r')
MEM_KB=$(A cat /proc/meminfo | awk '/MemTotal/{print $2}')
A pm list features | grep -q 'android.software.leanback' || die "this is not an Android TV device; nothing changed"
[ "${SDK:-0}" -ge 26 ] || die "Android SDK $SDK is too old for the launcher (it needs 26); nothing changed"
HOME_ACTIVITY=$(A cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.HOME | tail -n 1 | tr -d '\r')
HOME_PKG=${HOME_ACTIVITY%%/*}
# A second run finds our launcher as Home: the stock one was noted the first time.
if [ "$HOME_PKG" = com.gathin.tvhome ] && [ -f state/stock-home.txt ]; then HOME_PKG=$(cat state/stock-home.txt); fi
echo "Device: $MODEL, SDK $SDK, $((MEM_KB / 1024)) MB RAM, Home: $HOME_PKG"

# ---------- what would be disabled ----------
A pm list packages -e | sed 's/package://' | tr -d '\r' | sort > build/enabled.txt
# Package names from a list file that are enabled on this device and are not protected.
from_list() {
  { grep -vE '^\s*(#|$)' "$1" || true; } | awk '{print $1}' | sort -u | comm -12 - build/enabled.txt \
    | { grep -vE "$KEEP_RE" || true; } | { grep -vFx "$HOME_PKG" || true; }
}
if [ -n "$LIST" ]; then
  from_list "$LIST" > build/recommended.txt
else
  cat lists/telemetry.txt lists/features.txt > build/all.txt
  from_list build/all.txt > build/recommended.txt
fi
from_list lists/optional-apps.txt > build/optional.txt
say "Recommended to disable on this device ($(wc -l < build/recommended.txt | tr -d ' '))"
sed 's/^/  /' build/recommended.txt
say "Your choice, one at a time ($(wc -l < build/optional.txt | tr -d ' '))"
while read -r p; do printf '  %s\n' "$(grep -m1 "^$p" lists/optional-apps.txt)"; done < build/optional.txt

if [ "$DRY" = 1 ]; then
  say "Dry run: nothing was changed"
  echo "Launcher: $([ "$LAUNCHER" = 1 ] && echo "would install; $HOME_PKG stays enabled" || echo skipped)"
  echo "AirPlay: $([ "$AIRPLAY" = 1 ] && echo "would download and install $AIRPLAY_URL" || echo skipped)"
  exit 0
fi

# ---------- backup ----------
say "Backing up"
STAMP=$(date +%Y%m%d-%H%M%S)
BK=backup/$STAMP
mkdir -p "$BK"
A pm list packages -f > "$BK/packages.txt"
A pm list packages -d > "$BK/disabled.txt"
A getprop > "$BK/getprop.txt"
for ns in global secure system; do A settings list "$ns" > "$BK/settings-$ns.txt"; done
[ -f state/stock-home.txt ] || echo "$HOME_PKG" > state/stock-home.txt
echo "Saved to $BK. It holds details of your device: keep it private."

# ---------- cleanyourtv, at the tested version, with the per-app picture patch ----------
UP=.cache/cleanyourtv
if [ ! -d "$UP/.git" ]; then
  say "Fetching cleanyourtv"
  git clone -q "$CLEANYOURTV_URL" "$UP"
fi
git -C "$UP" checkout -q -f "$CLEANYOURTV_COMMIT"
git -C "$UP" clean -qfd launcher/app/src
git -C "$UP" apply "$ROOT/launcher/app-art.patch"
[ -x "$UP/tools/venv/bin/python" ] || python3 -m venv "$UP/tools/venv"
"$UP/tools/venv/bin/pip" install -q --disable-pip-version-check -r "$UP/tools/requirements.txt"
export TV_ADB_BINARY TV_HOST
TV_ADB_BINARY=$(command -v adb)
TV_HOST=$TARGET

# ---------- debloat ----------
disable_list() {   # file: goes through cleanyourtv's script, which refuses core packages
  [ -s "$1" ] || return 0
  A pm list packages -d | sed 's/package://' | tr -d '\r' | sort > build/before.txt
  local out status=0 missing
  out=$(cd "$UP" && tools/disable.sh "$ROOT/$1" 2>&1) || status=$?
  printf '%s\n' "$out" | grep -E 'new state' || true
  A pm list packages -d | sed 's/package://' | tr -d '\r' | sort > build/after.txt
  comm -13 build/before.txt build/after.txt >> state/disabled.txt
  # cleanyourtv's safety checks can skip a package or refuse a list. That must be seen, never read as success.
  missing=$(sort -u "$1" | comm -23 - build/after.txt)
  if [ "$status" != 0 ] || [ -n "$missing" ]; then
    NOT_DISABLED=$((NOT_DISABLED + $(printf '%s\n' "$missing" | grep -c . || true)))
    echo "WARNING: not everything in this batch was disabled:"
    printf '%s\n' "$missing" | sed 's/^/  /'
    echo "What the safety check said:"
    printf '%s\n' "$out" | grep -v 'new state' | tail -8 | sed 's/^/  /'
  fi
  sleep 3
  wait_for_tv || die "the device stopped answering. Its record is in state/disabled.txt; see README, Undo"
}
if [ "$DEBLOAT" = 1 ]; then
  if ask "Disable the recommended packages listed above?"; then
    split -l 8 build/recommended.txt build/batch-
    for batch in build/batch-*; do disable_list "$batch"; rm -f "$batch"; done
  fi
  : > build/chosen.txt
  while read -r p <&3; do
    ask_optional "Disable $(grep -m1 "^$p" lists/optional-apps.txt)?" && echo "$p" >> build/chosen.txt
  done 3< build/optional.txt
  disable_list build/chosen.txt
  # Android writes package state to disk about ten seconds after a change.
  sleep 15
fi

# ---------- launcher and theme ----------
if [ "$LAUNCHER" = 1 ] && ask "Build and install the character home screen?"; then
  say "Building the launcher (needs JDK 17 and Android SDK platform 34)"
  APK=$UP/launcher/app/build/outputs/apk/release/app-release.apk
  rm -f "$APK"
  # STOCK_LAUNCHER=none disables nothing. The script then reports Home as not switched, which is expected:
  # the stock launcher keeps Home and the launcher's Home button helper redirects from it.
  (cd "$UP/launcher" && STOCK_LAUNCHER=none bash build-and-install.sh) 2>&1 | tr '\r' '\n' | grep -vE 'chunk [0-9]+/' | tail -6 || true
  [ -f "$APK" ] || die "the launcher did not build. Check JDK 17 and SDK platform 34, see README"
  A pm path com.gathin.tvhome | grep -q package: || die "the launcher did not install; Home was left alone"
  grep -qx com.gathin.tvhome state/installed.txt 2>/dev/null || echo com.gathin.tvhome >> state/installed.txt

  say "Drawing the pictures"
  [ -x .cache/artvenv/bin/python ] || python3 -m venv .cache/artvenv
  .cache/artvenv/bin/pip install -q --disable-pip-version-check -r art/requirements.txt
  rm -rf build/theme; mkdir -p build/theme/wallpapers
  .cache/artvenv/bin/python art/make_avatars.py build/theme/wallpapers >/dev/null
  [ -f pictures/pictures.json ] && .cache/artvenv/bin/python art/make_real.py pictures/pictures.json pictures build/theme/wallpapers
  sed "s/@STOCK_HOME@/$HOME_PKG/" theme/config.template.json > build/theme/config.json
  (cd "$UP" && tools/theme.sh "$ROOT/build/theme") 2>&1 | tr '\r' '\n' | grep -vE 'chunk [0-9]+/' | tail -1
  DID_LAUNCHER=1
fi

# ---------- AirPlay ----------
if [ "$AIRPLAY" = 1 ] && ask "Download and install the AirPlay receiver for Mac mirroring ($AIRPLAY_URL)?"; then
  say "Installing AirPlay"
  APK=.cache/airplay-v0.0.36.apk
  [ -f "$APK" ] || curl -fsSL -m 300 -o "$APK" "$AIRPLAY_URL"
  GOT=$(shasum -a 256 "$APK" 2>/dev/null | awk '{print $1}')
  [ "$GOT" = "$AIRPLAY_SHA256" ] || { rm -f "$APK"; die "the AirPlay download does not match the tested file; not installing it"; }
  adb -s "$TARGET" push "$APK" /data/local/tmp/airplay.apk >/dev/null
  A pm install -r /data/local/tmp/airplay.apk | tail -n 1
  A rm -f /data/local/tmp/airplay.apk
  A pm path io.github.jqssun.airplay | grep -q package: || die "AirPlay did not install"
  grep -qx io.github.jqssun.airplay state/installed.txt 2>/dev/null || echo io.github.jqssun.airplay >> state/installed.txt
  # A receiver named exactly like the device loses mirroring on Android 14, so the name always differs.
  DEVICE=$(A settings get global device_name | tr -d '\r' | LC_ALL=C tr -cd 'A-Za-z0-9 _-')
  NAME="${DEVICE:-TV} Screen"
  set_airplay() { A "am broadcast -n io.github.jqssun.airplay/.SettingsReceiver -a io.github.jqssun.airplay.SET_SETTING --es key $1 --es value '$2'" >/dev/null; }
  A am start -n io.github.jqssun.airplay/.MainActivity >/dev/null; sleep 4
  set_airplay server_name "$NAME"
  [ "$MEM_KB" -lt 1500000 ] && set_airplay max_fps 30
  A am force-stop io.github.jqssun.airplay
  A am start -n io.github.jqssun.airplay/.MainActivity >/dev/null
  AIRPLAY_NAME=$NAME
fi

# ---------- what happened, and what is left for the person ----------
say "Summary"
echo "Disabled by this tool so far: $(sort -u state/disabled.txt 2>/dev/null | grep -c . || true) packages (state/disabled.txt)"
[ "$NOT_DISABLED" = 0 ] || echo "NOT disabled this run: $NOT_DISABLED packages. See the warnings above."
[ "$DID_LAUNCHER" = 1 ] && echo "Home screen: installed" || echo "Home screen: not changed"
if [ -n "$AIRPLAY_NAME" ]; then
  echo "AirPlay: installed. On your Mac, choose Control Center > Screen Mirroring > $AIRPLAY_NAME"
else
  echo "AirPlay: not changed"
fi

say "Left for you to do"
if [ "$DID_LAUNCHER" = 1 ]; then
  cat <<EOF
- On the device, turn on the helper that sends the Home button to the new home screen:
  Settings > Accessibility > Home button (the menu path can differ).
- Press Home inside an app, and try each remote button you rely on. See README, Known limits.
EOF
fi
cat <<EOF
- Close debugging. On the device, set Wireless debugging to Disabled, then run:
    python3 -I $ROOT/$UP/tools/adb-closed.py ${TARGET%:*} ${TARGET##*:}
  Then revoke the USB debugging authorisations, turn USB debugging off, restart, and run:
    python3 -I $ROOT/$UP/tools/adb-closed.py ${TARGET%:*}
  Both should say the port is closed.

Undo at any time: ./restore.sh <device ip:port>
EOF
