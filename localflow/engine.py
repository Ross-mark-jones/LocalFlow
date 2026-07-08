"""ASR engines, selected by model name via create_engine().

Parakeet (NVIDIA's TDT architecture, via parakeet-mlx) is the default: on an
M1 it transcribes 10s of speech in well under a second with accuracy above
whisper-small, at ~250 MB resident for the 110M variant. MLX Whisper remains
for multilingual/turbo use.
"""

from __future__ import annotations

import os
import tempfile
import wave
from typing import Protocol

import numpy as np

SAMPLE_RATE = 16_000


class Engine(Protocol):
    def load(self) -> None: ...
    def transcribe(self, audio: "np.ndarray | str") -> str: ...


def create_engine(model: str, language: str | None = None) -> "Engine":
    if "parakeet" in model.lower():
        return ParakeetEngine(model)
    return MLXWhisperEngine(model, language)


def _to_wav_file(audio: np.ndarray) -> str:
    """Parakeet's transcribe() only accepts paths, so bridge arrays through a
    temp WAV (16-bit PCM). Milliseconds of overhead, deleted by the caller."""
    fd, path = tempfile.mkstemp(suffix=".wav", prefix="localflow_")
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    with os.fdopen(fd, "wb") as raw, wave.open(raw, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())
    return path


PARAGRAPH_PAUSE_SECONDS = 1.2


def stitch_sentences(sentences: "list[tuple[str, float, float]]") -> str:
    """Join (text, start, end) sentence tuples, turning long pauses between
    them into paragraph breaks — dictated structure for free."""
    parts: list[str] = []
    prev_end: float | None = None
    for text, start, end in sentences:
        text = text.strip()
        if not text:
            continue
        if prev_end is not None:
            parts.append("\n\n" if (start - prev_end) >= PARAGRAPH_PAUSE_SECONDS else " ")
        parts.append(text)
        prev_end = end
    return "".join(parts)


class ParakeetEngine:
    """Parakeet TDT on Apple Silicon via parakeet-mlx."""

    def __init__(self, model: str):
        self.model = model
        self._pk = None

    def load(self) -> None:
        from parakeet_mlx import from_pretrained  # deferred import

        self._pk = from_pretrained(self.model)
        # Warm-up compiles the Metal kernels so the first dictation is fast.
        self.transcribe(np.zeros(int(0.5 * SAMPLE_RATE), dtype=np.float32))

    def _result_text(self, result) -> str:
        try:
            sentences = [(s.text, s.start, s.end) for s in result.sentences]
            if sentences:
                return stitch_sentences(sentences).strip()
        except AttributeError:
            pass  # parakeet-mlx version without sentence timing
        return result.text.strip()

    def transcribe(self, audio: "np.ndarray | str") -> str:
        if self._pk is None:
            self.load()
        if isinstance(audio, str):
            return self._result_text(self._pk.transcribe(audio))
        path = _to_wav_file(audio)
        try:
            return self._result_text(self._pk.transcribe(path))
        finally:
            os.unlink(path)


class MLXWhisperEngine:
    """Whisper on Apple Silicon via MLX. Model weights download from Hugging Face
    on first use and are cached in ~/.cache/huggingface."""

    def __init__(self, model: str, language: str | None = None):
        self.model = model
        self.language = language

    def load(self) -> None:
        import mlx_whisper  # deferred: ~2s import cost

        silence = np.zeros(int(0.5 * SAMPLE_RATE), dtype=np.float32)
        mlx_whisper.transcribe(silence, path_or_hf_repo=self.model, language=self.language)

    def transcribe(self, audio: "np.ndarray | str") -> str:
        import mlx_whisper

        result = mlx_whisper.transcribe(
            audio,
            path_or_hf_repo=self.model,
            language=self.language,
            condition_on_previous_text=False,
        )
        return result["text"].strip()
