import subprocess
from pathlib import Path

import pytest
from PIL import Image

from video_context import RecordingEvidence


def test_dense_interval_recovers_change_missed_by_overview(tmp_path: Path) -> None:
    source = tmp_path / "flash.mov"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x90:r=10:d=4,drawbox=color=red:t=fill:enable='eq(n,12)'",
            "-c:v",
            "libx264",
            str(source),
        ],
        check=True,
    )
    evidence = RecordingEvidence(tmp_path / "store")
    recording = evidence.prepare(source)
    assert all(frame.actual_time != 1.2 for frame in recording.overview.frames)
    moment = evidence.inspect(recording.recording_id, start=1.1, end=1.4, source_frames=True)
    assert [f.actual_time for f in moment.frames] == [1.1, 1.2, 1.3]
    pixels = []
    for frame in moment.frames:
        with Image.open(frame.path) as im:
            pixels.append(im.convert("RGB").tobytes()[:3])
    assert pixels[0][2] > 240
    assert pixels[1][0] > 240 and pixels[1][2] < 15
    assert pixels[2][2] > 240


def test_sampling_covers_long_interval_and_dense_mode_has_explicit_limit(tmp_path: Path) -> None:
    source = tmp_path / "long.mov"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=16x16:r=10:d=20",
            "-c:v",
            "libx264",
            str(source),
        ],
        check=True,
    )
    evidence = RecordingEvidence(tmp_path / "store")
    recording = evidence.prepare(source)
    sampled = evidence.inspect(recording.recording_id, start=0, end=20)
    assert len(sampled.frames) == 24
    assert sampled.frames[0].actual_time == 0
    assert sampled.frames[-1].actual_time >= 19
    assert sampled.sampling_interval == pytest.approx(20 / 24)
    with pytest.raises(ValueError, match="120.*narrower"):
        evidence.inspect(recording.recording_id, start=0, end=20, source_frames=True)


def test_variable_timing_source_offset_and_gap_use_real_presentation_times(tmp_path: Path) -> None:
    source = tmp_path / "offset-gap.mov"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=16x16:r=10:d=2",
            "-vf",
            "setpts=PTS+1/TB+gte(N\\,10)*0.3/TB",
            "-fps_mode",
            "passthrough",
            "-c:v",
            "libx264",
            str(source),
        ],
        check=True,
    )
    evidence = RecordingEvidence(tmp_path / "store")
    recording = evidence.prepare(source)
    assert recording.duration == 2.3
    assert evidence.inspect(recording.recording_id, at=1.05).actual_time == 1.3
    assert evidence.inspect(recording.recording_id, start=1.0, end=1.3).frames == []
    dense = evidence.inspect(recording.recording_id, start=0.8, end=1.5, source_frames=True)
    assert [f.actual_time for f in dense.frames] == [0.8, 0.9, 1.3, 1.4]


def test_crops_use_upright_square_pixel_display_coordinates(tmp_path: Path) -> None:
    source, rotated = tmp_path / "wide.mov", tmp_path / "rotated.mov"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=80x40:r=1:d=1,drawbox=x=0:y=0:w=40:h=40:color=red:t=fill,setsar=2/1",
            "-c:v",
            "libx264",
            str(source),
        ],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-display_rotation:v:0",
            "90",
            "-i",
            str(source),
            "-c",
            "copy",
            str(rotated),
        ],
        check=True,
    )
    evidence = RecordingEvidence(tmp_path / "store")
    recording = evidence.prepare(rotated)
    assert (recording.width, recording.height) == (40, 160)
    frame = evidence.inspect(recording.recording_id, at=0, crop=(5, 100, 20, 30))
    assert frame.path is not None
    with Image.open(frame.path) as im:
        assert im.size == (20, 30)
        pixel = im.convert("RGB").tobytes()[:3]
        assert pixel[0] > 240 and pixel[2] < 15
    with pytest.raises(ValueError, match="crop"):
        evidence.inspect(recording.recording_id, at=0, crop=(30, 0, 20, 30))


@pytest.mark.parametrize(
    "start,end", [(0, 0), (1, 0), (-1, 1), (0, 3), (float("nan"), 1), (0, float("inf"))]
)
def test_invalid_intervals_have_explicit_errors(tmp_path: Path, start: float, end: float) -> None:
    source = tmp_path / "clip.mov"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=16x16:r=1:d=2",
            "-c:v",
            "libx264",
            str(source),
        ],
        check=True,
    )
    evidence = RecordingEvidence(tmp_path / "store")
    recording = evidence.prepare(source)
    with pytest.raises(ValueError, match="Interval"):
        evidence.inspect(recording.recording_id, start=start, end=end)


def test_short_frame_intervals_are_not_rounded_to_nominal_rate(tmp_path: Path) -> None:
    source = tmp_path / "burst.mov"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=16x16:r=600:d=0.006",
            "-vf",
            "setpts=if(lt(N\\,3)\\,N*2\\,600)",
            "-bf",
            "0",
            "-fps_mode",
            "passthrough",
            "-c:v",
            "libx264",
            str(source),
        ],
        check=True,
    )
    evidence = RecordingEvidence(tmp_path / "store")
    recording = evidence.prepare(source)
    result = evidence.inspect(recording.recording_id, start=0, end=1, source_frames=True)
    assert [f.actual_time for f in result.frames] == [0, 1 / 300, 2 / 300]
