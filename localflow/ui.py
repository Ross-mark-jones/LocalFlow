"""Menu-bar app + floating overlay indicator (AppKit via PyObjC).

Everything here runs on the main thread. Worker threads must reach the UI via
PyObjCTools.AppHelper.callAfter — AppKit is not thread-safe.
"""

from __future__ import annotations

import subprocess
import threading
from typing import Callable

from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBackingStoreBuffered,
    NSColor,
    NSFont,
    NSMakeRect,
    NSMenu,
    NSMenuItem,
    NSPanel,
    NSScreen,
    NSStatusBar,
    NSStatusWindowLevel,
    NSTextAlignmentCenter,
    NSTextField,
    NSVariableStatusItemLength,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
)
from Foundation import NSObject
from PyObjCTools import AppHelper

ICON_IDLE = "🎙"
ICON_RECORDING = "🔴"
ICON_BUSY = "✍️"
ICON_ERROR = "⚠️"

TOGGLES = [
    ("Remove filler words", "remove_fillers"),
    ("Spoken commands (“new line”)", "spoken_commands"),
    ("Auto-capitalise", "capitalize"),
    ("Sound cues", "sounds"),
    ("Overlay indicator", "overlay"),
    ("Restore old clipboard after paste", "restore_clipboard"),
    ("LLM cleanup via Ollama", "llm_enabled"),
]

MODELS = [
    ("Parakeet 110M — fast + accurate (recommended)", "mlx-community/parakeet-tdt_ctc-110m"),
    ("Parakeet 0.6B — max accuracy, still quick", "mlx-community/parakeet-tdt-0.6b-v2"),
    ("Whisper Base.en — light fallback", "mlx-community/whisper-base.en-mlx"),
    ("Whisper Small.en", "mlx-community/whisper-small.en-mlx"),
    ("Whisper Large v3 Turbo — 16 GB+ Macs", "mlx-community/whisper-large-v3-turbo"),
]

HOTKEYS = [
    ("fn / globe", "fn"),
    ("Right ⌘", "right_cmd"),
    ("Right ⌥", "right_alt"),
    ("Right ⌃", "right_ctrl"),
]


class _MenuTarget(NSObject):
    """Objective-C bridge: menu items need an NSObject target/selector pair."""

    def onToggle_(self, sender):
        self.controller.on_toggle(str(sender.representedObject()))

    def onModel_(self, sender):
        self.controller.on_model(str(sender.representedObject()))

    def onHotkey_(self, sender):
        self.controller.on_hotkey(str(sender.representedObject()))

    def onLogin_(self, sender):
        self.controller.on_login_toggle()

    def onCancelRecording_(self, sender):
        self.controller.on_cancel_recording()

    def onHistoryCopy_(self, sender):
        self.controller.on_history_copy(str(sender.representedObject()))

    def onOpenLibrary_(self, sender):
        self.controller.on_open_library()

    def onClearHistory_(self, sender):
        self.controller.on_clear_history()

    def onOpenConfig_(self, sender):
        self.controller.on_open_config()

    def onOpenDictionary_(self, sender):
        self.controller.on_open_dictionary()

    def onQuit_(self, sender):
        NSApplication.sharedApplication().terminate_(None)


class Overlay:
    """Wispr-style pill at the bottom-centre of the active screen."""

    WIDTH, HEIGHT = 340, 40

    def __init__(self) -> None:
        rect = NSMakeRect(0, 0, self.WIDTH, self.HEIGHT)
        style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style, NSBackingStoreBuffered, False
        )
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setLevel_(NSStatusWindowLevel)
        panel.setIgnoresMouseEvents_(True)
        panel.setHasShadow_(True)
        panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        content = panel.contentView()
        content.setWantsLayer_(True)
        layer = content.layer()
        layer.setBackgroundColor_(
            NSColor.colorWithCalibratedWhite_alpha_(0.08, 0.88).CGColor()
        )
        layer.setCornerRadius_(self.HEIGHT / 2)

        label = NSTextField.labelWithString_("")
        label.setFrame_(NSMakeRect(10, 0, self.WIDTH - 20, self.HEIGHT - 12))
        label.setAlignment_(NSTextAlignmentCenter)
        label.setTextColor_(NSColor.whiteColor())
        label.setFont_(NSFont.systemFontOfSize_(13))
        content.addSubview_(label)

        self.panel = panel
        self.label = label
        self._flash_timer: threading.Timer | None = None

    def _position(self) -> None:
        screen = NSScreen.mainScreen()
        if screen is None:
            return
        frame = screen.visibleFrame()
        x = frame.origin.x + (frame.size.width - self.WIDTH) / 2
        y = frame.origin.y + 96
        self.panel.setFrameOrigin_((x, y))

    def show(self, text: str) -> None:
        if self._flash_timer:
            self._flash_timer.cancel()
            self._flash_timer = None
        self.label.setStringValue_(text)
        self._position()
        self.panel.orderFrontRegardless()

    def flash(self, text: str, seconds: float = 1.6) -> None:
        self.show(text)
        self._flash_timer = threading.Timer(seconds, lambda: AppHelper.callAfter(self.hide))
        self._flash_timer.daemon = True
        self._flash_timer.start()

    def hide(self) -> None:
        self.panel.orderOut_(None)


