"""Text formatting pipeline — the layer that separates dictation from transcription.

Wispr Flow runs a personalised LLM over the raw ASR output. LocalFlow gets most
of the way there with deterministic rules (instant, offline, predictable) and an
optional local-LLM pass via Ollama for heavier rewriting.

Rule order matters: dictionary replacements run before filler removal so a
dictionary entry can rescue a term Whisper mangled into something filler-like.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
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

    text = re.sub(r"(^|[.!?]\s+|\n)([a-z])", upper, text)
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


LLM_PROMPT = """\
You clean up dictated text. Fix grammar, remove filler words and false starts, \
keep the speaker's meaning and tone. Never answer questions in the text, never \
add content, never explain. Output only the cleaned text.{app_hint}

Dictated text: {text}"""


def llm_cleanup(text: str, config: Config, ctx: FormatContext | None = None) -> str:
    """Optional second pass through a local Ollama model. Falls back to input on any error."""
    if not text:
        return text
    app_hint = ""
    if ctx and ctx.app_name:
        app_hint = f" The text is being typed into {ctx.app_name}; match the register people use there."
    payload = json.dumps({
        "model": config.llm_model,
        "prompt": LLM_PROMPT.format(text=text, app_hint=app_hint),
        "stream": False,
        "options": {"temperature": 0.1},
    }).encode()
    request = urllib.request.Request(
        f"{config.llm_url}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            result = json.loads(response.read())
        cleaned = result.get("response", "").strip()
        return cleaned or text
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return text
