from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from typing import Literal
from uuid import uuid4

from PIL import Image, ImageDraw


@dataclass(frozen=True)
class PreparedRecording:
    recording_id: str
    source: str
    manifest: str
    duration: float
    width: int
    height: int
    audio_status: Literal["no_audio", "not_processed"]
    visual_status: Literal["ready"]
    overview: Overview


@dataclass(frozen=True)
class Frame:
    requested_time: float
    actual_time: float
    path: str
    status: Literal["ready"] = "ready"


@dataclass(frozen=True)
class NoFrame:
    requested_time: float
    actual_time: None = None
    path: None = None
    status: Literal["no_frame"] = "no_frame"


@dataclass(frozen=True)
class Overview:
    path: str
    frames: list[Frame]
    sparse: bool = True


@dataclass(frozen=True)
class _Video:
    width: int
    height: int
    duration: Fraction
    time_base: Fraction
    pts: tuple[int, ...]


def _extract(source: str, index: int, path: Path) -> None:
    _run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-xerror",
            "-i",
            source,
            "-map",
            "0:v:0",
            "-vf",
            f"select=eq(n\\,{index})",
            "-frames:v",
            "1",
            "-fps_mode",
            "passthrough",
            str(path),
        ]
    )


def _run(command: list[str]) -> str:
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise ValueError(f"Required tool {command[0]} is missing; install FFmpeg") from exc
    except subprocess.CalledProcessError as exc:
        raise ValueError(f"{command[0]} failed: {exc.stderr.strip()}") from exc
    if result.stderr.strip():
        raise ValueError(f"{command[0]} reported decoding errors: {result.stderr.strip()}")
    return result.stdout


def _digest(source: Path) -> str:
    with source.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("Expected a JSON object")
    return dict(value)


