import json
import os
import shutil
import signal
import subprocess
import sys
import time
import wave
from dataclasses import replace
from pathlib import Path

import pytest

from video_context import RecordingEvidence
from video_context.evidence import PreparationFailed
from video_context.transcription import TranscriptionConfig


class ReferenceSpeech:
    configuration = TranscriptionConfig("fixture", "1", "reference", "v1", "en", False)

    def transcribe(self, audio: Path) -> object:
        return {
            "language": "en",
            "segments": [{"start": 0.2, "end": 1.2, "text": "Do not hide this button."}],
        }


class UnavailableSpeech(ReferenceSpeech):
    def transcribe(self, audio: Path) -> object:
        raise RuntimeError("external recognizer unavailable")


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "source.mov"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=16x16:r=10:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=duration=2",
            "-c:v",
            "libx264",
            "-c:a",
            "pcm_s16le",
            str(path),
        ],
        check=True,
    )
    return path


def test_prepared_evidence_is_reused_when_recognizer_is_unavailable(
    source: Path, tmp_path: Path
) -> None:
    initial = RecordingEvidence(tmp_path / "store", transcriber=ReferenceSpeech()).prepare(source)
    evidence = RecordingEvidence(tmp_path / "store", transcriber=UnavailableSpeech())
    reused = evidence.prepare(source)
    assert reused.cache_status == "reused"
    assert initial.transcript is not None and reused.transcript is not None
    assert reused.transcript.path == initial.transcript.path
    assert evidence.search(reused.recording_id, "not hide").matches[0].start == 0.2
    assert evidence.inspect(reused.recording_id, at=0.5).actual_time == 0.5


def test_vocabulary_is_preserved_and_identical_hints_reuse_speech(
    source: Path, tmp_path: Path
) -> None:
    configuration = replace(
        ReferenceSpeech.configuration,
        vocabulary=("Font Awesome", "Example UI"),
        carry_initial_prompt=True,
    )

    class HintedSpeech(ReferenceSpeech):
        def __init__(self) -> None:
            self.configuration = configuration

    class UnavailableHintedSpeech(HintedSpeech):
        def transcribe(self, audio: Path) -> object:
            raise RuntimeError("external recognizer unavailable")

    initial = RecordingEvidence(tmp_path / "store", transcriber=HintedSpeech()).prepare(source)
    evidence = RecordingEvidence(tmp_path / "store", transcriber=UnavailableHintedSpeech())
    reused = evidence.prepare(source)
    assert reused.cache_status == "reused"
    assert reused.generation == initial.generation
    assert reused.transcript is not None
    assert reused.transcript.configuration.vocabulary == ("Font Awesome", "Example UI")
    assert evidence.search(reused.recording_id, "not hide").matches[0].text == (
        "Do not hide this button."
    )


def test_identical_moved_source_is_reassociated_without_recognition(
    source: Path, tmp_path: Path
) -> None:
    original = RecordingEvidence(tmp_path / "store", transcriber=ReferenceSpeech()).prepare(source)
    moved = source.rename(tmp_path / "renamed.mov")
    evidence = RecordingEvidence(tmp_path / "store", transcriber=UnavailableSpeech())
    recording = evidence.prepare(moved)
    assert recording.recording_id == original.recording_id
    assert recording.source == str(moved)
    assert recording.transcript is not None and original.transcript is not None
    assert recording.transcript.path == original.transcript.path
    assert evidence.inspect(recording.recording_id, at=0.5).status == "ready"


def test_failed_configuration_change_keeps_previous_published_evidence(
    source: Path, tmp_path: Path
) -> None:
    initial = RecordingEvidence(tmp_path / "store", transcriber=ReferenceSpeech()).prepare(source)

    class NewUnavailableSpeech(UnavailableSpeech):
        configuration = replace(ReferenceSpeech.configuration, revision="v2")

    evidence = RecordingEvidence(tmp_path / "store", transcriber=NewUnavailableSpeech())
    with pytest.raises(PreparationFailed):
        evidence.prepare(source)
    assert (
        evidence.search(initial.recording_id, "not hide").matches[0].text
        == "Do not hide this button."
    )
    retained = RecordingEvidence(tmp_path / "store", transcriber=UnavailableSpeech()).prepare(
        source
    )
    assert retained.generation == initial.generation


def test_corrupt_transcript_is_rebuilt_instead_of_reported_as_a_cache_hit(
    source: Path, tmp_path: Path
) -> None:
    evidence = RecordingEvidence(tmp_path / "store", transcriber=ReferenceSpeech())
    initial = evidence.prepare(source)
    assert initial.transcript is not None
    Path(initial.transcript.path).write_text("corrupt")
    with pytest.raises(ValueError, match="artifact"):
        evidence.search(initial.recording_id, "button")
    rebuilt = evidence.prepare(source)
    assert rebuilt.cache_status == "rebuilt"
    assert rebuilt.transcript is not None
    assert "Do not hide" in Path(rebuilt.transcript.path).read_text()


