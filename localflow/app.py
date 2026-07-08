"""LocalFlow runtime: wires hotkey → recorder → ASR → formatter → paste.

Threading model: the CFRunLoop (hotkey tap) owns the main thread. Press/release
callbacks arrive on short-lived worker threads; transcription work is serialised
by a lock so a rapid second dictation queues instead of interleaving pastes.
"""

from __future__ import annotations

import sys
import threading
import time

from . import sounds
from .config import Config
from .context import current_context
from .engine import MLXWhisperEngine
from .formatter import format_transcript, llm_cleanup
from .hotkey import HotkeyListener
from .inserter import paste_text
from .recorder import Recorder, duration_seconds

MIN_UTTERANCE_SECONDS = 0.3


class LocalFlowApp:
    def __init__(self, config: Config):
        self.config = config
        self.engine = MLXWhisperEngine(config.model, config.language)
        self.recorder = Recorder()
        self._transcribe_lock = threading.Lock()
        self._model_ready = threading.Event()

    def _load_model(self) -> None:
        print(f"Loading model {self.config.model} (first run downloads weights)...")
        started = time.perf_counter()
        self.engine.load()
        print(f"Model ready in {time.perf_counter() - started:.1f}s. "
              f"Hold [{self.config.hotkey}] and speak.")
        self._model_ready.set()

    def _on_press(self) -> None:
        if not self._model_ready.is_set():
            sounds.error_cue()
            return
        self.recorder.start()
        sounds.start_cue()

    def _on_release(self) -> None:
        audio = self.recorder.stop()
        sounds.stop_cue()
        if duration_seconds(audio) < MIN_UTTERANCE_SECONDS:
            return
        with self._transcribe_lock:
            started = time.perf_counter()
            ctx = current_context(self.config)
            raw = self.engine.transcribe(audio)
            text = format_transcript(raw, self.config, ctx)
            if text and self.config.llm_enabled:
                text = llm_cleanup(text, self.config, ctx)
            elapsed = time.perf_counter() - started
            if not text:
                print(f"(no speech detected, {elapsed:.2f}s)")
                return
            paste_text(text)
            target = ctx.app_name or "active app"
            print(f"→ {target} in {elapsed:.2f}s: {text[:80]}{'…' if len(text) > 80 else ''}")

    def run(self) -> None:
        threading.Thread(target=self._load_model, daemon=True).start()
        listener = HotkeyListener(self.config.hotkey, self._on_press, self._on_release)
        try:
            listener.run()  # blocks in CFRunLoop
        except PermissionError as error:
            print(f"\n{error}", file=sys.stderr)
            sys.exit(1)
