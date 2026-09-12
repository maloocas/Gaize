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

# Prefer a stable Apple Development identity when one is installed. TCC
# (Accessibility, Camera, Microphone, Speech) keys grants to the app's code
# requirement; a fresh ad-hoc signature can therefore invalidate the grant
# after every rebuild even though the bundle identifier stays unchanged.
SIGN_IDENTITY="${GAIZE_SIGN_IDENTITY:-}"
if [[ -z "$SIGN_IDENTITY" ]]; then
  SIGN_IDENTITY="$(security find-identity -v -p codesigning 2>/dev/null \
    | sed -n 's/.*"\(Apple Development:[^"]*\)".*/\1/p' \
    | head -n 1)"
fi
if [[ -z "$SIGN_IDENTITY" ]]; then
  SIGN_IDENTITY="-"
fi

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
  # Older SwiftPM versions generated this bundle without an Info.plist.
  # Newer versions put one under Contents; adding another at the bundle root
  # makes codesign reject it as unsealed content.
  if [[ ! -f "$APP/Contents/GaizeCompanion_GaizeCompanion.bundle/Info.plist" && \
        ! -f "$APP/Contents/GaizeCompanion_GaizeCompanion.bundle/Contents/Info.plist" ]]; then
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
fi

echo "▸ signing with $SIGN_IDENTITY (identifier $BUNDLE_ID)"
if [[ -d "$APP/Contents/GaizeCompanion_GaizeCompanion.bundle" ]]; then
  codesign --force --sign "$SIGN_IDENTITY" "$APP/Contents/GaizeCompanion_GaizeCompanion.bundle"
fi

codesign --force \
  --sign "$SIGN_IDENTITY" \
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
