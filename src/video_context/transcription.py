"""Local speech recognition boundary and validated recording-time evidence."""

import json
import sys
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path
from typing import Literal, Protocol

from ._json import boolean, integer, number, object_, objects, text

MODELS = {
    "small": ("mlx-community/whisper-small-mlx", "45f3915923c7a79a5a5b5a7d909d39aeb0e5630e"),
    "turbo": ("mlx-community/whisper-large-v3-turbo", "a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb"),
}

type SourceStatus = Literal["available", "unavailable", "changed"]


def model_path(name: str, *, download: bool = False) -> Path:
    if name not in MODELS:
        raise ValueError("Model must be small or turbo")
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise ValueError(
            "Install video-context[asr] on Apple Silicon for local transcription"
        ) from exc
    repo, revision = MODELS[name]
    try:
        with redirect_stdout(sys.stderr):
            path = Path(
                snapshot_download(
                    repo_id=repo,
                    revision=revision,
                    local_files_only=not download,
                    allow_patterns=["config.json", "weights.npz", "weights.safetensors"],
                )
            )
    except FileNotFoundError as exc:
        raise ValueError(f"Local model unavailable; run video-context models fetch {name}") from exc
    if not (path / "config.json").is_file() or not any(
        (path / f).is_file() for f in ("weights.npz", "weights.safetensors")
    ):
        raise ValueError(f"Local model is incomplete; run video-context models fetch {name}")
    return path.resolve()


@dataclass(frozen=True)
class TranscriptionConfig:
    backend: str
    backend_version: str
    model: str
    revision: str
    language: str | None
    word_timestamps: bool
    temperature: float = 0.0
    condition_on_previous_text: bool = False
    normalization_version: int = 1
    runtime_version: str = ""
    fp16: bool = True
    task: str = "transcribe"


class Transcriber(Protocol):
    @property
    def configuration(self) -> TranscriptionConfig: ...

    def transcribe(self, audio: Path) -> object: ...


class MLXWhisper:
    def __init__(
        self, model: str = "small", *, language: str | None = None, word_timestamps: bool = True
    ) -> None:
        if model not in MODELS:
            raise ValueError("Model must be small or turbo")
        self.model = model
        self.language = language
        self.word_timestamps = word_timestamps

    @property
    def configuration(self) -> TranscriptionConfig:
        repo, revision = MODELS[self.model]
        return TranscriptionConfig(
            "mlx-whisper",
            version("mlx-whisper"),
            repo,
            revision,
            self.language,
            self.word_timestamps,
            runtime_version=version("mlx"),
        )

    def transcribe(self, audio: Path) -> object:
        path = model_path(self.model)
        configuration = self.configuration
        import mlx_whisper

        with redirect_stdout(sys.stderr):
            result = object_(
                mlx_whisper.transcribe(
                    str(audio),
                    path_or_hf_repo=str(path),
                    language=configuration.language,
                    temperature=configuration.temperature,
                    condition_on_previous_text=configuration.condition_on_previous_text,
                    word_timestamps=configuration.word_timestamps,
                    verbose=None,
                    task=configuration.task,
                    fp16=configuration.fp16,
                )
            )
        result["local_model_path"] = str(path)
        return result


@dataclass(frozen=True)
class Word:
    start: float
    end: float
    word: str
    estimated: bool = True


@dataclass(frozen=True)
class Segment:
    segment_id: str
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)


@dataclass(frozen=True)
class Normalization:
    source_stream: int
    source_start_pts: int
    source_time_base: str
    recording_origin: str
    filter_graph: str
    sample_rate: int = 16000
    channels: int = 1
    version: int = 1


@dataclass(frozen=True)
class Transcript:
    status: Literal["ready", "empty"]
    language: str
    path: str
    segments: list[Segment]
    configuration: TranscriptionConfig
    audio_path: str
    raw_path: str
    normalization: Normalization


@dataclass(frozen=True)
class SearchResult:
    recording_id: str
    query: str
    matches: list[Segment]
    next_offset: int | None
    source_status: SourceStatus = "available"
    generation: str = ""


def segments(value: object, duration: float) -> list[Segment]:
    result = []
    for item in objects(value):
        wording = text(item["text"])
        if not wording.strip():
            continue
        start, end = number(item["start"]), number(item["end"])
        if not 0 <= start < end <= duration or (result and start < result[-1].start):
            raise ValueError("Invalid transcript interval or segment ordering")
        words = []
        for word in objects(item.get("words", [])):
            word_start, word_end = number(word["start"]), number(word["end"])
            if not start <= word_start <= word_end <= end or (
                words and word_start < words[-1].start
            ):
                raise ValueError("Invalid transcript word interval")
            words.append(Word(word_start, word_end, text(word["word"])))
        result.append(Segment(f"s{len(result):05d}", start, end, wording, words))
    return result


def recognize(
    transcriber: Transcriber, audio: Path, duration: float, normalization: Normalization
) -> Transcript:
    raw = object_(transcriber.transcribe(audio))
    raw_path = audio.parent / "recognition.json"
    raw_path.write_text(json.dumps(raw, ensure_ascii=False))
    try:
        recognized = segments(raw["segments"], duration)
        language = text(raw["language"])
    except KeyError as exc:
        raise ValueError("Incomplete transcript result") from exc
    path = audio.parent / "transcript.txt"
    path.write_text(
        "\n".join(f"[{s.start:.3f}–{s.end:.3f}] {s.segment_id}: {s.text}" for s in recognized),
        encoding="utf-8",
    )
    return Transcript(
        "ready" if recognized else "empty",
        language,
        str(path),
        recognized,
        transcriber.configuration,
        str(audio),
        str(raw_path),
        normalization,
    )


def read_transcript(value: object, duration: float) -> Transcript:
    data = object_(value)
    config = object_(data["configuration"])
    configuration = TranscriptionConfig(
        text(config["backend"]),
        text(config["backend_version"]),
        text(config["model"]),
        text(config["revision"]),
        None if config["language"] is None else text(config["language"]),
        boolean(config["word_timestamps"]),
        number(config["temperature"]),
        boolean(config["condition_on_previous_text"]),
        integer(config["normalization_version"]),
        text(config["runtime_version"]),
        boolean(config["fp16"]),
        text(config["task"]),
    )
    normal = object_(data["normalization"])
    normalization = Normalization(
        integer(normal["source_stream"]),
        integer(normal["source_start_pts"]),
        text(normal["source_time_base"]),
        text(normal["recording_origin"]),
        text(normal["filter_graph"]),
        integer(normal["sample_rate"]),
        integer(normal["channels"]),
        integer(normal["version"]),
    )
    recognized = segments(data["segments"], duration)
    status = "ready" if recognized else "empty"
    if data["status"] != status:
        raise ValueError("Transcript availability disagrees with its segments")
    return Transcript(
        status,
        text(data["language"]),
        text(data["path"]),
        recognized,
        configuration,
        text(data["audio_path"]),
        text(data["raw_path"]),
        normalization,
    )
