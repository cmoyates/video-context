import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .evidence import Crop, PreparationFailed, RecordingEvidence
from .transcription import MODELS, MLXWhisper, model_path


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
    visual_only: bool
    model: str
    language: str | None
    query: str
    limit: int
    offset: int
    audio_stream: int | None


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
    prepare.add_argument("--visual-only", action="store_true")
    prepare.add_argument("--model", choices=MODELS, default="small")
    prepare.add_argument("--language", help="Language code; omitted means auto-detection")
    prepare.add_argument(
        "--audio-stream", type=int, help="Absolute source stream index from ffprobe"
    )
    search = commands.add_parser("search")
    search.add_argument("recording_id")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--offset", type=int, default=0)
    models = commands.add_parser("models").add_subparsers(dest="model_command", required=True)
    fetch = models.add_parser(
        "fetch", help="Explicitly download a pinned model; never uploads media"
    )
    fetch.add_argument("model", choices=MODELS)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("recording_id")
    position = inspect.add_mutually_exclusive_group(required=True)
    position.add_argument("--at", type=float)
    position.add_argument("--start", type=float)
    inspect.add_argument("--end", type=float)
    inspect.add_argument("--source-frames", action="store_true")
    inspect.add_argument("--crop", type=_crop)
    for command in (prepare, inspect, search):
        command.add_argument(
            "--store", type=Path, default=Path.home() / "Library/Caches/video-context"
        )
    args = parser.parse_args(namespace=_Arguments())
    try:
        if args.command == "models":
            path = model_path(args.model, download=True)
            print(
                json.dumps(
                    {"model": args.model, "revision": MODELS[args.model][1], "path": str(path)}
                )
            )
            return
        evidence = RecordingEvidence(args.store)
        if args.command == "prepare":
            evidence = RecordingEvidence(
                args.store, transcriber=MLXWhisper(args.model, language=args.language)
            )
            result = evidence.prepare(
                args.source, visual_only=args.visual_only, audio_stream=args.audio_stream
            )
        elif args.command == "search":
            result = evidence.search(
                args.recording_id, args.query, limit=args.limit, offset=args.offset
            )
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
    except PreparationFailed as exc:
        print(json.dumps(asdict(exc.recording)))
        print(f"video-context: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except (ValueError, OSError) as exc:
        print(f"video-context: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(asdict(result)))
