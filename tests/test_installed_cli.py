"""Opt-in acceptance against an installed command, without repository imports."""

import json
import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(not os.environ.get("VIDEO_CONTEXT_CLI"), reason="opt-in installed CLI")
def test_installed_cli_from_unrelated_directory(tmp_path: Path) -> None:
    command = os.environ["VIDEO_CONTEXT_CLI"]
    source = tmp_path / "known.mov"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=32x32:r=10:d=1",
            "-c:v",
            "libx264",
            str(source),
        ],
        check=True,
    )
    store = tmp_path / "evidence"

    def run(*args: str) -> dict[str, object]:
        result = subprocess.run(
            [command, *args, "--store", str(store)],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        )
        data: object = json.loads(result.stdout)
        assert isinstance(data, dict)
        return {str(key): value for key, value in data.items()}

    prepared = run("prepare", str(source))
    assert prepared["audio_status"] == "no_audio"
    recording_id = str(prepared["recording_id"])
    search = subprocess.run(
        [command, "search", recording_id, "settings", "--store", str(store)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert search.returncode == 1
    assert "Transcript unavailable" in search.stderr
    frame = run("inspect", recording_id, "--at", "0.15")
    assert frame["actual_time"] == 0.2
    assert frame["recording_id"] == recording_id
    assert frame["generation"] == prepared["generation"]
    assert Path(str(frame["path"])).is_file()
