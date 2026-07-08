"""LocalFlow runtime: menu-bar app wiring hotkey → recorder → ASR → formatter → paste.

Threading model: AppKit's event loop owns the main thread (status item, overlay,
and the CGEventTap source all live there). Hotkey callbacks arrive on worker
threads; transcription is serialised by a lock; every UI update crosses back to
the main thread via ui.call_on_main. Pasting also happens on the main thread so
pasteboard writes and the synthetic Cmd+V never interleave between dictations.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time

from . import login, sounds, ui
from .config import (
    CONFIG_FILE,
    DICTIONARY_FILE,
    LOG_FILE,
    Config,
    load_dictionary,
    save_setting,
)
from .context import current_context
from .engine import create_engine
from .formatter import format_transcript, llm_cleanup
from .hotkey import HotkeyListener
from .inserter import paste_text
from .recorder import Recorder, duration_seconds, trim_silence

MIN_UTTERANCE_SECONDS = 0.3
SILENCE_PEAK = 1e-5  # all-zero audio means the mic permission is missing

log = logging.getLogger("localflow")


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)],
    )


class LocalFlowApp:
    def __init__(self, config: Config):
        self.config = config
        self.engine = create_engine(config.model, config.language)
        self.recorder = Recorder()
        self.listener = HotkeyListener(
            config.hotkey, self._on_press, self._on_release, self._on_cancel
        )
        self._transcribe_lock = threading.Lock()
        self._model_ready = threading.Event()
        self.status_bar: ui.StatusBarUI | None = None
        self.overlay: ui.Overlay | None = None

    # -- UI helpers (safe from any thread) --------------------------------

    def _icon(self, icon: str) -> None:
        if self.status_bar:
            ui.call_on_main(self.status_bar.set_icon, icon)

    def _status(self, text: str) -> None:
        if self.status_bar:
            ui.call_on_main(self.status_bar.set_status, text)

    def _overlay_show(self, text: str) -> None:
        if self.overlay and self.config.overlay:
            ui.call_on_main(self.overlay.show, text)

    def _overlay_flash(self, text: str, seconds: float = 1.6) -> None:
        if self.overlay and self.config.overlay:
            ui.call_on_main(self.overlay.flash, text, seconds)

    def _cue(self, fn) -> None:
        if self.config.sounds:
            ui.call_on_main(fn)

    # -- model lifecycle ---------------------------------------------------

    def _model_short_name(self) -> str:
        return self.config.model.rsplit("/", 1)[-1]

    def _load_model(self) -> None:
        import shutil

        log.info("ffmpeg=%s", shutil.which("ffmpeg"))  # parakeet needs it; None = broken PATH
        self._status(f"Loading {self._model_short_name()}…")
        self._icon(ui.ICON_BUSY)
        started = time.perf_counter()
        try:
            self.engine.load()
        except Exception:
            log.exception("model load failed")
            self._status(f"Model failed to load — see {LOG_FILE.name}")
            self._icon(ui.ICON_ERROR)
            return
        log.info("model %s ready in %.1fs", self.config.model, time.perf_counter() - started)
        self._status(f"Ready · {self._model_short_name()} · hold [{self.config.hotkey}]")
        self._icon(ui.ICON_IDLE)
        self._model_ready.set()

    # -- hotkey callbacks (worker threads) ---------------------------------

    def _on_press(self) -> None:
        if not self._model_ready.is_set():
            self._overlay_flash("⏳ Model still loading…")
            self._cue(sounds.error_cue)
            return
        self.recorder.start()
        log.info("recording started")
        self._cue(sounds.start_cue)
        self._icon(ui.ICON_RECORDING)
        self._overlay_show("● Listening…")

    def _on_cancel(self) -> None:
        # Another key was struck mid-hold: the user wanted fn+<key>, not us.
        if self.recorder.recording:
            self.recorder.stop()
            self._icon(ui.ICON_IDLE)
            self._overlay_flash("✕ Cancelled", 0.9)
            log.info("recording cancelled by key combo")

    def _on_release(self) -> None:
        audio = self.recorder.stop()
        log.info("recording stopped (%.1fs)", duration_seconds(audio))
        self._cue(sounds.stop_cue)
        if duration_seconds(audio) < MIN_UTTERANCE_SECONDS:
            self._icon(ui.ICON_IDLE)
            if self.overlay:
                ui.call_on_main(self.overlay.hide)
            return
        if audio.size and float(abs(audio).max()) < SILENCE_PEAK:
            self._icon(ui.ICON_ERROR)
            self._overlay_flash("🎙 Mic gave silence — check Microphone permission", 3.0)
            log.warning("captured %.1fs of pure silence — mic permission?", duration_seconds(audio))
            return

        held = duration_seconds(audio)
        audio = trim_silence(audio)
        if duration_seconds(audio) < MIN_UTTERANCE_SECONDS:
            self._icon(ui.ICON_IDLE)
            self._overlay_flash("… no speech detected", 1.2)
            log.info("nothing above noise floor (held %.1fs)", held)
            return

        with self._transcribe_lock:
            self._icon(ui.ICON_BUSY)
            self._overlay_show("✍️ Transcribing…")
            started = time.perf_counter()
            self.config.dictionary = load_dictionary()  # live-reload user edits
            ctx = current_context(self.config)
            try:
                raw = self.engine.transcribe(audio)
            except Exception:
                log.exception("transcription failed")
                self._icon(ui.ICON_ERROR)
                self._overlay_flash("⚠️ Transcription failed — see log", 2.5)
                return
            text = format_transcript(raw, self.config, ctx)
            if text and self.config.llm_enabled:
                text = llm_cleanup(text, self.config, ctx)
            elapsed = time.perf_counter() - started

            if not text:
                self._icon(ui.ICON_IDLE)
                self._overlay_flash("… no speech detected", 1.2)
                log.info("no speech (%.2fs, %.1fs speech of %.1fs held)",
                         elapsed, duration_seconds(audio), held)
                return

            ui.call_on_main(self._paste_and_report, text, ctx.app_name or "app", elapsed)

    # -- main-thread finish -------------------------------------------------

    def _paste_and_report(self, text: str, target: str, elapsed: float) -> None:
        paste_text(text, self.config.restore_clipboard)
        self.status_bar.set_last(text)
        self.status_bar.set_icon(ui.ICON_IDLE)
        if self.config.overlay:
            self.overlay.flash(f"✓ Pasted into {target} — also on clipboard", 1.8)
        log.info("→ %s in %.2fs: %s", target, elapsed, text[:120])

    # -- menu callbacks (main thread) ----------------------------------------

    def on_toggle(self, key: str) -> None:
        value = not getattr(self.config, key)
        setattr(self.config, key, value)
        save_setting(key, value)
        self.status_bar.sync()
        log.info("setting %s = %s", key, value)

    def on_model(self, repo: str) -> None:
        if repo == self.config.model:
            return
        self.config.model = repo
        save_setting("model", repo)
        self.engine = create_engine(repo, self.config.language)
        self._model_ready.clear()
        self.status_bar.sync()
        threading.Thread(target=self._load_model, daemon=True).start()

    def login_enabled(self) -> bool:
        return login.enabled()

    def on_login_toggle(self) -> None:
        state = login.toggle()
        self.status_bar.sync()
        log.info("start at login: %s", state)

    def on_hotkey(self, key: str) -> None:
        self.listener.set_key(key)
        self.config.hotkey = key
        save_setting("hotkey", key)
        self.status_bar.sync()
        self._status(f"Ready · {self._model_short_name()} · hold [{key}]")
        log.info("hotkey switched to %s", key)

    def on_open_config(self) -> None:
        ui.open_in_default_app(str(CONFIG_FILE))

    def on_open_dictionary(self) -> None:
        ui.open_in_default_app(str(DICTIONARY_FILE))

    # -- entry ----------------------------------------------------------------

    def _wait_for_accessibility(self) -> None:
        from .doctor import check_accessibility

        while not check_accessibility():
            time.sleep(2)
        ui.call_on_main(self._connect_hotkey)

    def _connect_hotkey(self) -> None:
        """Main thread: install the tap now, or park in a wait loop until the
        user grants Accessibility (first launch of the .app).

        Trust is checked explicitly: without the grant, a listen-only tap can
        be created successfully yet silently receive no events, so tap
        creation succeeding proves nothing."""
        from .doctor import check_accessibility

        if not check_accessibility():
            check_accessibility(prompt=True)  # pops the system dialog
            log.warning("not trusted for Accessibility — waiting for grant")
            self._icon(ui.ICON_ERROR)
            self._status("Enable LocalFlow in Accessibility settings…")
            self._overlay_flash("Grant Accessibility to LocalFlow — I'll connect automatically", 6.0)
            threading.Thread(target=self._wait_for_accessibility, daemon=True).start()
            return
        try:
            self.listener.install()
        except PermissionError as error:
            log.error("%s", error)
            self._icon(ui.ICON_ERROR)
            self._status("Hotkey setup failed — see log")
            return
        log.info("hotkey listener connected (%s), accessibility trusted", self.config.hotkey)
        if self._model_ready.is_set():
            self._icon(ui.ICON_IDLE)
            self._status(f"Ready · {self._model_short_name()} · hold [{self.config.hotkey}]")

    def run(self) -> None:
        _setup_logging()
        if not _acquire_single_instance_lock():
            print("LocalFlow is already running (check the 🎙 in your menu bar).")
            sys.exit(0)
        ui.setup_nsapp()
        self.status_bar = ui.StatusBarUI(self)
        self.overlay = ui.Overlay()
        self._connect_hotkey()
        threading.Thread(target=self._load_model, daemon=True).start()
        print("LocalFlow is in your menu bar (🎙). Logs:", LOG_FILE)
        ui.run_event_loop()


_lock_handle = None  # keeps the fd (and the flock) alive for the process lifetime


def _acquire_single_instance_lock() -> bool:
    """One instance only — a login item plus a manual launch would otherwise
    both tap the keyboard and paste twice."""
    global _lock_handle
    import fcntl

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _lock_handle = open(LOG_FILE.parent / "instance.lock", "w")
    try:
        fcntl.flock(_lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False
