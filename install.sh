#!/bin/sh
# LocalFlow installer for Apple Silicon Macs.
#   curl -fsSL https://raw.githubusercontent.com/Ross-mark-jones/LocalFlow/main/install.sh | sh
set -e

say() { printf '\n\033[1m%s\033[0m\n' "$1"; }
fail() { printf '\n❌ %s\n' "$1"; exit 1; }

[ "$(uname -m)" = "arm64" ] || fail "LocalFlow needs an Apple Silicon Mac (M1 or newer)."

if ! xcode-select -p >/dev/null 2>&1; then
    say "Apple's command line tools are needed first. A dialog will pop up —"
    say "click Install, wait for it to finish, then run this installer again."
    xcode-select --install || true
    exit 1
fi

if ! command -v brew >/dev/null 2>&1; then
    fail "Homebrew is required. Install it from https://brew.sh (one command), then re-run this."
fi

say "Installing dependencies (ffmpeg, uv)…"
command -v ffmpeg >/dev/null 2>&1 || brew install ffmpeg
command -v uv >/dev/null 2>&1 || brew install uv

REPO_DIR="$HOME/Apps/LocalFlow"
if [ -d "$REPO_DIR/.git" ]; then
    say "Updating LocalFlow…"
    git -C "$REPO_DIR" pull --ff-only
else
    say "Downloading LocalFlow…"
    mkdir -p "$HOME/Apps"
    git clone --quiet https://github.com/Ross-mark-jones/LocalFlow.git "$REPO_DIR"
fi

say "Setting up the speech engine (few minutes on first install)…"
cd "$REPO_DIR"
UV_PROJECT_ENVIRONMENT="$HOME/.localflow/venv" uv sync --quiet

say "Building LocalFlow.app…"
./scripts/build-app.sh

# The globe key must not trigger macOS's own action when pressed alone.
defaults write com.apple.HIToolbox AppleFnUsageType -int 0

open "/Applications/LocalFlow.app"

say "✅ LocalFlow is installed and starting (look for 🎙 in your menu bar)."
cat <<'EOT'

Two one-time permissions and you're away:

  1. A dialog will ask about Accessibility → click "Open System Settings"
     → turn ON LocalFlow → the app connects by itself.
  2. On your first dictation, click Allow for the Microphone.

Then: HOLD the fn (🌐) key, speak, release. Your words appear wherever
your cursor is. Click the 🎙 menu bar icon for settings and history.

The first launch downloads the speech model (~600 MB) — give it a minute.
Everything runs on your Mac. Nothing you say ever leaves it.
EOT
