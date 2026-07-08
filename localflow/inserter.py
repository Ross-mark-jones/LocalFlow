"""Insert text into the frontmost app.

Same trick Wispr Flow and every open-source clone uses: stash the clipboard,
put the transcript on it, synthesise Cmd+V, then restore the clipboard. Pasting
is the only insertion path that works reliably across native apps, Electron
apps, and browsers alike (AX value-setting fails in far too many of them).
"""

from __future__ import annotations

import time

import Quartz
from AppKit import NSPasteboard, NSPasteboardTypeString

KEY_V = 9  # kVK_ANSI_V


def paste_text(text: str, restore_clipboard: bool = True, restore_delay: float = 0.5) -> None:
    if not text:
        return
    pasteboard = NSPasteboard.generalPasteboard()
    previous = pasteboard.stringForType_(NSPasteboardTypeString) if restore_clipboard else None

    pasteboard.clearContents()
    pasteboard.setString_forType_(text, NSPasteboardTypeString)

    for key_down in (True, False):
        event = Quartz.CGEventCreateKeyboardEvent(None, KEY_V, key_down)
        Quartz.CGEventSetFlags(event, Quartz.kCGEventFlagMaskCommand)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)

    if previous is not None:
        # Give the target app time to read the pasteboard before restoring.
        time.sleep(restore_delay)
        pasteboard.clearContents()
        pasteboard.setString_forType_(previous, NSPasteboardTypeString)
