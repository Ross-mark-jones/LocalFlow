"""Text formatting pipeline — the layer that separates dictation from transcription.

Wispr Flow runs a personalised LLM over the raw ASR output. LocalFlow gets most
of the way there with deterministic rules — instant, offline, predictable, and
with no model to keep resident in memory.

Rule order matters: dictionary replacements run before filler removal so a
dictionary entry can rescue a term Whisper mangled into something filler-like.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config import AppProfile, Config

# Fillers only ever removed as standalone words. Deliberately conservative:
# "like" and "so" carry meaning too often to strip safely without an LLM.
FILLERS = r"um+|uh+|erm+|uhm+|mmm+|hmm+"

# Whisper hallucinates these on silence / noise-only audio — often repeated
# ("Thank you. Thank you."), so the filter checks sentence-by-sentence.
HALLUCINATIONS = {
    "thank you", "thanks for watching", "thank you for watching",
    "you", "bye", "bye bye", "the end", "so",
}


def is_hallucination(text: str) -> bool:
    """True when every sentence is a known silence-hallucination phrase."""
    sentences = [s.strip().lower() for s in re.split(r"[.!?]+", text) if s.strip()]
    if not sentences:
        return True
    return all(s in HALLUCINATIONS for s in sentences)

# Strip a comma glued to the command (ASR artefact) but never a preceding
# period — that belongs to the sentence before the command.
SPOKEN_COMMANDS = [
    (re.compile(r",?\s*\bnew paragraph\b[,.]?\s*", re.IGNORECASE), "\n\n"),
    (re.compile(r",?\s*\bnew line\b[,.]?\s*", re.IGNORECASE), "\n"),
    (re.compile(r",?\s*\bbullet point\b[,.:]?\s*", re.IGNORECASE), "\n- "),
    # Spoken punctuation. The phrases are near-unambiguous in dictation;
    # "full stop" included for NZ/UK speakers.
    (re.compile(r"[,.]?\s*\bquestion mark\b", re.IGNORECASE), "?"),
    (re.compile(r"[,.]?\s*\bexclamation (?:mark|point)\b", re.IGNORECASE), "!"),
    (re.compile(r"[,.]?\s*\bfull stop\b", re.IGNORECASE), "."),
]


@dataclass
class FormatContext:
    """What we know about where the text is going."""

    bundle_id: str | None = None
    app_name: str | None = None
    profile: AppProfile | None = None


def _apply_dictionary(text: str, dictionary: dict[str, str]) -> str:
    for spoken, written in dictionary.items():
        pattern = re.compile(rf"\b{re.escape(spoken)}\b", re.IGNORECASE)
        text = pattern.sub(written, text)
    return text


def _remove_fillers(text: str) -> str:
    # Drop the filler and any punctuation immediately following it.
    text = re.sub(rf"\b(?:{FILLERS})\b[,.]?\s*", "", text, flags=re.IGNORECASE)
    # Collapse punctuation orphaned by the removal: " , word" / ",," etc.
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = re.sub(r"([,.!?;:])\1+", r"\1", text)
    text = re.sub(r"^[\s,.;:]+", "", text)
    return text


def _apply_spoken_commands(text: str) -> str:
    for pattern, replacement in SPOKEN_COMMANDS:
        text = pattern.sub(replacement, text)
    return text


def _tidy_whitespace(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


def _capitalize_sentences(text: str) -> str:
    def upper(match: re.Match) -> str:
        return match.group(1) + match.group(2).upper()

    text = re.sub(r"(^|[.!?]\s+|\n(?:- )?)([a-z])", upper, text)
    return text


def format_transcript(raw: str, config: Config, ctx: FormatContext | None = None) -> str:
    """Run the full rules pipeline over raw ASR output."""
    text = raw.strip()
    if not text or is_hallucination(text):
        return ""

    text = _apply_dictionary(text, config.dictionary)
    if config.remove_fillers:
        text = _remove_fillers(text)
    if config.spoken_commands:
        text = _apply_spoken_commands(text)
    text = _tidy_whitespace(text)
    if config.capitalize:
        text = _capitalize_sentences(text)

    profile = ctx.profile if ctx else None
    if profile and profile.casual and "\n" not in text and text.endswith("."):
        # Single-sentence message in a chat app: trailing period reads as curt.
        if text.count(".") == 1:
            text = text[:-1]

    return text
