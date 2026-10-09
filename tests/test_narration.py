import subprocess
import wave
from pathlib import Path

import pytest

from video_context import RecordingEvidence
from video_context.evidence import PreparationFailed
from video_context.transcription import TranscriptionConfig


class KnownSpeech:
    configuration = TranscriptionConfig("fixture", "1", "known-phrase", "v1", "en", False)

    def transcribe(self, audio: Path) -> object:
        with wave.open(str(audio)) as wav:
            assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (16000, 1, 2)
            assert wav.readframes(16000) == bytes(32000)
            assert any(wav.readframes(16000))
        return {
            "language": "en",
            "segments": [{"start": 1.0, "end": 2.0, "text": "Do not hide the blue button."}],
        }


def test_delayed_speech_is_searchable_and_overlaps_visual_inspection(tmp_path: Path) -> None:
    source = tmp_path / "delayed.mov"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=16x16:r=10:d=4",
            "-itsoffset",
            "1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=16000:duration=1",
            "-c:v",
            "libx264",
            "-c:a",
            "pcm_s16le",
            str(source),
        ],
        check=True,
    )
    evidence = RecordingEvidence(tmp_path / "store", transcriber=KnownSpeech())
    recording = evidence.prepare(source)
    assert recording.audio_status == "ready"
    matches = evidence.search(recording.recording_id, "NOT HIDE")
    assert [(s.start, s.end, s.text) for s in matches.matches] == [
        (1.0, 2.0, "Do not hide the blue button.")
    ]
    moment = evidence.inspect(recording.recording_id, start=1.5, end=2.5)
    assert [s.text for s in moment.segments] == ["Do not hide the blue button."]
    assert moment.frames[0].actual_time == 1.5
    assert recording.transcript is not None
    assert "Do not hide" in Path(recording.transcript.path).read_text()


def test_asr_failure_retains_visual_evidence_and_reports_failure(tmp_path: Path) -> None:
    class BrokenSpeech(KnownSpeech):
        def transcribe(self, audio: Path) -> object:
            raise RuntimeError("recognizer unavailable")

    source = tmp_path / "with-audio.mov"
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
    evidence = RecordingEvidence(tmp_path / "store", transcriber=BrokenSpeech())
    with pytest.raises(PreparationFailed, match="recognizer unavailable") as failed:
        evidence.prepare(source)
    recording = failed.value.recording
    assert recording.audio_status == "failed"
    assert recording.visual_status == "ready"
    assert evidence.inspect(recording.recording_id, 0).status == "ready"
    with pytest.raises(ValueError, match="unavailable"):
        evidence.search(recording.recording_id, "hello")


def test_invalid_word_times_do_not_become_precise_evidence(tmp_path: Path) -> None:
    class InvalidWords(KnownSpeech):
        def transcribe(self, audio: Path) -> object:
            return {
                "language": "en",
                "segments": [
                    {
                        "start": 0,
                        "end": 1,
                        "text": "Do not hide",
                        "words": [{"start": 0.2, "end": 4, "word": "not"}],
                    }
                ],
            }

    source = tmp_path / "words.mov"
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
    evidence = RecordingEvidence(tmp_path / "store", transcriber=InvalidWords())
    with pytest.raises(PreparationFailed, match="word interval"):
        evidence.prepare(source)


def test_short_audio_gap_is_preserved_as_silence(tmp_path: Path) -> None:
    class GapSpeech(KnownSpeech):
        def transcribe(self, audio: Path) -> object:
            with wave.open(str(audio)) as wav:
                wav.setpos(4096)
                assert wav.readframes(800) == bytes(1600)
                assert any(wav.readframes(800))
            return {"language": "en", "segments": []}

    source = tmp_path / "audio-gap.mov"
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
            "sine=sample_rate=16000:duration=1",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-bsf:a",
            "setts=pts=PTS+gte(N\\,5)*800:dts=DTS+gte(N\\,5)*800",
            str(source),
        ],
        check=True,
    )
    evidence = RecordingEvidence(tmp_path / "store", transcriber=GapSpeech())
    recording = evidence.prepare(source)
    assert recording.audio_status == "empty"
    assert evidence.search(recording.recording_id, "hello").matches == []


def test_selected_audio_stream_is_recorded_in_normalization_provenance(tmp_path: Path) -> None:
    class ToneSpeech(KnownSpeech):
        def transcribe(self, audio: Path) -> object:
            with wave.open(str(audio)) as wav:
                assert any(wav.readframes(16000))
            return {"language": "en", "segments": []}

    source = tmp_path / "two-audio.mov"
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
            "anullsrc=r=16000:cl=mono:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=duration=2",
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-map",
            "2:a",
            "-c:v",
            "libx264",
            "-c:a",
            "pcm_s16le",
            str(source),
        ],
        check=True,
    )
    evidence = RecordingEvidence(tmp_path / "store", transcriber=ToneSpeech())
    recording = evidence.prepare(source, audio_stream=2)
    assert recording.transcript is not None
    assert recording.transcript.normalization.source_stream == 2
    assert recording.transcript.normalization.sample_rate == 16000
    with pytest.raises(ValueError, match="audio stream"):
        evidence.prepare(source, audio_stream=0)


def test_literal_search_is_bounded_and_keeps_recording_order(tmp_path: Path) -> None:
    class RepeatedSpeech(KnownSpeech):
        def transcribe(self, audio: Path) -> object:
            return {
                "language": "en",
                "segments": [
                    {"start": 0, "end": 0.5, "text": "Keep [X] visible."},
                    {"start": 0.5, "end": 1.0, "text": "Hide y."},
                    {"start": 1.0, "end": 1.5, "text": "Do not hide [x]."},
                ],
            }

    source = tmp_path / "search.mov"
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
    evidence = RecordingEvidence(tmp_path / "store", transcriber=RepeatedSpeech())
    recording = evidence.prepare(source)
    first = evidence.search(recording.recording_id, "[x]", limit=1)
    assert [(s.start, s.text) for s in first.matches] == [(0, "Keep [X] visible.")]
    assert first.next_offset == 1
    second = evidence.search(recording.recording_id, "[x]", limit=1, offset=first.next_offset)
    assert [(s.start, s.text) for s in second.matches] == [(1.0, "Do not hide [x].")]
    assert second.next_offset is None
    assert evidence.search(recording.recording_id, ".*").matches == []
