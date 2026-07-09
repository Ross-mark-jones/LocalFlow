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
        # Short critical section (a list append) so it can't race the reads in
        # flush_segment/stop. The callback must stay quick — no heavy work here.
        with self._lock:
            if self._capturing:
                self._chunks.append(indata.copy())

    def stop(self) -> np.ndarray:
        """Stop capturing and return whatever audio is still buffered (the
        un-flushed tail, in streaming mode). Never touches the stream."""
        with self._lock:
            self._capturing = False
            return self._take_buffer()

    def _take_buffer(self) -> np.ndarray:
        if not self._chunks:
            return np.zeros(0, dtype=np.float32)
        audio = np.concatenate(self._chunks)[:, 0]
        self._chunks = []
        return audio

    def flush_segment(
        self,
        pause_seconds: float = 0.7,
        min_speech_seconds: float = 1.0,
        max_segment_seconds: float = 30.0,
        silence_threshold: float = 0.01,
    ) -> "np.ndarray | None":
        """For streaming/hands-free mode: return a completed speech segment when
        the speaker pauses (trailing silence >= pause_seconds) or the buffer
        reaches max_segment_seconds, else None. The returned audio is removed
        from the buffer so the next segment starts clean. Pausing on natural
        gaps means cuts land between words, not through them."""
        with self._lock:
            if not self._chunks:
                return None
            buf = np.concatenate(self._chunks)[:, 0]
            n = len(buf)
            if n < int(min_speech_seconds * SAMPLE_RATE):
                # Not enough yet — but don't let pure silence accumulate forever.
                if n > int(max_segment_seconds * SAMPLE_RATE) and float(np.abs(buf).max()) < silence_threshold:
                    self._chunks = []
                return None
            pause_n = int(pause_seconds * SAMPLE_RATE)
            tail = buf[-pause_n:] if n >= pause_n else buf
            tail_silent = float(np.abs(tail).max()) < silence_threshold
            over_max = n >= int(max_segment_seconds * SAMPLE_RATE)
            if not (tail_silent or over_max):
                return None
            if float(np.abs(buf).max()) < silence_threshold:
                self._chunks = []  # all silence — drop it, emit nothing
                return None
            self._chunks = []
            return trim_silence(buf)

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
