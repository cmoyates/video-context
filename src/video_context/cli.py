import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .evidence import RecordingEvidence


class _Arguments(argparse.Namespace):
    # argparse populates these from the typed options below; command selects the applicable fields.
    command: str
    source: Path
    recording_id: str
    at: float
    store: Path


def main() -> None:
    parser = argparse.ArgumentParser(prog="video-context")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("source", type=Path)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("recording_id")
    inspect.add_argument("--at", type=float, required=True)
    for command in (prepare, inspect):
        command.add_argument(
            "--store", type=Path, default=Path.home() / "Library/Caches/video-context"
        )
    args = parser.parse_args(namespace=_Arguments())
    evidence = RecordingEvidence(args.store)
    try:
        if args.command == "prepare":
            result = evidence.prepare(args.source)
        else:
            result = evidence.inspect(args.recording_id, args.at)
    except (ValueError, OSError) as exc:
        print(f"video-context: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(asdict(result)))