def test_changing_overview_sampling_reuses_the_completed_transcript(
    source: Path, tmp_path: Path
) -> None:
    initial = RecordingEvidence(tmp_path / "store", transcriber=ReferenceSpeech()).prepare(source)
    evidence = RecordingEvidence(tmp_path / "store", transcriber=UnavailableSpeech())
    changed = evidence.prepare(source, overview_count=6)
    assert len(changed.overview.frames) == 6
    assert changed.transcript is not None and initial.transcript is not None
    assert changed.transcript.path == initial.transcript.path
    assert changed.generation != initial.generation


def test_missing_original_keeps_cached_speech_and_frames_readable(
    source: Path, tmp_path: Path
) -> None:
    evidence = RecordingEvidence(tmp_path / "store", transcriber=ReferenceSpeech())
    recording = evidence.prepare(source)
    cached = evidence.inspect(recording.recording_id, at=0.8)
    assert cached.recording_id == recording.recording_id
    assert cached.generation == recording.generation
    assert cached.frame_id == "f000008"
    source.rename(tmp_path / "unavailable-at-original-path.mov")
    search = evidence.search(recording.recording_id, "not hide")
    assert search.source_status == "unavailable"
    retrieved = evidence.inspect(recording.recording_id, at=0.8)
    assert retrieved.path == cached.path
    assert retrieved.source_status == "unavailable"
    with pytest.raises(ValueError, match="Source unavailable.*not cached"):
        evidence.inspect(recording.recording_id, at=1.3)


def test_concurrent_cli_preparations_share_one_complete_generation(
    source: Path, tmp_path: Path
) -> None:
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg is not None
    tools = tmp_path / "tools"
    tools.mkdir()
    wrapper = tools / "ffmpeg"
    wrapper.write_text(f'#!/bin/sh\n/bin/sleep 0.3\nexec "{ffmpeg}" "$@"\n')
    wrapper.chmod(0o755)
    env = {**os.environ, "PATH": f"{tools}:{os.environ['PATH']}"}
    cli = Path(sys.executable).parent / "video-context"
    command = [
        str(cli),
        "prepare",
        str(source),
        "--visual-only",
        "--store",
        str(tmp_path / "store"),
    ]
    with (
        subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env
        ) as first,
        subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env
        ) as second,
    ):
        out1, err1 = first.communicate(timeout=30)
        out2, err2 = second.communicate(timeout=30)
        assert first.returncode == second.returncode == 0, (err1, err2)
    one, two = json.loads(out1), json.loads(out2)
    assert one["generation"] == two["generation"]
    assert {one["cache_status"], two["cache_status"]} == {"prepared", "reused"}
    assert Path(one["overview"]["path"]).is_file()


def test_interrupted_cli_writer_leaves_old_generation_readable_and_retryable(
    source: Path, tmp_path: Path
) -> None:
    store = tmp_path / "store"
    initial = RecordingEvidence(store, transcriber=ReferenceSpeech()).prepare(source)
    tools = tmp_path / "tools"
    tools.mkdir()
    ready = tmp_path / "encoder-started"
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg is not None
    wrapper = tools / "ffmpeg"
    wrapper.write_text(
        f'#!/bin/sh\n: > "$VIDEO_CONTEXT_STAGE_READY"\n/bin/sleep 10\nexec "{ffmpeg}" "$@"\n'
    )
    wrapper.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{tools}:{os.environ['PATH']}",
        "VIDEO_CONTEXT_STAGE_READY": str(ready),
    }
    cli = Path(sys.executable).parent / "video-context"
    command = [
        str(cli),
        "prepare",
        str(source),
        "--visual-only",
        "--overview-frames",
        "6",
        "--store",
        str(store),
    ]
    with subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        start_new_session=True,
    ) as writer:
        try:
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline and writer.poll() is None:
                time.sleep(0.02)
            if writer.poll() is not None:
                pytest.fail(writer.communicate()[1])
            assert ready.exists(), "external encoder did not start"
            read = subprocess.run(
                [str(cli), "search", initial.recording_id, "not hide", "--store", str(store)],
                capture_output=True,
                text=True,
                timeout=5,
            )
            assert read.returncode == 0, read.stderr
            assert json.loads(read.stdout)["matches"][0]["text"] == "Do not hide this button."
        finally:
            if writer.poll() is None:
                os.killpg(writer.pid, signal.SIGTERM)
            writer.communicate(timeout=5)
    evidence = RecordingEvidence(store, transcriber=UnavailableSpeech())
    assert evidence.prepare(source).generation == initial.generation
    retried = evidence.prepare(source, overview_count=6)
    assert len(retried.overview.frames) == 6
    assert retried.transcript is not None and initial.transcript is not None
    assert retried.transcript.path == initial.transcript.path


