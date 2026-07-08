# LocalFlow Design — 2026-07-08

## Goal

Recreate Wispr Flow's base functionality locally on macOS: hold a key, speak, release, and cleaned-up text appears in the active app. Private (on-device), free, offline-capable.

*Process note: designed and built in an autonomous session; approach decisions below were made against research findings rather than interactive Q&A, and are documented with rationale so they can be revisited.*

## Approaches considered

1. **Python + MLX (chosen).** uv-managed Python app; MLX Whisper for ASR; pyobjc for the Quartz event tap, pasteboard, and NSWorkspace. *Pros:* hours-not-days to a working MVP on this machine's existing toolchain (uv, arm64), trivially hackable, engine pluggable. *Cons:* needs a terminal host (or later a LaunchAgent/menu-bar wrapper); Python runtime overhead is irrelevant here since MLX does the heavy lifting.
2. **Native Swift app.** VoiceInk's approach (whisper.cpp + FluidAudio). *Pros:* best UX and permission ergonomics. *Cons:* slowest to iterate; Xcode signing friction; duplicates a mature GPL project we could just fork.
3. **Rust binary.** local-dictation's approach (Parakeet + Qwen cleanup, 300–400 ms). *Pros:* fastest, single binary. *Cons:* highest build cost for an MVP; same integration surface anyway.

Chosen: **1**, with the Engine protocol and PLAN.md phases keeping paths 2/3 open.

## Architecture

```
fn press ──► HotkeyListener (CGEventTap, flagsChanged, listen-only)
                │ on_press: Recorder.start() + start cue
                │ on_release: Recorder.stop() ─► audio (16 kHz mono f32)
                ▼
          MLXWhisperEngine.transcribe(audio)          [on-device, Metal]
                ▼
          format_transcript(raw, config, ctx)         [rules, <1 ms]
                │  dictionary → fillers → spoken commands → whitespace
                │  → capitalisation → per-app tone (ctx = frontmost app)
                ▼
          llm_cleanup(text)                            [optional, Ollama]
                ▼
          paste_text(text)                             [clipboard swap + Cmd+V]
```

Threading: CFRunLoop owns the main thread; press/release callbacks spawn workers; a lock serialises transcribe→paste so rapid dictations queue rather than interleave.

## Components

- `hotkey.py` — CGEventTap; fn = keycode 63 via flagsChanged (unreachable by ordinary key handlers); modifier-only key support; tap re-enable on timeout; PermissionError with remediation text when Accessibility is missing.
- `recorder.py` — sounddevice InputStream, chunk list, no resampling.
- `engine.py` — Engine protocol; MLXWhisperEngine with silence warm-up (forces HF download + Metal compile at startup, not first dictation).
- `formatter.py` — deterministic pipeline + Whisper-hallucination blocklist; conservative filler list (no "like"/"so"); optional Ollama pass that fails open (returns input on any error).
- `inserter.py` — pasteboard save → set → synthetic Cmd+V (CGEventPost) → restore after 0.5 s.
- `context.py` — NSWorkspace frontmost app → per-bundle-id tone profile.
- `config.py` — TOML config + dictionary file, created with commented defaults on first run.
- `doctor.py` — AXIsProcessTrusted, mic guidance, globe-key `AppleFnUsageType` check.
- `cli.py` — `run` (default) / `doctor` / `transcribe FILE` (headless pipeline test).

## Error handling

- Missing Accessibility → tap creation fails → clear instructions, exit 1.
- Hotkey pressed before model ready → error cue, no-op.
- <0.3 s utterance → discarded (fn taps shouldn't paste hallucinations).
- Silence/noise → hallucination blocklist returns "" → nothing pasted.
- Ollama down/slow → 10 s timeout, rules-only text pasted.

## Testing

- Unit: formatter rules (10 cases — fillers, commands, dictionary, tone, hallucinations).
- Integration: `localflow transcribe` on `say`-generated audio through the real model (no mic/permissions needed) — verified on this machine with tiny and large-v3-turbo.
- Manual (needs user-granted permissions): hold-fn flow, paste into Slack/Notes, clipboard restore.
