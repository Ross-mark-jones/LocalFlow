"""Global hold-to-talk hotkey via a Quartz event tap.

The fn/globe key never reaches ordinary keyDown handlers — it only surfaces as
a flagsChanged event with the SecondaryFn modifier mask, which is why this uses
a CGEventTap rather than a higher-level library. The tap is listen-only: we
observe fn but cannot swallow it, so users should set System Settings →
Keyboard → "Press 🌐 key to" → "Do Nothing" (doctor checks this).

The tap also watches keyDown: any other key pressed while the hold key is down
means the user wanted a keyboard shortcut (fn+arrow, fn+backspace, ...), so the
recording is cancelled rather than transcribed — same behaviour as Wispr Flow.

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
    """Fires on_press when the chosen key goes down, on_release when it comes
    up, and on_cancel if another key is struck mid-hold.

    install() adds the tap to the *current* run loop (works under both a bare
    CFRunLoop and an AppKit event loop). Callbacks run on short-lived worker
    threads; do UI updates via AppHelper.callAfter.
    """

    def __init__(
        self,
        key: str,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
        on_cancel: Callable[[], None] | None = None,
    ):
        self.set_key(key)
        self.on_press = on_press
        self.on_release = on_release
        self.on_cancel = on_cancel
        self._down = False
        self._tap = None

    def set_key(self, key: str) -> None:
        """Switch the hold key. Safe to call live — the callback reads these on
        every event."""
        if key not in KEYCODES:
            raise ValueError(f"Unsupported hotkey {key!r}. Options: {', '.join(KEYCODES)}")
        self.key = key
        self.keycode = KEYCODES[key]
        self.flag_mask = FLAG_MASKS[key]
        self._down = False

    def _callback(self, proxy, event_type, event, refcon):
        if event_type == Quartz.kCGEventTapDisabledByTimeout:
            Quartz.CGEventTapEnable(self._tap, True)
            return event

        if event_type == Quartz.kCGEventKeyDown:
            if self._down and self.on_cancel is not None:
                # fn+key combo — user wanted a shortcut, not a dictation.
                self._down = False
                threading.Thread(target=self.on_cancel, daemon=True).start()
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

    def install(self) -> None:
        """Create the tap and attach it to the current run loop. Raises if the
        tap can't be created (almost always a missing Accessibility permission)."""
        mask = Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged) | Quartz.CGEventMaskBit(
            Quartz.kCGEventKeyDown
        )
        self._tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            mask,
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

    def run(self) -> None:
        """Headless mode: install and block in a bare CFRunLoop."""
        self.install()
        Quartz.CFRunLoopRun()
