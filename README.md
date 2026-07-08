# LocalFlow

A local, private Wispr Flow clone for macOS. Hold `fn`, speak, release — formatted text lands in whatever app you're in. Runs 100% on-device on Apple Silicon; nothing leaves your Mac.

## Quick start

```bash
cd LocalFlow
uv sync                # one-time install
uv run localflow doctor    # check permissions (see below)
uv run localflow           # run it — hold fn and speak
```

First run downloads the ASR model (~1.6 GB for the default `whisper-large-v3-turbo`) and warms it up. After that, dictations transcribe in well under a second.

## One-time macOS setup

`localflow doctor` checks all of these:

1. **Accessibility** — System Settings → Privacy & Security → Accessibility → enable your terminal app (needed for the global hotkey and pasting).
2. **Microphone** — macOS prompts on first recording; approve it.
3. **Globe key** — System Settings → Keyboard → "Press 🌐 key to" → **Do Nothing** (otherwise the emoji picker fights with hold-to-talk).

## Usage

| Command | What it does |
|---|---|
| `uv run localflow` | Run the dictation app (hold `fn`, speak, release) |
| `uv run localflow doctor` | Check permissions and keyboard settings |
| `uv run localflow transcribe file.wav` | Test the pipeline on an audio file, no mic needed |
| `uv run localflow --model mlx-community/whisper-base.en` | Use a smaller/faster model |
| `uv run localflow --key right_cmd` | Use a different hold key |

## Configuration

Created on first run:

- `~/.config/localflow/config.toml` — hotkey, model, formatting toggles, per-app tone profiles, optional local-LLM cleanup via Ollama
- `~/.config/localflow/dictionary.txt` — personal dictionary (`spoken -> Written` per line), the fix for names and brand terms ASR gets wrong

### Optional LLM cleanup

For Wispr-style heavier rewriting (false starts, rambling → clean prose), install [Ollama](https://ollama.com) and enable it:

```bash
brew install ollama
ollama pull qwen2.5:1.5b
# then set llm.enabled = true in ~/.config/localflow/config.toml
```

The rules pipeline (filler removal, punctuation, capitalisation, spoken commands like "new line", per-app tone) runs regardless and needs nothing extra.

## How it compares to Wispr Flow

Wispr Flow streams your audio to their cloud (their own ASR + personalised LLM, ~700 ms round trip). LocalFlow runs the same shaped pipeline — ASR → formatting layer → paste into the frontmost app — entirely on-device, so it's private, free, and works offline. What it doesn't have (yet): learning from your corrections, screen-content context, code-switched multilingual ASR, and a native menu-bar UI. See [PLAN.md](PLAN.md) for the roadmap.
