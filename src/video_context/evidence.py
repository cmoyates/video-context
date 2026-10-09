from __future__ import annotations

import fcntl
import hashlib
import json
import math
import re
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from fractions import Fraction
from pathlib import Path
from typing import Literal, overload
from uuid import uuid4

from PIL import Image, ImageDraw

from ._json import integer as _integer
from ._json import number as _number
from ._json import object_ as _object
from ._json import objects as _objects
from ._json import text as _text
from .media import Crop, _extract, _normalize_audio, _parse_video, _run, _Video
from .transcription import (
    MLXWhisper,
    SearchResult,
    Segment,
    SourceStatus,
    Transcriber,
    Transcript,
    read_transcript,
    recognize,
    segments,
)


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
    cache_status: Literal["prepared", "reused", "rebuilt"] = "prepared"
    generation: str = ""
    published: bool = True
    source_status: SourceStatus = "available"
    generation_manifest: str = ""


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
    source_status: SourceStatus = "available"
    recording_id: str = ""
    generation: str = ""
    frame_id: str = ""
    crop: Crop | None = None


@dataclass(frozen=True)
class NoFrame:
    requested_time: float
    actual_time: None = None
    path: None = None
    status: Literal["no_frame"] = "no_frame"
    segments: list[Segment] = field(default_factory=list)
    source_status: SourceStatus = "available"
    recording_id: str = ""
    generation: str = ""
    frame_id: None = None


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
    source_status: SourceStatus = "available"
    recording_id: str = ""
    generation: str = ""
    crop: Crop | None = None


def _digest(source: Path) -> str:
    with source.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _source_status(source: Path, recording_id: str) -> SourceStatus:
    try:
        digest = _digest(source)
    except OSError:
        return "unavailable"
    return "available" if digest == recording_id else "changed"


def _prepared(data: dict[str, object], video: _Video) -> PreparedRecording:
    raw = _object(data["recording"])
    overview = _object(raw["overview"])
    frames = [
        Frame(
            _number(f["requested_time"]),
            _number(f["actual_time"]),
            _text(f["path"]),
            recording_id=_text(f["recording_id"]),
            generation=_text(f["generation"]),
            frame_id=_text(f["frame_id"]),
        )
        for f in _objects(overview["frames"])
    ]
    transcript = (
        None
        if data.get("transcript") is None
        else read_transcript(data["transcript"], float(video.duration))
    )
    status: Literal["no_audio", "skipped", "ready", "empty", "failed"]
    if raw["audio_status"] == "no_audio":
        status = "no_audio"
    elif raw["audio_status"] == "skipped":
        status = "skipped"
    elif raw["audio_status"] == "ready":
        status = "ready"
    elif raw["audio_status"] == "empty":
        status = "empty"
    elif raw["audio_status"] == "failed":
        status = "failed"
    else:
        raise ValueError("Invalid audio availability")
    if status in ("ready", "empty") and (transcript is None or transcript.status != status):
        raise ValueError("Transcript is missing or incomplete")
    return PreparedRecording(
        _text(raw["recording_id"]),
        _text(data["source"]),
        _text(raw["manifest"]),
        float(video.duration),
        video.width,
        video.height,
        status,
        "ready",
        Overview(_text(overview["path"]), frames),
        transcript,
        None if raw.get("audio_error") is None else _text(raw["audio_error"]),
        generation=_text(raw.get("generation", "")),
        generation_manifest=_text(raw.get("generation_manifest", "")),
    )


def _publish(
    data: dict[str, object], result: PreparedRecording, directory: Path, *, publish: bool = True
) -> PreparedRecording:
    directory.mkdir(parents=True, exist_ok=True)
    result = replace(
        result,
        generation=directory.name,
        published=publish,
        manifest=result.manifest if publish else str(directory / "manifest.json"),
        generation_manifest=str(directory / "manifest.json"),
        overview=replace(
            result.overview,
            frames=[
                replace(f, recording_id=result.recording_id, generation=directory.name)
                for f in result.overview.frames
            ],
        ),
    )
    data["recording"] = asdict(result)
    data["artifact_hashes"] = {path: _digest(Path(path)) for path in _artifacts(result)}
    contents = json.dumps(data)
    (directory / "manifest.json").write_text(contents)
    (directory / "manifest.sha256").write_text(hashlib.sha256(contents.encode()).hexdigest())
    if publish:
        temporary = directory / "publish.json"
        temporary.write_text(contents)
        temporary.replace(Path(result.manifest))
    return result


