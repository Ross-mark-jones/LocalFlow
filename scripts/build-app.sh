#!/bin/sh
# Build ~/Applications/LocalFlow.app — a menu-bar-only wrapper around the
# localflow console script in ~/.localflow/venv.
#
# The launcher SPAWNS the python process rather than exec-ing it, so the app
# bundle stays the "responsible process" for TCC: permission prompts and
# grants (Accessibility, Microphone) attach to LocalFlow.app, not to python.
set -e

REPO="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$HOME/.localflow/venv"
# /Applications: it's where the Privacy & Security file picker, Spotlight,
# and users expect apps to live.
APP="/Applications/LocalFlow.app"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleName</key><string>LocalFlow</string>
	<key>CFBundleDisplayName</key><string>LocalFlow</string>
	<key>CFBundleIdentifier</key><string>nz.somethingnew.localflow</string>
	<key>CFBundleExecutable</key><string>LocalFlow</string>
	<key>CFBundlePackageType</key><string>APPL</string>
	<key>CFBundleShortVersionString</key><string>0.2.0</string>
	<key>CFBundleIconFile</key><string>LocalFlow</string>
	<key>LSMinimumSystemVersion</key><string>13.0</string>
	<key>LSUIElement</key><true/>
	<key>NSMicrophoneUsageDescription</key>
	<string>LocalFlow records your voice while you hold the dictation key, and transcribes it entirely on this Mac.</string>
</dict>
</plist>
PLIST

# Native launcher: a script here would run under /bin/sh and break TCC
# attribution (see scripts/launcher.c).
clang -O2 -o "$APP/Contents/MacOS/LocalFlow" "$REPO/scripts/launcher.c"

# Icon is nice-to-have; never fail the build over it.
"$VENV/bin/python" "$REPO/scripts/make-icon.py" "$APP/Contents/Resources" || \
    echo "warning: icon generation failed, using generic icon"

# Ad-hoc signature gives the bundle a stable identity for TCC.
codesign --force --deep -s - "$APP"
echo "built: $APP"
