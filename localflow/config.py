"""Configuration for LocalFlow.

Config lives at ~/.config/localflow/config.toml, personal dictionary at
~/.config/localflow/dictionary.txt (one `spoken -> written` pair per line).
Both are created with defaults on first run.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "localflow"
CONFIG_FILE = CONFIG_DIR / "config.toml"
DICTIONARY_FILE = CONFIG_DIR / "dictionary.txt"
SETTINGS_FILE = CONFIG_DIR / "settings.json"  # menu-bar toggles, overlaid on the TOML
LOG_FILE = CONFIG_DIR / "localflow.log"

DEFAULT_CONFIG = """\
# LocalFlow configuration

[hotkey]
# Hold this key to record, release to transcribe.
# Options: fn, right_cmd, right_alt, right_ctrl, right_shift
key = "fn"

[asr]
# Any mlx-community Whisper repo. large-v3-turbo is the accuracy/speed sweet spot
# (~1.6 GB download on first run). Use "mlx-community/whisper-base.en" for a
# lightweight English-only model (~80 MB).
model = "mlx-community/whisper-large-v3-turbo"
# Force a language code (e.g. "en") or leave empty to auto-detect.
language = "en"

[formatting]
remove_fillers = true
spoken_commands = true   # "new line" / "new paragraph" become line breaks
capitalize = true

[ui]
sounds = true
overlay = true           # floating "Listening…" pill while recording
# Restore the previous clipboard after pasting. Off by default: the restore
# can race slow apps' paste handlers, and leaving the transcript on the
# clipboard means a failed paste is one manual Cmd+V away.
restore_clipboard = false

[llm]
# Optional second pass through a local LLM via Ollama for heavier cleanup.
# Requires `brew install ollama` and a pulled model, e.g. `ollama pull qwen2.5:1.5b`.
enabled = false
model = "qwen2.5:1.5b"
url = "http://localhost:11434"

# Per-app tone profiles, keyed by bundle id. `casual = true` drops the trailing
# period on single-sentence messages (Slack/iMessage style).
[apps."com.tinyspeck.slackmacgap"]
casual = true

[apps."com.apple.MobileSMS"]
casual = true
"""

DEFAULT_DICTIONARY = """\
# Personal dictionary: one `spoken -> written` pair per line. Case-insensitive
# match on the left, exact replacement on the right. Lines starting with # are
# ignored.
# wispr -> Wispr
# something new -> Something New
"""


@dataclass
class AppProfile:
    casual: bool = False


@dataclass
class Config:
    hotkey: str = "fn"
    model: str = "mlx-community/whisper-large-v3-turbo"
    language: str | None = "en"
    remove_fillers: bool = True
    spoken_commands: bool = True
    capitalize: bool = True
    sounds: bool = True
    overlay: bool = True
    # Off by default: restoring the old clipboard too soon races slow apps'
    # paste handlers, and keeping the transcript on the clipboard means a
    # failed paste is always recoverable with Cmd+V.
    restore_clipboard: bool = False
    llm_enabled: bool = False
    llm_model: str = "qwen2.5:1.5b"
    llm_url: str = "http://localhost:11434"
    app_profiles: dict[str, AppProfile] = field(default_factory=dict)
    dictionary: dict[str, str] = field(default_factory=dict)

# Keys the menu-bar UI may persist to settings.json.
TOGGLEABLE = ("remove_fillers", "spoken_commands", "capitalize", "sounds",
              "overlay", "restore_clipboard", "llm_enabled", "model", "hotkey")


def ensure_config_files() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(DEFAULT_CONFIG)
    if not DICTIONARY_FILE.exists():
        DICTIONARY_FILE.write_text(DEFAULT_DICTIONARY)


def load_dictionary(path: Path = DICTIONARY_FILE) -> dict[str, str]:
    entries: dict[str, str] = {}
    if not path.exists():
        return entries
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "->" not in line:
            continue
        spoken, _, written = line.partition("->")
        spoken, written = spoken.strip(), written.strip()
        if spoken and written:
            entries[spoken] = written
    return entries


def load_settings_overrides() -> dict:
    import json

    if not SETTINGS_FILE.exists():
        return {}
    try:
        data = json.loads(SETTINGS_FILE.read_text())
        return {k: v for k, v in data.items() if k in TOGGLEABLE}
    except (json.JSONDecodeError, OSError):
        return {}


def save_setting(key: str, value) -> None:
    import json

    if key not in TOGGLEABLE:
        raise ValueError(f"Not a persistable setting: {key}")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = {}
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            data = {}
    data[key] = value
    SETTINGS_FILE.write_text(json.dumps(data, indent=2))


def load_config() -> Config:
    ensure_config_files()
    raw = tomllib.loads(CONFIG_FILE.read_text())
    cfg = Config()
    cfg.hotkey = raw.get("hotkey", {}).get("key", cfg.hotkey)
    asr = raw.get("asr", {})
    cfg.model = asr.get("model", cfg.model)
    cfg.language = asr.get("language") or None
    fmt = raw.get("formatting", {})
    cfg.remove_fillers = fmt.get("remove_fillers", cfg.remove_fillers)
    cfg.spoken_commands = fmt.get("spoken_commands", cfg.spoken_commands)
    cfg.capitalize = fmt.get("capitalize", cfg.capitalize)
    llm = raw.get("llm", {})
    cfg.llm_enabled = llm.get("enabled", cfg.llm_enabled)
    cfg.llm_model = llm.get("model", cfg.llm_model)
    cfg.llm_url = llm.get("url", cfg.llm_url)
    fmt2 = raw.get("ui", {})
    cfg.sounds = fmt2.get("sounds", cfg.sounds)
    cfg.overlay = fmt2.get("overlay", cfg.overlay)
    cfg.restore_clipboard = fmt2.get("restore_clipboard", cfg.restore_clipboard)
    for bundle_id, profile in raw.get("apps", {}).items():
        cfg.app_profiles[bundle_id] = AppProfile(casual=profile.get("casual", False))
    cfg.dictionary = load_dictionary()
    # Menu-bar settings win over the TOML: they're the user's latest choice.
    for key, value in load_settings_overrides().items():
        setattr(cfg, key, value)
    return cfg
