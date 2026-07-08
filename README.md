# LocalFlow 🎙

Talk instead of type, anywhere on your Mac. **Hold the `fn` (🌐) key, speak, release** — your words appear wherever your cursor is, already cleaned up: no "um"s, proper punctuation, proper capitalisation.

Free, open source, and 100% private: speech recognition runs entirely on your Mac (Apple Silicon + MLX). Nothing you say ever leaves it. No subscription, no account, no cloud.

## Install (2 minutes)

You need an Apple Silicon Mac (M1 or newer) and [Homebrew](https://brew.sh). Then paste this into Terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/Ross-mark-jones/LocalFlow/main/install.sh | sh
```

The installer sets everything up and opens the app. Two one-time permission prompts follow:

1. **Accessibility** — a dialog appears; click *Open System Settings*, turn **LocalFlow** on. The app connects by itself.
2. **Microphone** — on your first dictation, click *Allow*.

That's it. Look for the **🎙 in your menu bar**. The first launch downloads the speech model (~600 MB) — give it a minute.

## Using it

- **Hold `fn`, speak, release.** A pill appears at the bottom of your screen ("● Listening…") so you always know when it's recording. Your text pastes into whatever app you're in — usually in under a second.
- Say **"new line"** or **"new paragraph"** for line breaks.
- Pressing any other key while holding `fn` cancels the recording (so `fn`+arrow shortcuts still work).
- Your transcript is also left on the clipboard — if a paste ever misses, just Cmd+V.

## The 🎙 menu

| | |
|---|---|
| **History** | Your recent dictations — click one to copy it. *Open Library…* gives you a searchable page of everything you've ever dictated (stored only on your Mac). |
| **Toggles** | Filler-word removal, spoken commands, auto-capitalise, sounds, the overlay pill, clipboard behaviour. |
| **Model** | Parakeet 110M is the default (fast + accurate). Bigger models available for 16 GB+ Macs. |
| **Hold-to-talk key** | Prefer right-⌘ or right-⌥ over `fn`? Switch here. |
| **Personal dictionary** | Teach it names and brand terms it mishears: one `spoken -> Written` line each. |
| **Start at login** | Make it always-on. |

## How it works

Wispr Flow-style pipeline, entirely on-device: a Quartz event tap watches the `fn` key → mic audio (16 kHz) → [Parakeet TDT](https://huggingface.co/mlx-community/parakeet-tdt_ctc-110m) speech recognition via MLX on the Apple Silicon GPU → a rules formatter (fillers, hallucination filter, personal dictionary, per-app tone — casual in Slack/iMessage, formal elsewhere) → clipboard paste into the frontmost app. An optional [Ollama](https://ollama.com) pass adds LLM-grade cleanup if you want it.

## Development

```bash
cd ~/Apps/LocalFlow
./start.sh                     # run from source (env lives in ~/.localflow/venv)
./scripts/build-app.sh         # rebuild /Applications/LocalFlow.app
UV_PROJECT_ENVIRONMENT=~/.localflow/venv uv run python -m pytest
```

Three hard-won constraints, learned the painful way — see [PLAN.md](PLAN.md) for the roadmap:

1. The bundle's main executable must be the compiled `scripts/launcher.c` binary — a script executable runs under `/bin/sh` and macOS attributes permission checks to Apple's shell, so Accessibility grants never match.
2. All MLX engine calls run on one dedicated thread — MLX compute streams are thread-bound.
3. Keep the Python env out of iCloud-synced folders — iCloud evicts venv files and imports break intermittently.

## Troubleshooting

- **Nothing happens when I hold `fn`** → System Settings → Privacy & Security → Accessibility → LocalFlow must be ON. Also set Keyboard → "Press 🌐 key to" → *Do Nothing*.
- **Dictations come back empty** → check Microphone permission for LocalFlow.
- **Anything else** → every dictation is logged with timings at `~/.config/localflow/localflow.log`.

## Licence

[MIT](LICENSE) — built by Ross Jones with Claude.
