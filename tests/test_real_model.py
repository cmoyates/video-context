"""Opt-in model acceptance; synthetic speech is not natural-narration accuracy."""

import json
import os
import subprocess
import sys
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


@pytest.mark.real_model
@pytest.mark.skipif(not os.environ.get("VIDEO_CONTEXT_REAL_MODEL"), reason="opt-in local model run")
def test_vocabulary_file_guides_later_speech_and_reuses_effective_contents(tmp_path: Path) -> None:
    first, second, source = (tmp_path / name for name in ("first.aiff", "second.aiff", "late.mov"))
    for audio, phrase in (
        (first, "Do not hide the blue button. Keep the settings page open."),
        (second, "Replace this icon with the equivalent font awesome icon."),
    ):
        subprocess.run(["say", "-v", "Samantha", "-o", str(audio), phrase], check=True)
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=16x16:r=1:d=46",
            "-i",
            str(first),
            "-i",
            str(second),
            "-filter_complex",
            "[1:a]apad=whole_dur=46[a];[2:a]adelay=36000:all=1[b];"
            "[a][b]amix=inputs=2:normalize=0:duration=longest[audio]",
            "-map",
            "0:v",
            "-map",
            "[audio]",
            "-c:v",
            "libx264",
            "-c:a",
            "pcm_s16le",
            str(source),
        ],
        check=True,
    )
    vocabulary = tmp_path / "vocabulary.txt"
    vocabulary.write_text("# Project terms\n Font Awesome \n\nFont Awesome\n", encoding="utf-8")
    cli = Path(sys.executable).parent / "video-context"
    command = [
        str(cli),
        "prepare",
        str(source),
        "--model",
        os.environ["VIDEO_CONTEXT_REAL_MODEL"],
        "--language",
        "en",
        "--vocabulary",
        str(vocabulary),
        "--store",
        str(tmp_path / "store"),
    ]
    result = subprocess.run(command, cwd=tmp_path, check=True, capture_output=True, text=True)
    prepared = json.loads(result.stdout)
    transcript = prepared["transcript"]
    assert transcript["configuration"]["vocabulary"] == ["Font Awesome"]
    assert transcript["configuration"]["carry_initial_prompt"] is True
    matches = [s for s in transcript["segments"] if "Font Awesome" in s["text"]]
    assert matches and all(s["start"] >= 34 for s in matches)
    assert any("not hide" in s["text"].lower() for s in transcript["segments"])
    vocabulary.write_text("# Only the comment changed\nFont Awesome\n", encoding="utf-8")
    reused = json.loads(
        subprocess.run(
            command,
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    assert reused["generation"] == prepared["generation"]
    assert reused["cache_status"] == "reused"
    vocabulary.write_text("Font Awesome\nExample UI\n", encoding="utf-8")
    changed = json.loads(
        subprocess.run(
            command,
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    assert changed["generation"] != prepared["generation"]
    assert changed["transcript"]["configuration"]["vocabulary"] == ["Font Awesome", "Example UI"]
    assert all("Example UI" not in s["text"] for s in changed["transcript"]["segments"])