class StatusBarUI:
    """Menu-bar icon + settings menu. `controller` provides the on_* callbacks
    and a `config` attribute; see LocalFlowApp."""

    def __init__(self, controller) -> None:
        self.controller = controller
        self._target = _MenuTarget.alloc().init()
        self._target.controller = controller
        self._toggle_items: dict[str, NSMenuItem] = {}
        self._model_items: dict[str, NSMenuItem] = {}
        self._hotkey_items: dict[str, NSMenuItem] = {}

        self.item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        self.item.button().setTitle_(ICON_IDLE)

        menu = NSMenu.alloc().init()
        menu.setAutoenablesItems_(False)

        self.status_line = self._info_item(menu, "Starting…")
        self.last_line = self._info_item(menu, "Last: —")

        history_parent = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("History", None, "")
        self._history_menu = NSMenu.alloc().init()
        self._history_menu.setAutoenablesItems_(False)
        history_parent.setSubmenu_(self._history_menu)
        menu.addItem_(history_parent)
        self._action_item(menu, "Cancel recording (or press Esc)", "onCancelRecording:", "")
        menu.addItem_(NSMenuItem.separatorItem())

        for title, key in TOGGLES:
            entry = self._action_item(menu, title, "onToggle:", key)
            self._toggle_items[key] = entry
        menu.addItem_(NSMenuItem.separatorItem())

        self._submenu(menu, "Model", MODELS, "onModel:", self._model_items)
        self._submenu(menu, "Hold-to-talk key", HOTKEYS, "onHotkey:", self._hotkey_items)
        menu.addItem_(NSMenuItem.separatorItem())

        self._login_item = self._action_item(menu, "Start at login", "onLogin:", "")

        self._action_item(menu, "Open config file", "onOpenConfig:", "")
        self._action_item(menu, "Open personal dictionary", "onOpenDictionary:", "")
        menu.addItem_(NSMenuItem.separatorItem())
        self._action_item(menu, "Quit LocalFlow", "onQuit:", "")

        self.item.setMenu_(menu)
        self.sync()

    def _info_item(self, menu: NSMenu, title: str) -> NSMenuItem:
        entry = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
        entry.setEnabled_(False)
        menu.addItem_(entry)
        return entry

    def _action_item(self, menu: NSMenu, title: str, selector: str, represented: str) -> NSMenuItem:
        entry = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, selector, "")
        entry.setTarget_(self._target)
        entry.setRepresentedObject_(represented)
        menu.addItem_(entry)
        return entry

    def _submenu(self, menu, title, options, selector, registry) -> None:
        parent = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
        sub = NSMenu.alloc().init()
        sub.setAutoenablesItems_(False)
        for label, value in options:
            entry = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(label, selector, "")
            entry.setTarget_(self._target)
            entry.setRepresentedObject_(value)
            sub.addItem_(entry)
            registry[value] = entry
        parent.setSubmenu_(sub)
        menu.addItem_(parent)

    # -- updates (main thread only) --------------------------------------

    def set_icon(self, icon: str) -> None:
        self.item.button().setTitle_(icon)

    def set_status(self, text: str) -> None:
        self.status_line.setTitle_(text)

    def set_last(self, text: str) -> None:
        short = text.replace("\n", " ")
        if len(short) > 60:
            short = short[:57] + "…"
        self.last_line.setTitle_(f"Last: {short}")

    def refresh_history(self, entries: list[dict]) -> None:
        """Rebuild the History submenu: recent dictations (click = copy),
        then Library/Clear actions. Main thread only."""
        import time as _time

        self._history_menu.removeAllItems()
        if not entries:
            placeholder = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "No dictations yet", None, "")
            placeholder.setEnabled_(False)
            self._history_menu.addItem_(placeholder)
        for entry in entries:
            stamp = _time.strftime("%H:%M", _time.localtime(entry["ts"]))
            text = entry["text"].replace("\n", " ")
            title = f"{stamp}  {text[:52]}{'…' if len(text) > 52 else ''}"
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                title, "onHistoryCopy:", "")
            item.setTarget_(self._target)
            item.setRepresentedObject_(entry["text"])
            item.setToolTip_(entry["text"])
            self._history_menu.addItem_(item)
        self._history_menu.addItem_(NSMenuItem.separatorItem())
        library = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Open Library…", "onOpenLibrary:", "")
        library.setTarget_(self._target)
        self._history_menu.addItem_(library)
        clear = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Clear History", "onClearHistory:", "")
        clear.setTarget_(self._target)
        self._history_menu.addItem_(clear)

    def sync(self) -> None:
        """Reflect current config in every checkmark."""
        config = self.controller.config
        for key, entry in self._toggle_items.items():
            entry.setState_(1 if getattr(config, key) else 0)
        for value, entry in self._model_items.items():
            entry.setState_(1 if value == config.model else 0)
        for value, entry in self._hotkey_items.items():
            entry.setState_(1 if value == config.hotkey else 0)
        if hasattr(self.controller, "login_enabled"):
            self._login_item.setState_(1 if self.controller.login_enabled() else 0)


def open_in_default_app(path: str) -> None:
    subprocess.run(["open", path], check=False)


def setup_nsapp() -> None:
    """Accessory activation policy: menu-bar presence, no Dock icon."""
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)


def run_event_loop() -> None:
    AppHelper.runEventLoop()


def call_on_main(fn: Callable, *args) -> None:
    AppHelper.callAfter(fn, *args)
