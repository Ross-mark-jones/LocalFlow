"""Microphone capture. 16 kHz mono float32 — exactly what Whisper expects,
so no resampling step sits between the mic and the model.

One long-lived stream, opened once and kept open for the app's lifetime.
start()/stop() only toggle a capture flag. This matters: PortAudio on macOS
throws paInternalError (-9986) if you close and reopen an input stream, so any
open/close churn eventually wedges the mic entirely. A single persistent
stream sidesteps that completely — the cost is the mic indicator staying lit
while LocalFlow runs, which is honest for an always-listening dictation tool.
"""

from __future__ import annotations

import logging
import threading

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16_000

log = logging.getLogger("localflow")


class Recorder:
    def __init__(self) -> None:
        self._chunks: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._capturing = False
        self._lock = threading.Lock()

    def _open_stream(self) -> sd.InputStream:
        stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            callback=self._on_audio,
        )
        stream.start()
        return stream

    def _ensure_stream(self) -> None:
        """Open the persistent stream if needed. On PortAudio's internal error
        (state gone bad after sleep/wake or a device change), reset PortAudio
        once and retry — the recovery path for a mic that stopped responding."""
        if self._stream is not None and self._stream.active:
            return
        if self._stream is not None:
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        try:
            self._stream = self._open_stream()
        except sd.PortAudioError:
            log.warning("input stream open failed — resetting PortAudio and retrying")
            try:
                sd._terminate()
                sd._initialize()
            except Exception:
                log.exception("PortAudio reset failed")
            self._stream = self._open_stream()  # if this raises, caller handles it

    def warm_up(self) -> None:
        """Open the stream up front so the first dictation isn't the one that
        discovers a mic problem. Safe to call before permissions are granted;
        failures are logged, not raised."""
        with self._lock:
            try:
                self._ensure_stream()
            except Exception:
                log.exception("microphone warm-up failed")

    def start(self) -> bool:
        """Begin capturing. Returns False if the mic can't be opened (caller
        should surface an error rather than pretend it's recording)."""
        with self._lock:
            try:
                self._ensure_stream()
            except Exception:
                log.exception("could not start microphone")
                return False
            self._chunks = []
            self._capturing = True
            return True

    def _on_audio(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        if self._capturing:
            self._chunks.append(indata.copy())

    def stop(self) -> np.ndarray:
        """Stop capturing and return the audio. Never touches the stream, so it
        cannot block or fail."""
        with self._lock:
            self._capturing = False
            if not self._chunks:
                return np.zeros(0, dtype=np.float32)
            audio = np.concatenate(self._chunks)[:, 0]
            self._chunks = []
            return audio

    @property
    def recording(self) -> bool:
        return self._capturing


def duration_seconds(audio: np.ndarray) -> float:
    return len(audio) / SAMPLE_RATE


MAX_UTTERANCE_SECONDS = 120


def trim_silence(audio: np.ndarray, pad_seconds: float = 0.25) -> np.ndarray:
    """Cut leading/trailing silence so Whisper only processes actual speech —
    on memory-tight machines the difference between 2s and 30s of inference.
    Returns an empty array when there's no signal above the noise floor."""
    if audio.size == 0:
        return audio
    peak = float(np.abs(audio).max())
    threshold = max(0.005, peak * 0.05)
    loud = np.where(np.abs(audio) > threshold)[0]
    if loud.size == 0:
        return np.zeros(0, dtype=np.float32)
    pad = int(pad_seconds * SAMPLE_RATE)
    start = max(0, int(loud[0]) - pad)
    end = min(len(audio), int(loud[-1]) + pad)
    trimmed = audio[start:end]
    return trimmed[: MAX_UTTERANCE_SECONDS * SAMPLE_RATE]
