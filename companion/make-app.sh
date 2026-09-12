#!/bin/bash
#
# Wraps the SwiftPM binary in a .app bundle so macOS keeps the camera / mic /
# speech / accessibility permissions we grant it. `swift run` produces a bare
# binary with no Info.plist and no stable code signature, so TCC drops it on
# every rebuild. This bundle carries packaging/Info.plist +
# packaging/GaizeCompanion.entitlements and an ad-hoc signature with a FIXED
# identifier, so the grant sticks across rebuilds.
#
# Usage:
#   ./make-app.sh            # debug build (default)
#   ./make-app.sh release    # release build
#   ./make-app.sh && open Gaize.app
#
set -euo pipefail

CONFIG="${1:-debug}"
APP="Gaize.app"
BUNDLE_ID="com.gaize.companion"

echo "▸ swift build -c $CONFIG"
swift build -c "$CONFIG"

BIN_PATH="$(swift build -c "$CONFIG" --show-bin-path)/GaizeCompanion"
if [[ ! -x "$BIN_PATH" ]]; then
  echo "✗ binary not found at $BIN_PATH" >&2
  exit 1
fi

echo "▸ assembling $APP"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
mkdir -p "$APP/Contents/Resources"
cp "$BIN_PATH" "$APP/Contents/MacOS/GaizeCompanion"
cp packaging/Info.plist "$APP/Contents/Info.plist"

echo "▸ ad-hoc signing with identifier $BUNDLE_ID"
codesign --force --deep \
  --sign - \
  --identifier "$BUNDLE_ID" \
  --entitlements packaging/GaizeCompanion.entitlements \
  --options runtime \
  "$APP"

codesign --verify --verbose "$APP" >/dev/null 2>&1 && echo "✓ signature OK"

echo
echo "✓ built $APP"
echo "  run:  open $APP        (or ./Gaize.app/Contents/MacOS/GaizeCompanion to see logs)"
echo
echo "  First run: grant Accessibility, Camera, Microphone and Speech"
echo "  Recognition when asked (System Settings > Privacy & Security)."
echo "  If a rebuild ever loses a permission, remove Gaize from that list"
echo "  and re-run this script."
