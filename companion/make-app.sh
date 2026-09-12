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

# SwiftPM's generated Bundle.module accessor looks for this bundle directly
# under Bundle.main.bundleURL, i.e. Contents/ - not Contents/Resources/.
RESOURCE_BUNDLE="$(swift build -c "$CONFIG" --show-bin-path)/GaizeCompanion_GaizeCompanion.bundle"
if [[ -d "$RESOURCE_BUNDLE" ]]; then
  cp -R "$RESOURCE_BUNDLE" "$APP/Contents/GaizeCompanion_GaizeCompanion.bundle"
  # SwiftPM's generated bundle has no Info.plist, which codesign requires
  # to recognize a .bundle-suffixed directory as valid bundle format
  # (otherwise: "bundle format unrecognized, invalid, or unsuitable").
  cat > "$APP/Contents/GaizeCompanion_GaizeCompanion.bundle/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleIdentifier</key>
	<string>com.gaize.companion.resources</string>
	<key>CFBundlePackageType</key>
	<string>BNDL</string>
	<key>CFBundleInfoDictionaryVersion</key>
	<string>6.0</string>
</dict>
</plist>
PLIST
fi

echo "▸ ad-hoc signing with identifier $BUNDLE_ID"
if [[ -d "$APP/Contents/GaizeCompanion_GaizeCompanion.bundle" ]]; then
  codesign --force --sign - "$APP/Contents/GaizeCompanion_GaizeCompanion.bundle"
fi

codesign --force \
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
