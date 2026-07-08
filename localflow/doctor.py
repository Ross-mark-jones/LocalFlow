"""Preflight checks: LocalFlow needs two permissions granted to the *hosting*
process (your terminal, or the .app if bundled later) plus one keyboard setting.
"""

from __future__ import annotations

import subprocess

from ApplicationServices import AXIsProcessTrusted


def check_accessibility() -> bool:
    return bool(AXIsProcessTrusted())


def check_fn_key_setting() -> str | None:
    """Returns the current 'Press 🌐 key to' action, or None if unreadable.
    0 = Do Nothing, 1 = Change Input Source, 2 = Emoji & Symbols, 3 = Dictation."""
    try:
        out = subprocess.run(
            ["defaults", "read", "com.apple.HIToolbox", "AppleFnUsageType"],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() or None
    except (subprocess.SubprocessError, OSError):
        return None


def run_doctor(hotkey: str) -> bool:
    """Print a permission report. Returns True when everything critical is in place."""
    ok = True

    if check_accessibility():
        print("✅ Accessibility: granted")
    else:
        ok = False
        print("❌ Accessibility: NOT granted — needed for the hotkey listener and pasting.")
        print("   System Settings → Privacy & Security → Accessibility → enable your terminal app.")

    print("ℹ️  Microphone: macOS will prompt on first recording. If dictations come back")
    print("   empty, check System Settings → Privacy & Security → Microphone.")

    if hotkey == "fn":
        setting = check_fn_key_setting()
        if setting == "0":
            print("✅ Globe key: set to 'Do Nothing'")
        else:
            print("⚠️  Globe key: currently triggers a system action when pressed alone.")
            print("   System Settings → Keyboard → 'Press 🌐 key to' → 'Do Nothing',")
            print("   otherwise the emoji picker / macOS dictation fights with LocalFlow.")

    return ok
