"""Global hold-to-talk hotkey via a Quartz event tap.

The fn/globe key never reaches ordinary keyDown handlers — it only surfaces as
a flagsChanged event with the SecondaryFn modifier mask, which is why this uses
a CGEventTap rather than a higher-level library. The tap is listen-only: we
observe fn but cannot swallow it, so users should set System Settings →
Keyboard → "Press 🌐 key to" → "Do Nothing" (doctor checks this).

Requires the hosting app (your terminal) to have Accessibility permission.
"""

from __future__ import annotations

import threading
from typing import Callable

import Quartz

# Virtual keycodes for supported hold keys — all modifiers, so a single
# flagsChanged press/release cycle covers every one of them.
KEYCODES = {
    "fn": 63,
    "right_cmd": 54,
    "right_alt": 61,
    "right_ctrl": 62,
    "right_shift": 60,
}

# Modifier flag masks, used to disambiguate press from release.
FLAG_MASKS = {
    "fn": Quartz.kCGEventFlagMaskSecondaryFn,
    "right_cmd": Quartz.kCGEventFlagMaskCommand,
    "right_alt": Quartz.kCGEventFlagMaskAlternate,
    "right_ctrl": Quartz.kCGEventFlagMaskControl,
    "right_shift": Quartz.kCGEventFlagMaskShift,
}


class HotkeyListener:
    """Fires on_press when the chosen key goes down, on_release when it comes up.

    run() blocks in a CFRunLoop, so call it from the main thread and do real
    work (transcription, pasting) on worker threads from the callbacks.
    """

    def __init__(self, key: str, on_press: Callable[[], None], on_release: Callable[[], None]):
        if key not in KEYCODES:
            raise ValueError(f"Unsupported hotkey {key!r}. Options: {', '.join(KEYCODES)}")
        self.key = key
        self.keycode = KEYCODES[key]
        self.flag_mask = FLAG_MASKS[key]
        self.on_press = on_press
        self.on_release = on_release
        self._down = False
        self._tap = None

    def _callback(self, proxy, event_type, event, refcon):
        if event_type == Quartz.kCGEventTapDisabledByTimeout:
            Quartz.CGEventTapEnable(self._tap, True)
            return event
        if event_type != Quartz.kCGEventFlagsChanged:
            return event

        keycode = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
        if keycode != self.keycode:
            return event

        flags = Quartz.CGEventGetFlags(event)
        pressed = bool(flags & self.flag_mask)
        if pressed and not self._down:
            self._down = True
            threading.Thread(target=self.on_press, daemon=True).start()
        elif not pressed and self._down:
            self._down = False
            threading.Thread(target=self.on_release, daemon=True).start()
        return event

    def run(self) -> None:
        """Install the tap and block in the run loop. Raises if the tap can't be created
        (almost always a missing Accessibility permission)."""
        self._tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged),
            self._callback,
            None,
        )
        if self._tap is None:
            raise PermissionError(
                "Could not create the keyboard event tap. Grant Accessibility permission to "
                "your terminal in System Settings → Privacy & Security → Accessibility, "
                "then restart LocalFlow."
            )
        source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
        Quartz.CFRunLoopAddSource(Quartz.CFRunLoopGetCurrent(), source, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(self._tap, True)
        Quartz.CFRunLoopRun()
