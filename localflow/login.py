"""Start-at-login via a LaunchAgent pointing at the app bundle."""

from __future__ import annotations

import os
import plistlib
import subprocess
from pathlib import Path

LABEL = "nz.somethingnew.localflow"
AGENT_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
APP_PATH = Path.home() / "Applications" / "LocalFlow.app"


def enabled() -> bool:
    return AGENT_PLIST.exists()


def enable() -> None:
    AGENT_PLIST.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": LABEL,
        # `open -a` launches it as a proper app (correct TCC identity), and
        # is a no-op if it's already running.
        "ProgramArguments": ["/usr/bin/open", "-a", str(APP_PATH)],
        "RunAtLoad": True,
    }
    with AGENT_PLIST.open("wb") as f:
        plistlib.dump(payload, f)
    subprocess.run(
        ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(AGENT_PLIST)],
        capture_output=True,
    )


def disable() -> None:
    subprocess.run(
        ["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True
    )
    AGENT_PLIST.unlink(missing_ok=True)


def toggle() -> bool:
    if enabled():
        disable()
    else:
        enable()
    return enabled()
