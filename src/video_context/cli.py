import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .evidence import Crop, RecordingEvidence


class _Arguments(argparse.Namespace):
    # argparse populates these from the typed options below; command selects the applicable fields.
    command: str
    source: Path
    recording_id: str
    at: float | None
    start: float | None
    end: float | None
    source_frames: bool
    crop: Crop | None
    store: Path


def _crop(value: str) -> Crop:
    try:
        parts = tuple(int(p) for p in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("crop requires integer x,y,width,height") from exc
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("crop requires x,y,width,height")
    return parts[0], parts[1], parts[2], parts[3]


def main() -> None:
    parser = argparse.ArgumentParser(prog="video-context")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("source", type=Path)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("recording_id")
    position = inspect.add_mutually_exclusive_group(required=True)
    position.add_argument("--at", type=float)
    position.add_argument("--start", type=float)
    inspect.add_argument("--end", type=float)
    inspect.add_argument("--source-frames", action="store_true")
    inspect.add_argument("--crop", type=_crop)
    for command in (prepare, inspect):
        command.add_argument(
            "--store", type=Path, default=Path.home() / "Library/Caches/video-context"
        )
    args = parser.parse_args(namespace=_Arguments())
    evidence = RecordingEvidence(args.store)
    try:
        if args.command == "prepare":
            result = evidence.prepare(args.source)
        elif args.at is not None:
            if args.end is not None or args.source_frames:
                raise ValueError("--end and --source-frames require --start")
            result = evidence.inspect(args.recording_id, args.at, crop=args.crop)
        else:
            if args.start is None or args.end is None:
                raise ValueError("Interval requires --start and --end")
            result = evidence.inspect(
                args.recording_id,
                start=args.start,
                end=args.end,
                source_frames=args.source_frames,
                crop=args.crop,
            )
    except (ValueError, OSError) as exc:
        print(f"video-context: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(asdict(result)))
