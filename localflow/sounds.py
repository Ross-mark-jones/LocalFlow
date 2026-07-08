"""Audio cues. Wispr plays a tone so you know exactly when to start speaking —
without one, users clip their first word."""

from __future__ import annotations

from AppKit import NSSound

_cache: dict[str, object] = {}


def play(name: str) -> None:
    """Play a named macOS system sound (Pop, Tink, Morse, ...). Silent no-op if missing."""
    sound = _cache.get(name)
    if sound is None:
        sound = NSSound.soundNamed_(name)
        if sound is None:
            return
        _cache[name] = sound
    sound.stop()
    sound.play()


def start_cue() -> None:
    play("Pop")


def stop_cue() -> None:
    play("Bottle")


def error_cue() -> None:
    play("Basso")
