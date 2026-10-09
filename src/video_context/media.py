"""FFmpeg decoding, display transforms, and recording-time audio normalization."""

import json
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from uuid import uuid4

from ._json import integer as _integer
from ._json import object_ as _object
from ._json import objects as _objects
from ._json import text as _text
from .transcription import Normalization

type Crop = tuple[int, int, int, int]


@dataclass(frozen=True)
class _Video:
    width: int
    height: int
    duration: Fraction
    time_base: Fraction
    pts: tuple[int, ...]
    origin: Fraction


def _extract(
    source: str, indices: list[int], directory: Path, video: _Video, crop: Crop | None = None
) -> dict[int, Path]:
    indices = sorted(set(indices))
    if not indices:
        return {}
    prefix = uuid4().hex
    selection = "+".join(f"eq(n\\,{index})" for index in indices)
    filters = f"select={selection},scale={video.width}:{video.height},setsar=1"
    if crop is not None:
        x, y, width, height = crop
        filters += f",format=rgb24,crop={width}:{height}:{x}:{y}:exact=1"
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
            filters,
            "-frames:v",
            str(len(indices)),
            "-fps_mode",
            "passthrough",
            "-enc_time_base",
            "-1",
            str(directory / f"{prefix}-%03d.png"),
        ]
    )
    paths = {
        index: directory / f"{prefix}-{slot:03d}.png" for slot, index in enumerate(indices, start=1)
    }
    if not all(path.is_file() for path in paths.values()):
        raise ValueError("Decoder did not produce every requested frame")
    return paths


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
    origin = Fraction(_text(data.get("timeline_origin", "0")))
    duration = Fraction(_text(data.get("timeline_duration", stream["duration"])))
    if time_base <= 0 or duration <= 0:
        raise ValueError("Unsupported video time base or duration")
    if any(b <= a for a, b in zip(pts, pts[1:], strict=False)):
        raise ValueError("Unsupported timing: frame presentation times must increase")
    if pts[0] * time_base < origin or pts[-1] * time_base - origin >= duration:
        raise ValueError("Unsupported timing: frames outside recording timeline")
    if "nb_frames" in stream and int(_text(stream["nb_frames"])) != len(frames):
        raise ValueError("Incomplete video: decoded frame count disagrees with stream")
    width, height = _integer(stream["width"]), _integer(stream["height"])
    if (
        width <= 0
        or height <= 0
        or any(frame.get("width") != width or frame.get("height") != height for frame in frames)
    ):
        raise ValueError("Unsupported display: invalid or changing dimensions")
    sar = stream.get("sample_aspect_ratio", "1:1")
    if any(frame.get("sample_aspect_ratio", sar) != sar for frame in frames):
        raise ValueError("Unsupported display: changing pixel aspect ratio")
    ratio = Fraction(1) if sar == "N/A" else Fraction(_text(sar).replace(":", "/"))
    if ratio <= 0:
        raise ValueError("Unsupported display: invalid pixel aspect ratio")
    width = round(width * ratio)
    if any(
        item.get("color_transfer") in ("smpte2084", "arib-std-b67") for item in (stream, *frames)
    ):
        raise ValueError("Unsupported display: HDR transfer function")
    if stream.get("field_order", "progressive") not in ("progressive", "unknown"):
        raise ValueError("Unsupported display: interlaced video")
    if any(frame.get("interlaced_frame") != 0 for frame in frames):
        raise ValueError("Unsupported display: interlaced or unknown frame structure")
    matrices = [
        side
        for side in _objects(stream.get("side_data_list", []))
        if side.get("side_data_type") == "Display Matrix"
    ]
    if any(
        side.get("side_data_type") == "Display Matrix"
        for frame in frames
        for side in _objects(frame.get("side_data_list", []))
    ):
        raise ValueError("Unsupported display: changing display matrix")
    if matrices:
        rotation = _integer(matrices[0]["rotation"])
        if len(matrices) != 1 or rotation % 90:
            raise ValueError("Unsupported display: only quarter-turn rotations are supported")
        if rotation % 180:
            width, height = height, width
    if any(
        frame.get(f"crop_{edge}", 0) != 0
        for frame in frames
        for edge in ("top", "bottom", "left", "right")
    ):
        raise ValueError("Unsupported display: frame cropping metadata")
    return _Video(width, height, duration, time_base, pts, origin)


def _normalize_audio(
    source: Path, stream: dict[str, object], video: _Video, audio: Path
) -> Normalization:
    index = _integer(stream["index"])
    base = Fraction(_text(stream["time_base"]))
    rate = int(_text(stream["sample_rate"]))
    probe = _object(
        json.loads(
            _run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    str(index),
                    "-show_frames",
                    "-show_entries",
                    "frame=pts,nb_samples",
                    "-of",
                    "json",
                    str(source),
                ]
            )
        )
    )
    frames = _objects(probe["frames"])
    if not frames or base <= 0 or rate <= 0:
        raise ValueError("Unsupported audio timeline: missing samples or time base")
    previous_end = video.origin
    for frame in frames:
        start = _integer(frame["pts"]) * base
        count = _integer(frame["nb_samples"])
        if count <= 0 or start < previous_end - Fraction(1, rate):
            raise ValueError(
                "Unsupported audio timeline: overlapping or reversed sample timestamps"
            )
        previous_end = start + Fraction(count, rate)
    filters = (
        f"asetpts=PTS-({video.origin})/TB,aresample=16000:async=1:first_pts=0:"
        "min_comp=0.0000625:min_hard_comp=0.0000625,"
        f"apad=whole_dur={float(video.duration)},atrim=end={float(video.duration)}"
    )
    _run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-copyts",
            "-i",
            str(source),
            "-map",
            f"0:{index}",
            "-vn",
            "-af",
            filters,
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(audio),
        ]
    )
    return Normalization(
        index, _integer(stream["start_pts"]), str(base), str(video.origin), filters
    )
