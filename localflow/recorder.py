"""Microphone capture. 16 kHz mono float32 — exactly what Whisper expects,
so no resampling step sits between the mic and the model."""

from __future__ import annotations

import threading

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16_000


class Recorder:
    def __init__(self) -> None:
        self._chunks: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._stream is not None:
                return
            self._chunks = []
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                callback=self._on_audio,
            )
            self._stream.start()

    def _on_audio(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        self._chunks.append(indata.copy())

    def stop(self) -> np.ndarray:
        """Stop capturing and return everything recorded as a 1-D float32 array."""
        with self._lock:
            if self._stream is None:
                return np.zeros(0, dtype=np.float32)
            self._stream.stop()
            self._stream.close()
            self._stream = None
            if not self._chunks:
                return np.zeros(0, dtype=np.float32)
            audio = np.concatenate(self._chunks)[:, 0]
            self._chunks = []
            return audio

    @property
    def recording(self) -> bool:
        return self._stream is not None


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
