"""Microphone capture. 16 kHz mono float32 — exactly what Whisper expects,
so no resampling step sits between the mic and the model.

The stream is persistent: start()/stop() only toggle a capture flag. Opening
and closing CoreAudio streams in quick succession (which double-tap
hands-free mode does) can wedge PortAudio so hard that stop() blocks forever
— with a persistent stream, stop() is a flag flip plus an array concat and
can never hang the event dispatcher. The watchdog calls reap() to actually
close the stream after ~10s of no dictation, so the mic indicator doesn't
stay on permanently.
"""

from __future__ import annotations

import logging
import threading
import time

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16_000
STREAM_IDLE_CLOSE_SECONDS = 10

log = logging.getLogger("localflow")


class Recorder:
    def __init__(self) -> None:
        self._chunks: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._capturing = False
        self._last_use = 0.0
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._capturing:
                return
            if self._stream is None:
                self._stream = sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    channels=1,
                    dtype="float32",
                    callback=self._on_audio,
                )
                self._stream.start()
            self._chunks = []
            self._capturing = True

    def _on_audio(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        if self._capturing:
            self._chunks.append(indata.copy())

    def stop(self) -> np.ndarray:
        """Stop capturing and return the audio. Never touches the underlying
        stream, so it cannot block."""
        with self._lock:
            self._capturing = False
            self._last_use = time.monotonic()
            if not self._chunks:
                return np.zeros(0, dtype=np.float32)
            audio = np.concatenate(self._chunks)[:, 0]
            self._chunks = []
            return audio

    def reap(self) -> None:
        """Close the stream after idle time. Called from the watchdog thread —
        if CoreAudio ever wedges on close, only the watchdog stalls, never the
        event dispatcher."""
        with self._lock:
            if self._stream is None or self._capturing:
                return
            if time.monotonic() - self._last_use < STREAM_IDLE_CLOSE_SECONDS:
                return
            stream, self._stream = self._stream, None
        try:
            stream.stop()
            stream.close()
        except Exception:
            log.exception("closing idle audio stream failed")

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