def _objects(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError("Expected a JSON array")
    return [_object(item) for item in value]


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Expected text")
    return value


def _integer(value: object) -> int:
    if type(value) is not int:
        raise ValueError("Expected an integer")
    return value


def _parse_video(data: dict[str, object]) -> _Video:
    streams = _objects(data["streams"])
    if len(streams) != 1:
        raise ValueError("Expected one video stream")
    stream = streams[0]
    frames = _objects(data["frames"])
    if not frames:
        raise ValueError("No video frames found")
    pts = tuple(_integer(frame["pts"]) for frame in frames)
    time_base = Fraction(_text(stream["time_base"]))
    rate = Fraction(_text(stream["r_frame_rate"]))
    if time_base <= 0 or rate <= 0:
        raise ValueError("Unsupported video time base or frame rate")
    step = 1 / rate / time_base
    if pts[0] != 0 or stream.get("start_pts") != 0:
        raise ValueError("Unsupported timing: video must start at zero")
    if any(b - a != step for a, b in zip(pts, pts[1:], strict=False)):
        raise ValueError("Unsupported timing: expected continuous constant-frame-rate video")
    if any(_integer(frame["duration"]) != step for frame in frames):
        raise ValueError("Unsupported timing: variable frame duration")
    duration_ticks = _integer(stream["duration_ts"])
    if duration_ticks != pts[-1] + step:
        raise ValueError("Unsupported timing: stream duration disagrees with decoded frames")
    if "nb_frames" in stream and int(_text(stream["nb_frames"])) != len(frames):
        raise ValueError("Incomplete video: decoded frame count disagrees with stream")
    width, height = _integer(stream["width"]), _integer(stream["height"])
    if (
        width <= 0
        or height <= 0
        or any(frame.get("width") != width or frame.get("height") != height for frame in frames)
    ):
        raise ValueError("Unsupported display: invalid or changing dimensions")
    if stream.get("sample_aspect_ratio", "1:1") not in ("1:1", "N/A"):
        raise ValueError("Unsupported display: non-square pixels")
    if any(frame.get("sample_aspect_ratio", "1:1") not in ("1:1", "N/A") for frame in frames):
        raise ValueError("Unsupported display: changing pixel aspect ratio")
    if any(
        item.get("color_transfer") in ("smpte2084", "arib-std-b67") for item in (stream, *frames)
    ):
        raise ValueError("Unsupported display: HDR transfer function")
    if stream.get("field_order", "progressive") not in ("progressive", "unknown"):
        raise ValueError("Unsupported display: interlaced video")
    if any(frame.get("interlaced_frame") != 0 for frame in frames):
        raise ValueError("Unsupported display: interlaced or unknown frame structure")
    if any(
        side.get("side_data_type") == "Display Matrix"
        for item in (stream, *frames)
        for side in _objects(item.get("side_data_list", []))
    ):
        raise ValueError("Unsupported display: rotation or display matrix")
    if any(
        frame.get(f"crop_{edge}", 0) != 0
        for frame in frames
        for edge in ("top", "bottom", "left", "right")
    ):
        raise ValueError("Unsupported display: frame cropping metadata")
    return _Video(width, height, duration_ticks * time_base, time_base, pts)


class RecordingEvidence:
    """Own preparation and frame retrieval for a local evidence store."""

    def __init__(self, store: Path) -> None:
        self.store = store.expanduser().resolve()

    def prepare(self, source: Path) -> PreparedRecording:
        source = source.expanduser().resolve()
        recording_id = _digest(source)
        directory = self.store / recording_id / uuid4().hex
        directory.mkdir(parents=True)
        manifest = directory.parent / "manifest.json"
        metadata = _object(
            json.loads(
                _run(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-show_streams",
                        "-of",
                        "json",
                        str(source),
                    ]
                )
            )
        )
        streams = _objects(metadata["streams"])
        if len([s for s in streams if s.get("codec_type") == "video"]) != 1:
            raise ValueError("Unsupported media: expected exactly one video stream")
        audio_status: Literal["no_audio", "not_processed"] = (
            "not_processed" if any(s.get("codec_type") == "audio" for s in streams) else "no_audio"
        )
        data = _object(
            json.loads(
                _run(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-select_streams",
                        "v:0",
                        "-show_streams",
                        "-show_frames",
                        "-of",
                        "json",
                        str(source),
                    ]
                )
            )
        )
        data["source"] = str(source)
        try:
            video = _parse_video(data)
        except (KeyError, ZeroDivisionError) as exc:
            raise ValueError(f"Unsupported or incomplete video metadata: {exc}") from exc
        count = min(12, len(video.pts))
        indices = [round(i * (len(video.pts) - 1) / max(1, count - 1)) for i in range(count)]
        overview_frames = []
        cell_height = min(320, round(232 * video.height / video.width)) + 30
        sheet = Image.new("RGB", (960, 40 + ((count + 3) // 4) * cell_height), "#181818")
        draw = ImageDraw.Draw(sheet)
        draw.text((12, 12), "SPARSE OVERVIEW - may omit events", fill="white")
        for slot, index in enumerate(indices):
            path = directory / f"overview-{slot}.png"
            _extract(str(source), index, path)
            actual = float(video.pts[index] * video.time_base)
            overview_frames.append(Frame(actual, actual, str(path)))
            x, y = (slot % 4) * 240, 40 + (slot // 4) * cell_height
            with Image.open(path) as frame_image:
                frame_image.thumbnail((232, cell_height - 30))
                sheet.paste(frame_image, (x + (240 - frame_image.width) // 2, y))
            draw.text((x + 4, y + cell_height - 22), f"{actual:.6f} s", fill="white")
        overview_path = directory / "overview.png"
        sheet.save(overview_path)
        result = PreparedRecording(
            recording_id,
            str(source),
            str(manifest),
            float(video.duration),
            video.width,
            video.height,
            audio_status,
            "ready",
            Overview(str(overview_path), overview_frames),
        )
        data["schema_version"] = 1
        data["status"] = "complete"
        data["recording"] = asdict(result)
        temporary = directory / "manifest.json"
        temporary.write_text(json.dumps(data))
        if _digest(source) != recording_id:
            raise ValueError("Source changed during preparation; prepare it again")
        temporary.replace(manifest)
        return result

    def inspect(self, recording_id: str, at: float) -> Frame | NoFrame:
        if not math.isfinite(at) or at < 0:
            raise ValueError("Requested time must be finite and nonnegative (seconds)")
        if not re.fullmatch(r"[0-9a-f]{64}", recording_id):
            raise ValueError("Invalid recording reference: expected a SHA-256 identifier")
        directory = self.store / recording_id
        try:
            data = _object(json.loads((directory / "manifest.json").read_text()))
        except FileNotFoundError as exc:
            raise ValueError(f"Recording {recording_id} is not prepared in {self.store}") from exc
        try:
            if data.get("schema_version") != 1 or data.get("status") != "complete":
                raise ValueError("unsupported version or incomplete state")
            video = _parse_video(data)
            _text(data["source"])
        except (KeyError, ValueError, ZeroDivisionError) as exc:
            raise ValueError(f"Invalid recording manifest: {exc}") from exc
        source = Path(_text(data["source"]))
        if _digest(source) != recording_id:
            raise ValueError("Source changed since preparation; prepare it again")
        requested_time = Fraction(str(at))
        selected = next(
            (
                (index, pts)
                for index, pts in enumerate(video.pts)
                if pts * video.time_base >= requested_time
            ),
            None,
        )
        if selected is None:
            return NoFrame(at)
        index, pts = selected
        path = directory / f"{uuid4().hex}.png"
        _extract(_text(data["source"]), index, path)
        if _digest(source) != recording_id:
            raise ValueError("Source changed during inspection; prepare it again")
        return Frame(at, float(pts * video.time_base), str(path))
