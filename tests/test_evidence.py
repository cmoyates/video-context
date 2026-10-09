import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from video_context import RecordingEvidence


@pytest.fixture
def silent_clip(tmp_path: Path) -> Path:
    source = tmp_path / "silent.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x90:r=10:d=2",
            "-c:v",
            "libx264",
            str(source),
        ],
        check=True,
    )
    return source


def test_preparation_describes_sparse_visual_evidence(silent_clip: Path, tmp_path: Path) -> None:
    original = silent_clip.read_bytes()
    recording = RecordingEvidence(tmp_path / "store").prepare(silent_clip)
    assert recording.recording_id == hashlib.sha256(original).hexdigest()
    assert (recording.duration, recording.width, recording.height) == (2.0, 160, 90)
    assert recording.audio_status == "no_audio"
    assert recording.visual_status == "ready"
    assert recording.overview.sparse is True
    assert len(recording.overview.frames) == 12
    assert recording.overview.frames[0].actual_time == 0
    assert recording.overview.frames[-1].actual_time == 1.9
    for path in [
        recording.manifest,
        recording.overview.path,
        *(frame.path for frame in recording.overview.frames),
    ]:
        assert Path(path).is_absolute() and Path(path).is_file()
    manifest = json.loads(Path(recording.manifest).read_text())
    assert manifest["schema_version"] == 1
    assert manifest["status"] == "complete"
    assert silent_clip.read_bytes() == original


def test_modified_source_cannot_be_used_as_old_evidence(silent_clip: Path, tmp_path: Path) -> None:
    evidence = RecordingEvidence(tmp_path / "store")
    recording = evidence.prepare(silent_clip)
    replacement = tmp_path / "replacement.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=160x90:r=10:d=2",
            "-c:v",
            "libx264",
            str(replacement),
        ],
        check=True,
    )
    silent_clip.write_bytes(replacement.read_bytes())
    with pytest.raises(ValueError, match="Source changed"):
        evidence.inspect(recording.recording_id, at=0)


@pytest.mark.parametrize("change", [{"status": "partial"}, {"schema_version": 42}, {"frames": []}])
def test_incomplete_or_unknown_manifest_is_not_readable(
    silent_clip: Path,
    tmp_path: Path,
    change: dict[str, object],
) -> None:
    evidence = RecordingEvidence(tmp_path / "store")
    recording = evidence.prepare(silent_clip)
    manifest = Path(recording.manifest)
    data = json.loads(manifest.read_text())
    data.update(change)
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="manifest"):
        evidence.inspect(recording.recording_id, 0)


def test_end_of_recording_has_no_frame_at_or_after(silent_clip: Path, tmp_path: Path) -> None:
    evidence = RecordingEvidence(tmp_path / "store")
    recording = evidence.prepare(silent_clip)
    result = evidence.inspect(recording.recording_id, at=1.95)
    assert result.status == "no_frame"
    assert result.requested_time == 1.95
    assert result.actual_time is None
    assert result.path is None


@pytest.mark.parametrize(
    "filter_graph, dimensions, duration",
    [
        ("setpts=PTS+1/TB", (160, 90), 2.0),
        ("setpts=PTS+gte(N\\,10)*0.3/TB", (160, 90), 2.3),
        ("setsar=2/1", (320, 90), 2.0),
    ],
)
def test_offset_variable_timing_and_pixel_aspect_are_supported(
    silent_clip: Path,
    tmp_path: Path,
    filter_graph: str,
    dimensions: tuple[int, int],
    duration: float,
) -> None:
    unsupported = tmp_path / "unsupported.mov"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(silent_clip),
            "-vf",
            filter_graph,
            "-fps_mode",
            "passthrough",
            "-c:v",
            "libx264",
            str(unsupported),
        ],
        check=True,
    )
    evidence = RecordingEvidence(tmp_path / "store")
    recording = evidence.prepare(unsupported)
    assert (recording.width, recording.height) == dimensions
    assert recording.duration == duration
    assert evidence.inspect(recording.recording_id, 0).actual_time == 0


def test_rotated_video_reports_upright_dimensions(silent_clip: Path, tmp_path: Path) -> None:
    rotated = tmp_path / "rotated.mov"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-display_rotation:v:0",
            "90",
            "-i",
            str(silent_clip),
            "-c",
            "copy",
            str(rotated),
        ],
        check=True,
    )
    recording = RecordingEvidence(tmp_path / "store").prepare(rotated)
    assert (recording.width, recording.height) == (90, 160)


def test_audio_presence_is_not_mislabeled_as_silence(silent_clip: Path, tmp_path: Path) -> None:
    narrated = tmp_path / "with-audio.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(silent_clip),
            "-f",
            "lavfi",
            "-i",
            "sine=duration=2",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            str(narrated),
        ],
        check=True,
    )
    recording = RecordingEvidence(tmp_path / "store").prepare(narrated, visual_only=True)
    assert recording.audio_status == "skipped"
    assert recording.visual_status == "ready"


@pytest.mark.parametrize(
    "options",
    [
        ["-vf", "setparams=color_trc=smpte2084:color_primaries=bt2020:colorspace=bt2020nc"],
        ["-vf", "scale=160:96,setsar=1", "-flags", "+ildct+ilme"],
        ["-map", "0:v", "-map", "0:v"],
    ],
)
def test_unhandled_display_modes_are_rejected(
    silent_clip: Path,
    tmp_path: Path,
    options: list[str],
) -> None:
    source = tmp_path / "unsupported-display.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(silent_clip),
            *options,
            "-c:v",
            "libx264",
            str(source),
        ],
        check=True,
    )
    with pytest.raises(ValueError, match="Unsupported"):
        RecordingEvidence(tmp_path / "store").prepare(source)


def test_failed_render_does_not_publish_a_recording(
    silent_clip: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    ffprobe = shutil.which("ffprobe")
    assert ffprobe is not None
    (tools / "ffprobe").symlink_to(ffprobe)
    (tools / "ffmpeg").write_text("#!/bin/sh\necho 'simulated encoder failure' >&2\nexit 1\n")
    (tools / "ffmpeg").chmod(0o755)
    monkeypatch.setenv("PATH", str(tools))
    evidence = RecordingEvidence(tmp_path / "store")
    with pytest.raises(ValueError, match="simulated encoder failure"):
        evidence.prepare(silent_clip)
    with pytest.raises(ValueError, match="not prepared"):
        evidence.inspect(hashlib.sha256(silent_clip.read_bytes()).hexdigest(), 0)


def test_exact_time_and_one_frame_overview(tmp_path: Path) -> None:
    source = tmp_path / "one-frame.mov"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x90:r=10",
            "-frames:v",
            "1",
            "-c:v",
            "libx264",
            str(source),
        ],
        check=True,
    )
    evidence = RecordingEvidence(tmp_path / "store")
    recording = evidence.prepare(source)
    assert recording.duration == 0.1
    assert len(recording.overview.frames) == 1
    assert evidence.inspect(recording.recording_id, 0).actual_time == 0
    assert evidence.inspect(recording.recording_id, 0.000001).status == "no_frame"
