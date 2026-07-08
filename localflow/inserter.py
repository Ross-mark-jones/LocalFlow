"""Insert text into the frontmost app.

Same trick Wispr Flow and every open-source clone uses: put the transcript on
the clipboard and synthesise Cmd+V. Pasting is the only insertion path that
works reliably across native apps, Electron apps, and browsers alike (AX
value-setting fails in far too many of them).

By default the transcript is *left* on the clipboard rather than restoring the
old contents: slow apps (especially Electron) read the pasteboard late, so an
eager restore races the paste and the text silently vanishes. Leaving it also
means a failed paste is always one manual Cmd+V away. Set restore_clipboard =
true in the config to get the old swap behaviour (with a generous delay).
"""

from __future__ import annotations

import threading
import time

import Quartz
from AppKit import NSPasteboard, NSPasteboardTypeString

KEY_V = 9  # kVK_ANSI_V
RESTORE_DELAY = 2.0  # seconds; generous so even slow paste handlers have read us


def paste_text(text: str, restore_clipboard: bool = False) -> None:
    if not text:
        return
    pasteboard = NSPasteboard.generalPasteboard()
    previous = pasteboard.stringForType_(NSPasteboardTypeString) if restore_clipboard else None

    pasteboard.clearContents()
    pasteboard.setString_forType_(text, NSPasteboardTypeString)
    change_count = pasteboard.changeCount()

    # Give the pasteboard server a beat to publish before we hit Cmd+V.
    time.sleep(0.08)
    for key_down in (True, False):
        event = Quartz.CGEventCreateKeyboardEvent(None, KEY_V, key_down)
        Quartz.CGEventSetFlags(event, Quartz.kCGEventFlagMaskCommand)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)

    if previous is not None:
        def restore() -> None:
            pb = NSPasteboard.generalPasteboard()
            # Only restore if nothing else has written the clipboard since us.
            if pb.changeCount() == change_count:
                pb.clearContents()
                pb.setString_forType_(previous, NSPasteboardTypeString)

        threading.Timer(RESTORE_DELAY, restore).start()
