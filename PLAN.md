# LocalFlow — Research & Roadmap

## How Wispr Flow works (research summary, July 2026)

Sources: Wispr's engineering blog ("Technical challenges and breakthroughs behind Flow"), third-party reviews, and the open-source clone ecosystem (VoiceInk, local-dictation, Yap, OpenWhispr).

**Architecture.** Wispr Flow is a *cloud* product. The desktop client captures audio while you hold `fn` and streams it to their servers. Their pipeline: proprietary context-conditioned ASR models (target <200 ms) → a personalised LLM formatting layer with token-level style control (<200 ms) → back over the network (~200 ms budget) → pasted into the focused text field. Total target: **~700 ms** from when you stop speaking.

**What the client actually does locally.** Global `fn`-key listener (Quartz event tap — fn only surfaces as a `flagsChanged` modifier event), mic capture, start/stop tones, a recording indicator, frontmost-app detection for tone matching, and text insertion via clipboard-swap + synthetic Cmd+V. Permissions: Microphone + Accessibility.

**The "magic" beyond raw transcription.**
- Filler-word removal, auto-punctuation, auto-capitalisation
- Tone matching per app (casual in Slack, formal in Docs)
- Personal dictionary for names/jargon
- Learning from user corrections (their stated goal: "never make the same mistake twice")
- Code-switched multilingual ASR; whispered/sub-audible speech support
- Uncertainty communication (when to review the output)

**Key insight for a local clone:** on Apple Silicon, on-device ASR (MLX Whisper, Parakeet TDT) beats Wispr's 700 ms cloud budget — open-source projects hit 300–400 ms per utterance with zero network. The hard part isn't the ASR; it's the formatting layer and the OS integration, both very buildable.

## What's built (Phase 1 — MVP, done)

Pipeline mirroring Wispr's shape, fully on-device:

| Component | Implementation |
|---|---|
| Hold-to-talk | Quartz CGEventTap on `flagsChanged`, default `fn`, configurable |
| Capture | sounddevice, 16 kHz mono float32 (Whisper-native) |
| ASR | MLX Whisper (`whisper-large-v3-turbo` default, pluggable) |
| Formatting | Rules: fillers, hallucination filter, spoken commands, dictionary, capitalisation, per-app tone |
| LLM cleanup | Optional Ollama pass (off by default) |
| Insertion | Clipboard-swap + synthetic Cmd+V, clipboard restored |
| Context | Frontmost app bundle id → tone profile |
| Preflight | `localflow doctor` checks Accessibility, mic, globe-key setting |

Verified: 10/10 unit tests; end-to-end file transcription through the real model on this machine.

## Phase 2 — Daily-driver polish

- **Menu-bar app + recording indicator** (rumps or a small Swift shell) so it runs without a terminal window
- **Launch at login** via LaunchAgent
- **Hands-free toggle mode** (double-tap fn to lock recording)
- **Streaming feel**: chunked transcription while still speaking for long dictations
- **Parakeet TDT engine** (`parakeet-mlx`) — faster than Whisper for English, the VoiceInk/local-dictation choice
- **History window**: last N dictations, click to re-copy

## Phase 3 — The Wispr magic

- **Correction learning**: watch the pasted text for immediate user edits (Accessibility observers), store correction pairs, auto-grow the dictionary
- **Richer context**: feed the focused text field's existing content (AX API) to the LLM pass for continuation-aware formatting
- **Per-app LLM prompts**: email register for Mail/Gmail tabs, commit-message style for terminals
- **Multilingual**: Whisper already code-switches reasonably; expose language auto-detect profiles

## Phase 4 — Native app (optional)

Swift rewrite following VoiceInk's architecture (whisper.cpp + FluidAudio, KeyboardShortcuts, proper permission prompts, notarised .app). Only worth it if LocalFlow becomes a daily habit — or consider adopting/forking VoiceInk (GPL-3.0) directly instead of maintaining a parallel native app.
