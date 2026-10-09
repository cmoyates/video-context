import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_missing_vocabulary_fails_before_preparing_the_source(tmp_path: Path) -> None:
    cli = Path(sys.executable).parent / "video-context"
    missing = tmp_path / "missing-vocabulary.txt"
    result = subprocess.run(
        [str(cli), "prepare", "not-opened.mov", "--vocabulary", str(missing)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "missing-vocabulary.txt" in result.stderr
    assert "No such file" in result.stderr
    assert not result.stdout


@pytest.mark.parametrize("contents", [b"\xff", b"Example\x00Product"])
def test_invalid_vocabulary_is_a_clear_cli_failure(tmp_path: Path, contents: bytes) -> None:
    vocabulary = tmp_path / "invalid.txt"
    vocabulary.write_bytes(contents)
    cli = Path(sys.executable).parent / "video-context"
    result = subprocess.run(
        [str(cli), "prepare", "not-opened.mov", "--vocabulary", str(vocabulary)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert result.stderr.startswith("video-context:")
    assert "not-opened.mov" not in result.stderr
    assert not result.stdout


def test_silent_recording_survives_a_second_cli_process(tmp_path: Path) -> None:
    source = tmp_path / "silent.mov"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x90:r=10:d=2,drawbox=color=red:t=fill:enable='eq(n,12)'",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
    )
    original = source.read_bytes()
    cli = Path(sys.executable).parent / "video-context"
    prepared = subprocess.run(
        [str(cli), "prepare", str(source), "--store", str(tmp_path / "store")],
        capture_output=True,
        text=True,
    )
    assert prepared.returncode == 0, prepared.stderr
    recording = json.loads(prepared.stdout)
    inspected = subprocess.run(
        [
            str(cli),
            "inspect",
            recording["recording_id"],
            "--at",
            "1.15",
            "--store",
            str(tmp_path / "store"),
        ],
        capture_output=True,
        text=True,
    )
    assert inspected.returncode == 0, inspected.stderr
    frame = json.loads(inspected.stdout)
    assert frame["requested_time"] == 1.15
    assert frame["actual_time"] == 1.2
    pixels = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", frame["path"], "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True,
        check=True,
    ).stdout
    assert pixels[0] > 240 and pixels[1] < 15 and pixels[2] < 15
    assert source.read_bytes() == original
    interval = subprocess.run(
        [
            str(cli),
            "inspect",
            recording["recording_id"],
            "--start",
            "1.1",
            "--end",
            "1.4",
            "--source-frames",
            "--crop",
            "10,10,20,20",
            "--store",
            str(tmp_path / "store"),
        ],
        capture_output=True,
        text=True,
    )
    assert interval.returncode == 0, interval.stderr
    assert [f["actual_time"] for f in json.loads(interval.stdout)["frames"]] == [1.1, 1.2, 1.3]


@pytest.mark.parametrize("at", ["-1", "nan", "inf", "-inf", "garbage"])
def test_invalid_time_is_a_useful_cli_error(tmp_path: Path, at: str) -> None:
    cli = Path(sys.executable).parent / "video-context"
    result = subprocess.run(
        [
            str(cli),
            "inspect",
            "a" * 64,
            f"--at={at}",
            "--store",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert result.stdout == ""
    assert "Requested time" in result.stderr or "--at" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("kind", ["corrupt", "missing", "audio_only", "missing_ffmpeg"])
def test_input_failures_have_diagnostics(tmp_path: Path, kind: str) -> None:
    source = tmp_path / "source.mp4"
    environment = None
    if kind == "corrupt":
        source.write_bytes(b"not a movie")
    elif kind == "audio_only":
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=duration=0.1",
                "-c:a",
                "aac",
                str(source),
            ],
            check=True,
        )
    elif kind == "missing_ffmpeg":
        source.write_bytes(b"not a movie")
        environment = {"PATH": str(tmp_path)}
    cli = Path(sys.executable).parent / "video-context"
    result = subprocess.run(
        [
            str(cli),
            "prepare",
            str(source),
            "--store",
            str(tmp_path / "store"),
        ],
        capture_output=True,
        text=True,
        env=environment,
    )
    assert result.returncode != 0
    assert result.stdout == ""
    assert "Traceback" not in result.stderr
    assert result.stderr.strip()


def test_cli_reports_unavailable_transcript_without_a_traceback(tmp_path: Path) -> None:
    cli = Path(sys.executable).parent / "video-context"
    result = subprocess.run(
        [str(cli), "search", "a" * 64, "hello", "--store", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "not prepared" in result.stderr
    assert "Traceback" not in result.stderr


def test_missing_local_model_returns_partial_visual_result_and_explicit_setup(
    tmp_path: Path,
) -> None:
    source = tmp_path / "needs-model.mov"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=16x16:r=1:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=duration=2",
            "-c:v",
            "libx264",
            "-c:a",
            "pcm_s16le",
            str(source),
        ],
        check=True,
    )
    cli = Path(sys.executable).parent / "video-context"
    env = {**os.environ, "HF_HUB_CACHE": str(tmp_path / "empty-model-cache"), "HF_HUB_OFFLINE": "1"}
    result = subprocess.run(
        [str(cli), "prepare", str(source), "--store", str(tmp_path / "store")],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 1
    recording = json.loads(result.stdout)
    assert recording["visual_status"] == "ready" and recording["audio_status"] == "failed"
    assert "models fetch turbo" in result.stderr or "Install video-context[asr]" in result.stderr
