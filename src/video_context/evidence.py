from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from dataclasses import asdict, dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Literal, overload
from uuid import uuid4

from PIL import Image, ImageDraw

from ._json import integer as _integer
from ._json import object_ as _object
from ._json import objects as _objects
from ._json import text as _text
from .transcription import (
    MLXWhisper,
    Normalization,
    SearchResult,
    Segment,
    Transcriber,
    Transcript,
    recognize,
    segments,
)

type Crop = tuple[int, int, int, int]


@dataclass(frozen=True)
class PreparedRecording:
    recording_id: str
    source: str
    manifest: str
    duration: float
    width: int
    height: int
    audio_status: Literal["no_audio", "skipped", "ready", "empty", "failed"]
    visual_status: Literal["ready"]
    overview: Overview
    transcript: Transcript | None = None
    audio_error: str | None = None


class PreparationFailed(ValueError):
    def __init__(self, recording: PreparedRecording) -> None:
        self.recording = recording
        super().__init__(
            f"Transcription failed; visual evidence available: {recording.audio_error}"
        )


@dataclass(frozen=True)
class Frame:
    requested_time: float
    actual_time: float
    path: str
    status: Literal["ready"] = "ready"
    segments: list[Segment] = field(default_factory=list)


@dataclass(frozen=True)
class NoFrame:
    requested_time: float
    actual_time: None = None
    path: None = None
    status: Literal["no_frame"] = "no_frame"
    segments: list[Segment] = field(default_factory=list)


@dataclass(frozen=True)
class Overview:
    path: str
    frames: list[Frame]
    sparse: bool = True


@dataclass(frozen=True)
class Inspection:
    start: float
    end: float
    frames: list[Frame]
    source_frames: bool
    sampling_interval: float | None
    width: int
    height: int
    segments: list[Segment] = field(default_factory=list)


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


def _digest(source: Path) -> str:
    with source.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


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