def _artifacts(recording: PreparedRecording) -> list[str]:
    paths = [recording.overview.path, *(frame.path for frame in recording.overview.frames)]
    if recording.transcript is not None:
        paths.extend(
            [
                recording.transcript.path,
                recording.transcript.audio_path,
                recording.transcript.raw_path,
            ]
        )
    return paths


def _require_artifacts(data: dict[str, object], paths: list[str]) -> None:
    try:
        hashes = _object(data["artifact_hashes"])
        for path in paths:
            if _digest(Path(path)) != _text(hashes.get(path)):
                raise ValueError(f"Cached artifact is corrupt: {path}; prepare again to rebuild")
    except (OSError, KeyError) as exc:
        raise ValueError(
            f"Cached artifact is unavailable; prepare again to rebuild: {exc}"
        ) from exc


def _valid_artifacts(data: dict[str, object], paths: list[str]) -> bool:
    try:
        _require_artifacts(data, paths)
    except ValueError:
        return False
    return True


class RecordingEvidence:
    """Own preparation and frame retrieval for a local evidence store."""

    def __init__(self, store: Path, *, transcriber: Transcriber | None = None) -> None:
        self.store = store.expanduser().resolve()
        self.transcriber = transcriber if transcriber is not None else MLXWhisper()

    def prepare(
        self,
        source: Path,
        *,
        visual_only: bool = False,
        audio_stream: int | None = None,
        overview_count: int = 12,
        rebuild: bool = False,
    ) -> PreparedRecording:
        source = source.expanduser().resolve()
        recording_id = _digest(source)
        with self._writer(recording_id):
            if _digest(source) != recording_id:
                raise ValueError("Source changed while waiting to prepare; retry with stable media")
            return self._prepare(
                source,
                recording_id,
                visual_only=visual_only,
                audio_stream=audio_stream,
                overview_count=overview_count,
                rebuild=rebuild,
            )

    @contextmanager
    def _writer(self, recording_id: str) -> Generator[None, None, None]:
        directory = self.store / recording_id
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _prepare(
        self,
        source: Path,
        recording_id: str,
        *,
        visual_only: bool,
        audio_stream: int | None,
        overview_count: int,
        rebuild: bool,
    ) -> PreparedRecording:
        if type(overview_count) is not int or not 1 <= overview_count <= 12:
            raise ValueError("Overview count must be an integer from 1 to 12")
        manifest = self.store / recording_id / "manifest.json"
        previous = None
        reusable_transcript = None
        if manifest.is_file() and rebuild:
            try:
                data, video = self._load(recording_id)
                previous = _prepared(data, video)
            except (ValueError, OSError):
                # Explicit rebuilding does not depend on an unreadable older schema/artifact index.
                previous = None
        if manifest.is_file() and not rebuild:
            data, video = self._load(recording_id)
            previous = _prepared(data, video)
            audio_indices = [
                _integer(s["index"])
                for s in _objects(data["source_streams"])
                if s.get("codec_type") == "audio"
            ]
            if audio_stream is not None and audio_stream not in audio_indices:
                raise ValueError("Selected audio stream is unavailable")
            selected_index = (
                audio_stream if audio_stream is not None else next(iter(audio_indices), None)
            )
            transcript = previous.transcript
            compatible = audio_stream is None and (
                previous.audio_status == "no_audio"
                or (visual_only and previous.audio_status == "skipped")
            )
            if transcript is not None:
                compatible = (
                    visual_only or transcript.configuration == self.transcriber.configuration
                ) and selected_index == transcript.normalization.source_stream
                if compatible and _valid_artifacts(
                    data, [transcript.path, transcript.audio_path, transcript.raw_path]
                ):
                    reusable_transcript = transcript
            if reusable_transcript is None and selected_index is not None:
                reusable_transcript = self._previous_transcript(
                    recording_id, selected_index, visual_only
                )
            if (
                ((compatible and transcript is None) or reusable_transcript is not None)
                and len(previous.overview.frames) == min(overview_count, len(video.pts))
                and _valid_artifacts(
                    data, [previous.overview.path, *(f.path for f in previous.overview.frames)]
                )
            ):
                result = replace(
                    previous,
                    source=str(source),
                    cache_status="reused",
                    transcript=reusable_transcript,
                    audio_status=reusable_transcript.status
                    if reusable_transcript is not None
                    else previous.audio_status,
                    audio_error=None,
                )
                if _digest(source) != recording_id:
                    raise ValueError("Source changed during preparation; prepare it again")
                if previous.source != str(source) or previous.transcript != reusable_transcript:
                    data["source"] = str(source)
                    data["transcript"] = (
                        asdict(reusable_transcript) if reusable_transcript is not None else None
                    )
                    return _publish(data, result, manifest.parent / uuid4().hex)
                return result
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
        data["source_streams"] = streams
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
        count = min(overview_count, len(video.pts))
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
            overview_frames.append(Frame(actual, actual, str(path), frame_id=f"f{index:06d}"))
            x, y = (slot % 4) * 240, 40 + (slot // 4) * cell_height
            with Image.open(path) as frame_image:
                frame_image.thumbnail((232, cell_height - 30))
                sheet.paste(frame_image, (x + (240 - frame_image.width) // 2, y))
            draw.text((x + 4, y + cell_height - 22), f"{actual:.6f} s", fill="white")
        overview_path = directory / "overview.png"
        sheet.save(overview_path)
        transcript = reusable_transcript
        failure: Exception | None = None
        if transcript is not None:
            audio_status = transcript.status
        elif audio_status != "no_audio" and not visual_only:
            assert selected_audio is not None
            audio = directory / "audio.wav"
            try:
                normalization = _normalize_audio(source, selected_audio, video, audio)
                transcript = recognize(
                    self.transcriber, audio, float(video.duration), normalization
                )
                audio_status = transcript.status
            except (
                OSError,
                ValueError,
                RuntimeError,
                ImportError,
                KeyError,
                ZeroDivisionError,
            ) as exc:
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
            cache_status="rebuilt" if manifest.is_file() else "prepared",
        )
        data["schema_version"] = 2
        data["status"] = "complete"
        data["recording"] = asdict(result)
        data["transcript"] = asdict(transcript) if transcript is not None else None
        if _digest(source) != recording_id:
            raise ValueError("Source changed during preparation; prepare it again")
        result = _publish(data, result, directory, publish=failure is None or previous is None)
        if failure is not None:
            raise PreparationFailed(result) from failure
        return result

    def _previous_transcript(
        self, recording_id: str, audio_stream: int, visual_only: bool
    ) -> Transcript | None:
        for path in sorted((self.store / recording_id).glob("*/manifest.json")):
            try:
                contents = path.read_bytes()
                if hashlib.sha256(contents).hexdigest() != path.with_suffix(".sha256").read_text():
                    continue
                data = _object(json.loads(contents))
                if data.get("schema_version") != 2 or data.get("status") != "complete":
                    continue
                recording = _prepared(data, _parse_video(data))
                transcript = recording.transcript
                if (
                    recording.recording_id == recording_id
                    and recording.generation == path.parent.name
                    and transcript is not None
                    and transcript.normalization.source_stream == audio_stream
                    and (visual_only or transcript.configuration == self.transcriber.configuration)
                    and _valid_artifacts(
                        data, [transcript.path, transcript.audio_path, transcript.raw_path]
                    )
                ):
                    return transcript
            except (OSError, ValueError, KeyError, ZeroDivisionError):
                # An incomplete/damaged historical generation is never a cache hit.
                continue
        return None

    def _load(self, recording_id: str) -> tuple[dict[str, object], _Video]:
        if not re.fullmatch(r"[0-9a-f]{64}", recording_id):
            raise ValueError("Invalid recording reference: expected a SHA-256 identifier")
        directory = self.store / recording_id
        try:
            contents = (directory / "manifest.json").read_text()
            data = _object(json.loads(contents))
        except FileNotFoundError as exc:
            raise ValueError(f"Recording {recording_id} is not prepared in {self.store}") from exc
        try:
            if data.get("schema_version") != 2 or data.get("status") != "complete":
                raise ValueError("unsupported version or incomplete state")
            video = _parse_video(data)
            _text(data["source"])
            recording = _prepared(data, video)
            if recording.recording_id != recording_id or not re.fullmatch(
                r"[0-9a-f]{32}", recording.generation
            ):
                raise ValueError("recording reference or generation is invalid")
            if (directory / recording.generation / "manifest.json").read_text() != contents:
                raise ValueError("published manifest differs from its immutable generation")
            if (
                hashlib.sha256(contents.encode()).hexdigest()
                != (directory / recording.generation / "manifest.sha256").read_text()
            ):
                raise ValueError("generation checksum does not match")
        except (KeyError, ValueError, ZeroDivisionError, OSError) as exc:
            raise ValueError(f"Invalid recording manifest: {exc}; prepare with --rebuild") from exc
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
        stored = read_transcript(transcript, float(video.duration))
        _require_artifacts(data, [stored.path, stored.audio_path, stored.raw_path])
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
            _source_status(Path(_text(data["source"])), recording_id),
            _text(_object(data["recording"])["generation"]),
        )

    def _frames(
        self,
        recording_id: str,
        data: dict[str, object],
        video: _Video,
        indices: list[int],
        crop: Crop | None,
        *,
        locked: bool = False,
    ) -> dict[int, Path]:
        directory = self.store / recording_id / "frames"
        directory.mkdir(exist_ok=True)
        paths = {}
        overview = _prepared(data, video).overview
        crop_key = "full" if crop is None else "-".join(str(v) for v in crop)
        for index in set(indices):
            entry = directory / f"v1-{index}-{crop_key}.json"
            if entry.is_file():
                try:
                    cached = _object(json.loads(entry.read_text()))
                    path = Path(_text(cached["path"]))
                    if _digest(path) == _text(cached["sha256"]):
                        paths[index] = path
                        continue
                except (OSError, ValueError, KeyError):
                    # A damaged derived frame can be rebuilt from the verified original below.
                    pass
            if crop is None:
                actual = float(video.pts[index] * video.time_base - video.origin)
                frame = next((f for f in overview.frames if f.actual_time == actual), None)
                if frame is not None and _valid_artifacts(data, [frame.path]):
                    paths[index] = Path(frame.path)
        missing = sorted(set(indices) - paths.keys())
        if missing:
            if not locked:
                with self._writer(recording_id):
                    return self._frames(recording_id, data, video, indices, crop, locked=True)
            source = Path(_text(data["source"]))
            status = _source_status(source, recording_id)
            if status != "available":
                raise ValueError(
                    f"Source {status}; requested frame is not cached. "
                    "Re-associate identical bytes with prepare."
                )
            output = directory / uuid4().hex
            output.mkdir()
            extracted = _extract(str(source), missing, output, video, crop)
            if _digest(source) != recording_id:
                raise ValueError("Source changed during inspection; prepare it again")
            for index, path in extracted.items():
                entry = output / f"{index}.json"
                entry.write_text(json.dumps({"path": str(path), "sha256": _digest(path)}))
                entry.replace(directory / f"v1-{index}-{crop_key}.json")
            paths.update(extracted)
        return paths

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
        generation = _text(_object(data["recording"])["generation"])
        transcript = data.get("transcript")
        if transcript is not None:
            stored = read_transcript(transcript, float(video.duration))
            _require_artifacts(data, [stored.path, stored.audio_path, stored.raw_path])
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
        source = Path(_text(data["source"]))
        source_status = _source_status(source, recording_id)
        if at is None:
            if start is None or end is None or not all(math.isfinite(t) for t in (start, end)):
                raise ValueError("Interval requires finite start and end")
            if start < 0 or end <= start or end > float(video.duration):
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
            paths = self._frames(
                recording_id, data, video, [i for i, _, _ in selected_frames], crop
            )
            frames = []
            for index, requested, actual in selected_frames:
                frames.append(
                    Frame(
                        float(requested),
                        float(actual),
                        str(paths[index]),
                        source_status=source_status,
                        recording_id=recording_id,
                        generation=generation,
                        frame_id=f"f{index:06d}",
                        crop=crop,
                    )
                )
            return Inspection(
                start,
                end,
                frames,
                source_frames,
                sampling,
                video.width,
                video.height,
                [s for s in speech if s.start < end and s.end > start],
                source_status,
                recording_id,
                generation,
                crop,
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
            return NoFrame(
                at,
                segments=[s for s in speech if s.start <= at < s.end],
                source_status=source_status,
                recording_id=recording_id,
                generation=generation,
            )
        index, pts = selected
        path = self._frames(recording_id, data, video, [index], crop)[index]
        return Frame(
            at,
            float(pts * video.time_base - video.origin),
            str(path),
            segments=[s for s in speech if s.start <= at < s.end],
            source_status=source_status,
            recording_id=recording_id,
            generation=generation,
            frame_id=f"f{index:06d}",
            crop=crop,
        )
