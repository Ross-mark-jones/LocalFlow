# LocalFlow

A local, private Wispr Flow clone for macOS. Hold `fn`, speak, release — formatted text lands in whatever app you're in. Runs 100% on-device on Apple Silicon; nothing leaves your Mac.

## Quick start

Open **LocalFlow** from `~/Applications` (or Spotlight). It lives in the menu bar as 🎙 — no Dock icon, no window. Click the icon for all settings; enable **Start at login** there to make it permanent.

Default engine is **Parakeet 110M**: sub-second transcription on an M1 with accuracy above whisper-small at ~250 MB of memory.

### Development

```bash
cd ~/Apps/LocalFlow            # repo lives OUTSIDE iCloud on purpose
./start.sh                     # run from source (env in ~/.localflow/venv)
./scripts/build-app.sh         # rebuild ~/Applications/LocalFlow.app
UV_PROJECT_ENVIRONMENT=~/.localflow/venv uv run python -m pytest
```

Note: after `build-app.sh`, macOS may treat the rebuilt bundle as a new app and re-ask for Accessibility once.

## One-time macOS setup

1. **Accessibility** — on first launch the app prompts and waits; enable **LocalFlow** in System Settings → Privacy & Security → Accessibility and it connects automatically.
2. **Microphone** — macOS prompts on first dictation; approve it.
3. **Globe key** — System Settings → Keyboard → "Press 🌐 key to" → **Do Nothing** (`./start.sh doctor` checks this).

## CLI (from the repo)

| Command | What it does |
|---|---|
| `./start.sh` | Run the menu-bar app from source |
| `./start.sh doctor` | Check permissions and keyboard settings |
| `./start.sh transcribe file.wav` | Test the pipeline on an audio file, no mic needed |
| `./start.sh --model mlx-community/whisper-base.en-mlx` | Try a different model |
| `./start.sh --key right_cmd` | Use a different hold key |

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
