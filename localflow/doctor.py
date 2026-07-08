"""Preflight checks: LocalFlow needs two permissions granted to the *hosting*
process (your terminal, or the .app if bundled later) plus one keyboard setting.

Doctor doesn't just report — where possible it *triggers* the system prompts,
which registers the hosting app in the right Privacy & Security list so the
user only has to flip a toggle instead of hunting with the "+" button.
"""

from __future__ import annotations

import subprocess

from ApplicationServices import (
    AXIsProcessTrusted,
    AXIsProcessTrustedWithOptions,
    kAXTrustedCheckOptionPrompt,
)


def check_accessibility(prompt: bool = False) -> bool:
    if prompt:
        # Pops the system dialog with an "Open System Settings" button and
        # registers this process's host app in the Accessibility list.
        return bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True}))
    return bool(AXIsProcessTrusted())


def trigger_microphone_prompt() -> None:
    """Opening an input stream forces the mic permission prompt if it hasn't
    been decided yet. Harmless no-op when already granted or denied."""
    try:
        import sounddevice as sd

        with sd.InputStream(samplerate=16_000, channels=1):
            pass
    except Exception:
        pass  # denied or no input device; the printed guidance covers it


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
    """Print a permission report, triggering the system prompts where possible.
    Returns True when everything critical is in place."""
    ok = True

    if check_accessibility():
        print("✅ Accessibility: granted")
    else:
        ok = False
        check_accessibility(prompt=True)
        print("❌ Accessibility: NOT granted — needed for the hotkey listener and pasting.")
        print("   A system dialog should have just appeared: click 'Open System Settings',")
        print("   enable your terminal app in the Accessibility list, then re-run doctor.")

    trigger_microphone_prompt()
    print("ℹ️  Microphone: if macOS just prompted, click Allow. If dictations come back")
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
