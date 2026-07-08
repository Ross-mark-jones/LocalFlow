"""CLI entry point.

  localflow                     run the dictation app (default)
  localflow doctor              check permissions and keyboard settings
  localflow transcribe FILE     transcribe an audio file (pipeline test, no mic needed)
"""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(prog="localflow", description="Local Wispr Flow clone for macOS.")
    parser.add_argument("--model", help="Override ASR model repo (e.g. mlx-community/whisper-base.en)")
    parser.add_argument("--key", help="Override hold-to-talk key (fn, right_cmd, right_alt, ...)")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("run", help="Run the dictation app (default)")
    subparsers.add_parser("doctor", help="Check permissions and settings")
    transcribe = subparsers.add_parser("transcribe", help="Transcribe an audio file and print the result")
    transcribe.add_argument("file")
    transcribe.add_argument("--raw", action="store_true", help="Skip the formatting pipeline")
    args = parser.parse_args()

    from .config import load_config

    config = load_config()
    if args.model:
        config.model = args.model
    if args.key:
        config.hotkey = args.key

    if args.command == "doctor":
        from .doctor import run_doctor

        run_doctor(config.hotkey)
        return

    if args.command == "transcribe":
        from .engine import MLXWhisperEngine
        from .formatter import format_transcript

        engine = MLXWhisperEngine(config.model, config.language)
        raw = engine.transcribe(args.file)
        print(raw if args.raw else format_transcript(raw, config))
        return

    from .app import LocalFlowApp

    LocalFlowApp(config).run()


if __name__ == "__main__":
    main()