class RecordingEvidence:
    """Own preparation and frame retrieval for a local evidence store."""

    def __init__(self, store: Path, *, transcriber: Transcriber | None = None) -> None:
        self.store = store.expanduser().resolve()
        self.transcriber = transcriber if transcriber is not None else MLXWhisper()

    def prepare(
        self, source: Path, *, visual_only: bool = False, audio_stream: int | None = None
    ) -> PreparedRecording:
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
                        "-show_format",
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
        audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
        selected_audio = next(
            (s for s in audio_streams if audio_stream is None or s.get("index") == audio_stream),
            None,
        )
        if audio_stream is not None and selected_audio is None:
            raise ValueError(
                "Selected audio stream is unavailable; use an absolute audio stream index"
            )
        audio_status: Literal["no_audio", "skipped", "ready", "empty", "failed"] = (
            "skipped" if any(s.get("codec_type") == "audio" for s in streams) else "no_audio"
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
            timings = [
                (
                    _integer(s["start_pts"]) * Fraction(_text(s["time_base"])),
                    _integer(s["duration_ts"]) * Fraction(_text(s["time_base"])),
                )
                for s in streams
                if s.get("codec_type") in ("audio", "video")
            ]
            origin = min(start for start, _ in timings)
            end = max(start + duration for start, duration in timings)
        except (KeyError, ZeroDivisionError) as exc:
            raise ValueError("Unsupported media: stream timeline is incomplete") from exc
        data["timeline_origin"] = str(origin)
        data["timeline_duration"] = str(end - origin)
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
        paths = _extract(str(source), indices, directory, video)
        for slot, index in enumerate(indices):
            path = paths[index]
            actual = float(video.pts[index] * video.time_base - video.origin)
            overview_frames.append(Frame(actual, actual, str(path)))
            x, y = (slot % 4) * 240, 40 + (slot // 4) * cell_height
            with Image.open(path) as frame_image:
                frame_image.thumbnail((232, cell_height - 30))
                sheet.paste(frame_image, (x + (240 - frame_image.width) // 2, y))
            draw.text((x + 4, y + cell_height - 22), f"{actual:.6f} s", fill="white")
        overview_path = directory / "overview.png"
        sheet.save(overview_path)
        transcript = None
        failure: Exception | None = None
        if audio_status != "no_audio" and not visual_only:
            assert selected_audio is not None
            audio = directory / "audio.wav"
            try:
                normalization = _normalize_audio(source, selected_audio, video, audio)
                transcript = recognize(
                    self.transcriber, audio, float(video.duration), normalization
                )
                audio_status = transcript.status
            except (OSError, ValueError, RuntimeError, ImportError) as exc:
                # External recognition boundary: publish usable visuals, then re-raise with context.
                failure = exc
                audio_status = "failed"
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
            transcript,
            str(failure) if failure is not None else None,
        )
        data["schema_version"] = 1
        data["status"] = "complete"
        data["recording"] = asdict(result)
        data["transcript"] = asdict(transcript) if transcript is not None else None
        temporary = directory / "manifest.json"
        temporary.write_text(json.dumps(data))
        if _digest(source) != recording_id:
            raise ValueError("Source changed during preparation; prepare it again")
        temporary.replace(manifest)
        if failure is not None:
            raise PreparationFailed(result) from failure
        return result

    def _load(self, recording_id: str) -> tuple[dict[str, object], _Video]:
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
        return data, video

    def search(
        self, recording_id: str, query: str, *, limit: int = 20, offset: int = 0
    ) -> SearchResult:
        if not query or not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Search requires nonempty text, limit 1–100, and nonnegative offset")
        data, video = self._load(recording_id)
        transcript = data.get("transcript")
        if transcript is None:
            raise ValueError("Transcript unavailable for this recording")
        matches = [
            s
            for s in segments(_object(transcript)["segments"], float(video.duration))
            if query.casefold() in s.text.casefold()
        ]
        return SearchResult(
            recording_id,
            query,
            matches[offset : offset + limit],
            offset + limit if offset + limit < len(matches) else None,
        )

    @overload
    def inspect(
        self, recording_id: str, at: float, *, crop: Crop | None = None
    ) -> Frame | NoFrame: ...

    @overload
    def inspect(
        self,
        recording_id: str,
        *,
        start: float,
        end: float,
        source_frames: bool = False,
        crop: Crop | None = None,
    ) -> Inspection: ...

    def inspect(
        self,
        recording_id: str,
        at: float | None = None,
        *,
        start: float | None = None,
        end: float | None = None,
        source_frames: bool = False,
        crop: Crop | None = None,
    ) -> Frame | NoFrame | Inspection:
        if at is not None and (not math.isfinite(at) or at < 0):
            raise ValueError("Requested time must be finite and nonnegative (seconds)")
        data, video = self._load(recording_id)
        transcript = data.get("transcript")
        speech = (
            []
            if transcript is None
            else segments(_object(transcript)["segments"], float(video.duration))
        )
        if crop is not None:
            x, y, width, height = crop
            if (
                any(type(v) is not int for v in crop)
                or x < 0
                or y < 0
                or width <= 0
                or height <= 0
                or x + width > video.width
                or y + height > video.height
            ):
                raise ValueError("Invalid crop: use x,y,width,height within displayed dimensions")
        directory = self.store / recording_id
        source = Path(_text(data["source"]))
        if at is None:
            if start is None or end is None or not all(math.isfinite(t) for t in (start, end)):
                raise ValueError("Interval requires finite start and end")
            if start < 0 or end <= start or Fraction(str(end)) > video.duration:
                raise ValueError("Interval must satisfy 0 <= start < end <= duration")
            first, stop = Fraction(str(start)), Fraction(str(end))
            available = [
                (i, p * video.time_base - video.origin)
                for i, p in enumerate(video.pts)
                if first <= p * video.time_base - video.origin < stop
            ]
            sampling = None
            if source_frames:
                if len(available) > 120:
                    raise ValueError("More than 120 source frames; request a narrower interval")
                selected_frames = [(i, t, t) for i, t in available]
            else:
                step = max(Fraction(1, 2), (stop - first) / 24)
                sampling = float(step)
                selected_frames = []
                requested = first
                while requested < stop:
                    match = next(((i, t) for i, t in available if t >= requested), None)
                    if match is not None:
                        selected_frames.append((match[0], requested, match[1]))
                    requested += step
            paths = _extract(
                str(source), [i for i, _, _ in selected_frames], directory, video, crop
            )
            frames = []
            for index, requested, actual in selected_frames:
                frames.append(Frame(float(requested), float(actual), str(paths[index])))
            if _digest(source) != recording_id:
                raise ValueError("Source changed during inspection; prepare it again")
            return Inspection(
                start,
                end,
                frames,
                source_frames,
                sampling,
                video.width,
                video.height,
                [s for s in speech if s.start < end and s.end > start],
            )
        requested_time = Fraction(str(at))
        selected = next(
            (
                (index, pts)
                for index, pts in enumerate(video.pts)
                if pts * video.time_base - video.origin >= requested_time
            ),
            None,
        )
        if selected is None:
            return NoFrame(at, segments=[s for s in speech if s.start <= at < s.end])
        index, pts = selected
        path = _extract(str(source), [index], directory, video, crop)[index]
        if _digest(source) != recording_id:
            raise ValueError("Source changed during inspection; prepare it again")
        return Frame(
            at,
            float(pts * video.time_base - video.origin),
            str(path),
            segments=[s for s in speech if s.start <= at < s.end],
        )
