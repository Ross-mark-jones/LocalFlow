"""ASR engines. MLX Whisper is the default; the Engine protocol keeps the door
open for Parakeet (via parakeet-mlx) or whisper.cpp without touching callers."""

from __future__ import annotations

from typing import Protocol

import numpy as np


class Engine(Protocol):
    def load(self) -> None: ...
    def transcribe(self, audio: "np.ndarray | str") -> str: ...


class MLXWhisperEngine:
    """Whisper on Apple Silicon via MLX. Model weights download from Hugging Face
    on first use and are cached in ~/.cache/huggingface."""

    def __init__(self, model: str, language: str | None = None):
        self.model = model
        self.language = language

    def load(self) -> None:
        """Warm up: transcribing a beat of silence forces the model download and
        Metal kernel compilation so the first real dictation isn't slow."""
        import mlx_whisper  # deferred: ~2s import cost

        silence = np.zeros(int(0.5 * 16_000), dtype=np.float32)
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
