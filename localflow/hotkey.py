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


KVK_ESCAPE = 53


class TapTracker:
    """Pure state machine that classifies fn press/release cycles.

    Hold-to-talk: press → "start", long release → "finish".
    Double-tap:   tap, tap → "lock" (hands-free recording), next press →
                  "finish", its release → "none".
    Quick single tap → "discard".
    """

    def __init__(self, tap_max_hold: float = 0.35, double_window: float = 0.45):
        self.tap_max_hold = tap_max_hold
        self.double_window = double_window
        self.locked = False
        self.press_time: float | None = None
        self._arming = False
        self._last_tap_end = float("-inf")
        self._ignore_release = False

    def press(self, now: float) -> str:
        if self.locked:
            self.locked = False
            self._ignore_release = True
            return "finish"
        self._arming = (now - self._last_tap_end) <= self.double_window
        self.press_time = now
        return "start"

    def release(self, now: float) -> str:
        if self._ignore_release:
            self._ignore_release = False
            return "none"
        hold = now - (self.press_time if self.press_time is not None else now)
        if hold < self.tap_max_hold:
            if self._arming:
                self._arming = False
                self.locked = True
                return "lock"
            self._last_tap_end = now
            return "discard"
        self._last_tap_end = float("-inf")
        return "finish"

    def cancel(self) -> None:
        self.locked = False
        self._arming = False
        self._ignore_release = False
        self.press_time = None
        self._last_tap_end = float("-inf")


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
        on_esc: Callable[[], None] | None = None,
    ):
        self.set_key(key)
        self.on_press = on_press
        self.on_release = on_release
        self.on_cancel = on_cancel
        self.on_esc = on_esc
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
        if event_type in (Quartz.kCGEventTapDisabledByTimeout,
                          Quartz.kCGEventTapDisabledByUserInput):
            Quartz.CGEventTapEnable(self._tap, True)
            return event

        if event_type == Quartz.kCGEventKeyDown:
            if self._down and self.on_cancel is not None:
                # fn+key combo — user wanted a shortcut, not a dictation.
                self._down = False
                threading.Thread(target=self.on_cancel, daemon=True).start()
            elif self.on_esc is not None:
                keycode = Quartz.CGEventGetIntegerValueField(
                    event, Quartz.kCGKeyboardEventKeycode)
                if keycode == KVK_ESCAPE:
                    threading.Thread(target=self.on_esc, daemon=True).start()
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

    def ensure_enabled(self) -> bool:
        """Re-enable the tap if macOS quietly disabled it (heavy system load
        makes the OS kill slow taps, eating key events — including releases).
        Returns True when a revive was needed."""
        if self._tap is None or Quartz.CGEventTapIsEnabled(self._tap):
            return False
        Quartz.CGEventTapEnable(self._tap, True)
        self._down = False  # the release was likely lost while we were dead
        return True

    def run(self) -> None:
        """Headless mode: install and block in a bare CFRunLoop."""
        self.install()
        Quartz.CFRunLoopRun()
