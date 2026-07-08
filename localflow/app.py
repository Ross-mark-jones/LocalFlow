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
import queue
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import history, login, sounds, ui
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
from .hotkey import HotkeyListener, TapTracker
from .inserter import copy_text, paste_text
from .recorder import Recorder, duration_seconds, trim_silence

MIN_UTTERANCE_SECONDS = 0.3
SILENCE_PEAK = 1e-5  # all-zero audio means the mic permission is missing
MAX_RECORDING_SECONDS = 300  # watchdog auto-finish: a lost key event must never record forever

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
        # All hotkey/menu/watchdog events flow through one queue and are
        # handled strictly in order on a single dispatcher thread — per-event
        # threads raced each other on fast double-taps.
        self._events: "queue.Queue[tuple[str, float]]" = queue.Queue()
        self.listener = HotkeyListener(config.hotkey, self._enqueue_event)
        self.tap_tracker = TapTracker()
        self._transcribe_lock = threading.Lock()
        self._model_ready = threading.Event()
        # MLX streams are thread-bound (parakeet-mlx raises "no Stream in
        # current thread" if load and inference happen on different threads),
        # so every engine call runs on this single dedicated thread.
        self._engine_thread = ThreadPoolExecutor(max_workers=1, thread_name_prefix="engine")
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
            self._engine_thread.submit(self.engine.load).result()
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

    def _enqueue_event(self, kind: str, ts: float) -> None:
        self._events.put((kind, ts))

    def _event_loop(self) -> None:
        while True:
            kind, ts = self._events.get()
            try:
                self._handle_event(kind, ts)
            except Exception:
                log.exception("event %s failed", kind)

    def _handle_event(self, kind: str, ts: float) -> None:
        if kind == "cancel":  # another key struck mid-hold: user wanted fn+<key>
            self._abort_recording("cancelled by key combo")
            return
        if kind == "esc" or kind == "menu-cancel":
            if self.recorder.recording:
                reason = "cancelled by Esc" if kind == "esc" else "cancelled from menu"
                self._abort_recording(reason)
            return
        if kind == "force-finish":  # watchdog: recording ran absurdly long
            if self.recorder.recording:
                self.tap_tracker.cancel()
                self._finish_recording()
            return
        if kind == "press":
            if not self._model_ready.is_set():
                self._overlay_flash("⏳ Model still loading…")
                self._cue(sounds.error_cue)
                return
            action = self.tap_tracker.press(ts)
            if action == "finish":  # tap ends a hands-free recording
                log.info("hands-free recording finished by tap")
                self._finish_recording()
                return
            self.recorder.start()
            log.info("recording started")
            self._cue(sounds.start_cue)
            self._icon(ui.ICON_RECORDING)
            self._overlay_show("● Listening…")
            return
        if kind == "release":
            action = self.tap_tracker.release(ts)
            if action == "none":
                return
            if action == "lock":  # double-tap → hands-free
                log.info("hands-free recording (double-tap) — tap fn to finish")
                self._overlay_show("● Recording — tap fn to finish · Esc cancels")
                return
            if action == "discard":  # lone short tap
                self.recorder.stop()
                self._icon(ui.ICON_IDLE)
                if self.overlay:
                    ui.call_on_main(self.overlay.hide)
                return
            self._finish_recording()

    def _abort_recording(self, reason: str) -> None:
        self.tap_tracker.cancel()
        if self.recorder.recording:
            self.recorder.stop()
            self._icon(ui.ICON_IDLE)
            self._overlay_flash("✕ Cancelled", 0.9)
            log.info("recording %s", reason)

    def on_cancel_recording(self) -> None:  # menu action — works even if the tap is dead
        self._enqueue_event("menu-cancel", time.monotonic())

    def _watchdog(self) -> None:
        """Belt and braces against the stuck-Listening failure: macOS disables
        event taps it finds slow (losing the fn release), so revive the tap
        continuously and auto-finish any recording that runs absurdly long."""
        while True:
            time.sleep(5)
            try:
                self.recorder.reap()  # close the mic stream after idle time
                if self.listener.ensure_enabled():
                    log.warning("event tap was disabled by macOS — re-enabled")
                started = self.tap_tracker.press_time
                if (self.recorder.recording and started is not None
                        and time.monotonic() - started > MAX_RECORDING_SECONDS):
                    log.warning("recording exceeded %ss — auto-finishing", MAX_RECORDING_SECONDS)
                    self._enqueue_event("force-finish", time.monotonic())
            except Exception:
                log.exception("watchdog error")

    def _finish_recording(self) -> None:
        """Dispatcher thread: stop capture fast, hand the slow work off so the
        event queue stays responsive during transcription."""
        audio = self.recorder.stop()
        log.info("recording stopped (%.1fs)", duration_seconds(audio))
        self._cue(sounds.stop_cue)
        threading.Thread(target=self._process_audio, args=(audio,), daemon=True).start()

    def _process_audio(self, audio) -> None:
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
                raw = self._engine_thread.submit(self.engine.transcribe, audio).result()
            except Exception:
                log.exception("transcription failed")
                self._icon(ui.ICON_ERROR)
                self._overlay_flash("⚠️ Transcription failed — see log", 2.5)
                return
            text = format_transcript(raw, self.config, ctx)
            if (text and self.config.llm_enabled
                    and len(text.split()) >= self.config.llm_min_words):
                text = llm_cleanup(text, self.config, ctx)
            elapsed = time.perf_counter() - started

            if not text:
                self._icon(ui.ICON_IDLE)
                self._overlay_flash("… no speech detected", 1.2)
                log.info("no speech (%.2fs, %.1fs speech of %.1fs held)",
                         elapsed, duration_seconds(audio), held)
                return

            ui.call_on_main(self._paste_and_report, text, raw, ctx,
                            duration_seconds(audio), elapsed)

    # -- main-thread finish -------------------------------------------------

    def _paste_and_report(self, text, raw, ctx, audio_seconds: float, elapsed: float) -> None:
        target = ctx.app_name or "app"
        paste_text(text, self.config.restore_clipboard)
        history.add(text, raw_text=raw, app_name=ctx.app_name, bundle_id=ctx.bundle_id,
                    audio_seconds=audio_seconds, elapsed_seconds=elapsed)
        self.status_bar.set_last(text)
        self.status_bar.refresh_history(history.recent(10))
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

    def on_history_copy(self, text: str) -> None:
        copy_text(text)
        if self.config.overlay:
            self.overlay.flash("✓ Copied to clipboard", 1.2)

    def on_open_library(self) -> None:
        ui.open_in_default_app(str(history.render_library()))

    def on_clear_history(self) -> None:
        history.clear()
        self.status_bar.refresh_history([])
        log.info("history cleared")

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
        self.status_bar.refresh_history(history.recent(10))
        self.overlay = ui.Overlay()
        self._connect_hotkey()
        threading.Thread(target=self._event_loop, daemon=True).start()
        threading.Thread(target=self._watchdog, daemon=True).start()
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
