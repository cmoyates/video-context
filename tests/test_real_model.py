"""Opt-in model acceptance; synthetic speech is not natural-narration accuracy."""

import os
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from video_context import RecordingEvidence
from video_context.transcription import MLXWhisper


@pytest.mark.real_model
@pytest.mark.skipif(not os.environ.get("VIDEO_CONTEXT_REAL_MODEL"), reason="opt-in local model run")
def test_known_delayed_speech_points_to_the_red_visual_moment(tmp_path: Path) -> None:
    speech, source = tmp_path / "speech.aiff", tmp_path / "spoken.mov"
    subprocess.run(
        [
            "say",
            "-v",
            "Samantha",
            "-o",
            str(speech),
            "Do not hide the blue button. Open the settings page.",
        ],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=32x32:r=10:d=12,drawbox=color=red:t=fill:enable='between(t,2,9)'",
            "-itsoffset",
            "2",
            "-i",
            str(speech),
            "-c:v",
            "libx264",
            "-c:a",
            "pcm_s16le",
            str(source),
        ],
        check=True,
    )
    evidence = RecordingEvidence(
        tmp_path / "store",
        transcriber=MLXWhisper(os.environ["VIDEO_CONTEXT_REAL_MODEL"], language="en"),
    )
    recording = evidence.prepare(source)
    result = evidence.search(recording.recording_id, "not hide")
    assert len(result.matches) == 1
    segment = result.matches[0]
    assert 1.5 <= segment.start < 5
    assert "blue button" in segment.text.lower()
    assert segment.words and all(word.estimated for word in segment.words)
    # Speech times are estimates: inspect the surrounding moment, not an exact speech onset.
    moment = evidence.inspect(
        recording.recording_id,
        start=max(0, segment.start - 0.5),
        end=min(recording.duration, segment.end + 0.5),
    )
    red_times = []
    for frame in moment.frames:
        with Image.open(frame.path) as im:
            pixel = im.convert("RGB").tobytes()[:3]
            if pixel[0] > 240 and pixel[2] < 15:
                red_times.append(frame.actual_time)
    assert red_times and all(2 <= time <= 9 for time in red_times)