def test_unknown_manifest_version_requires_explicit_rebuild(source: Path, tmp_path: Path) -> None:
    evidence = RecordingEvidence(tmp_path / "store", transcriber=ReferenceSpeech())
    original = evidence.prepare(source)
    manifest = Path(original.manifest)
    contents = json.loads(manifest.read_text())
    contents["schema_version"] = 99
    manifest.write_text(json.dumps(contents))
    with pytest.raises(ValueError, match="manifest"):
        evidence.prepare(source)
    rebuilt = evidence.prepare(source, rebuild=True)
    assert rebuilt.generation != original.generation
    assert rebuilt.cache_status == "rebuilt"
    assert evidence.search(rebuilt.recording_id, "not hide").matches


def test_default_stream_does_not_reuse_a_different_explicit_stream(
    source: Path, tmp_path: Path
) -> None:
    class ToneSpeech(ReferenceSpeech):
        def transcribe(self, audio: Path) -> object:
            with wave.open(str(audio)) as wav:
                wording = "Tone" if any(wav.readframes(16000)) else "Silence"
            return {"language": "en", "segments": [{"start": 0, "end": 1, "text": wording}]}

    multiple = tmp_path / "multiple.mov"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(source),
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=16000:cl=mono:d=2",
            "-map",
            "0:v",
            "-map",
            "0:a",
            "-map",
            "1:a",
            "-c:v",
            "copy",
            "-c:a",
            "pcm_s16le",
            str(multiple),
        ],
        check=True,
    )
    evidence = RecordingEvidence(tmp_path / "store", transcriber=ToneSpeech())
    explicit = evidence.prepare(multiple, audio_stream=2)
    assert evidence.search(explicit.recording_id, "Silence").matches
    default = evidence.prepare(multiple)
    assert evidence.search(default.recording_id, "Tone").matches
    assert default.transcript is not None and default.transcript.normalization.source_stream == 1


@pytest.mark.parametrize(
    "configuration",
    [
        replace(ReferenceSpeech.configuration, revision="v2"),
        replace(ReferenceSpeech.configuration, backend_version="2"),
        replace(ReferenceSpeech.configuration, language="fr"),
        replace(ReferenceSpeech.configuration, temperature=0.2),
        replace(ReferenceSpeech.configuration, word_timestamps=True),
        replace(ReferenceSpeech.configuration, condition_on_previous_text=True),
        replace(ReferenceSpeech.configuration, normalization_version=2),
        replace(ReferenceSpeech.configuration, runtime_version="new-runtime"),
        replace(ReferenceSpeech.configuration, vocabulary=("Example Product",)),
        replace(ReferenceSpeech.configuration, carry_initial_prompt=True),
    ],
)
def test_changed_recognition_configuration_cannot_reuse_old_transcript(
    source: Path, tmp_path: Path, configuration: TranscriptionConfig
) -> None:
    class UpdatedSpeech(ReferenceSpeech):
        def __init__(self, config: TranscriptionConfig) -> None:
            self.configuration = config

        def transcribe(self, audio: Path) -> object:
            return {
                "language": "en",
                "segments": [{"start": 0, "end": 1, "text": "Updated wording."}],
            }

    old = RecordingEvidence(tmp_path / "store", transcriber=ReferenceSpeech()).prepare(source)
    evidence = RecordingEvidence(tmp_path / "store", transcriber=UpdatedSpeech(configuration))
    new = evidence.prepare(source)
    assert new.generation != old.generation
    assert evidence.search(new.recording_id, "Updated wording").matches
    assert new.transcript is not None and new.transcript.configuration == configuration


def test_new_bytes_at_the_same_path_are_a_new_recording(source: Path, tmp_path: Path) -> None:
    evidence = RecordingEvidence(tmp_path / "store", transcriber=ReferenceSpeech())
    old = evidence.prepare(source)
    source.write_bytes(source.read_bytes() + b"different trailing bytes")
    new = evidence.prepare(source)
    assert new.recording_id != old.recording_id
    assert evidence.search(old.recording_id, "not hide").source_status == "changed"
    assert evidence.search(new.recording_id, "not hide").source_status == "available"


def test_returning_to_an_earlier_configuration_reuses_its_completed_transcript(
    source: Path, tmp_path: Path
) -> None:
    original = RecordingEvidence(tmp_path / "store", transcriber=ReferenceSpeech()).prepare(source)

    class OtherSpeech(ReferenceSpeech):
        configuration = replace(ReferenceSpeech.configuration, revision="v2")

        def transcribe(self, audio: Path) -> object:
            return {
                "language": "en",
                "segments": [{"start": 0, "end": 1, "text": "Other wording."}],
            }

    RecordingEvidence(tmp_path / "store", transcriber=OtherSpeech()).prepare(source)
    restored = RecordingEvidence(tmp_path / "store", transcriber=UnavailableSpeech()).prepare(
        source
    )
    assert restored.cache_status == "reused"
    assert restored.transcript is not None and original.transcript is not None
    assert restored.transcript.path == original.transcript.path
