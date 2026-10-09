# Local video context: implementation research

Researched 2026-10-09 for the design in [the implementation plan](../design/video-context-v1.md).
The SpeechCatcher conversation established the user experience: record normally,
provide a local file path, and let the agent investigate speech and pictures
together. This investigation checked source code, official documentation, and a
small synthetic media probe. It did not run the competing products or benchmark
speech recognition on a real SpeechCatcher recording.

## Existing implementations worth learning from

### Talkthrough: durable evidence and follow-up retrieval

[Talkthrough](https://github.com/korovin-aa97/talkthrough-mcp/tree/350ac6b734eff003e0298950f85fdb8ea34d6abb)
is the closest existing match. Its README describes narrated local recordings,
transcripts, keyframes, OCR, and follow-up frame retrieval through MCP. Its source
uses file identity, stored manifests, per-job locking, and integrity checks to
reuse completed work. Explicitly requesting a different transcription model
invalidates the corresponding reuse path.
[Pipeline source](https://github.com/korovin-aa97/talkthrough-mcp/blob/350ac6b734eff003e0298950f85fdb8ea34d6abb/src/talkthrough_mcp/core/pipeline.py#L713)

Frame extraction combines scene changes with a time floor in one decode pass.
The floor becomes wider for long recordings, but scene-dense input can still hit
the frame cap early; the source explicitly reports that limitation. Exact-frame
retrieval and crops read the original recording again. Thus a cached overview
does not remove the need to keep the source available.
[Frame implementation](https://github.com/korovin-aa97/talkthrough-mcp/blob/350ac6b734eff003e0298950f85fdb8ea34d6abb/src/talkthrough_mcp/core/frames.py)

Its local transcription uses faster-whisper on CPU with int8 computation and
voice activity detection. It includes a vocabulary-echo heuristic because prompt
words can appear in recognition output over quiet openings. That is a useful
failure case to evaluate, not a heuristic to copy before measuring our own input.
[Transcription implementation](https://github.com/korovin-aa97/talkthrough-mcp/blob/350ac6b734eff003e0298950f85fdb8ea34d6abb/src/talkthrough_mcp/core/stt.py)

**Design inference:** borrow the durable evidence/retrieval pattern. Avoid taking
on its OCR, diarization, public URL ingestion, MCP transport, and speaker-identity
workflows for our first local-recording use case. The existing project is a strong
alternative if maintaining a custom tool later stops being valuable; this is not
a claim that it is inadequate.

### Watch / claude-video: a small agent-facing workflow

[Watch](https://github.com/bradautomates/claude-video/tree/03ceb42f7fa2c4439aca01752118044baabffb8f)
documents Codex support, a local extraction engine, transcript-guided timestamps,
focused intervals, frame budgets, and optional local WhisperX transcription. Its
README also describes cloud backends; those are outside our chosen processing
contract. The local route is the relevant comparison.
[README](https://github.com/bradautomates/claude-video/blob/03ceb42f7fa2c4439aca01752118044baabffb8f/README.md)

The source distinguishes requested timestamps from returned frame timestamps and
rejects missing/non-finite frame timestamps. It accounts for FFmpeg logging extra
filtered frames before an output cap stops encoding. Its deduplication uses small
RGB thumbnails, and the README explicitly warns that this can erase subtle visual
changes. It offers a no-dedup mode.
[Frame implementation](https://github.com/bradautomates/claude-video/blob/03ceb42f7fa2c4439aca01752118044baabffb8f/skills/watch/scripts/frames.py#L144)

**Design inference:** a CLI plus an agent skill is sufficient for an initial
integration. Keep requested and actual times, and allow direct retrieval without
deduplication. We do not need a persistent server to establish whether the
recording-to-evidence experience works.

## Local transcription choices

MLX Whisper exposes a Python `transcribe` function, model selection, and optional
word timestamps. Its documented default is a tiny model, so relying on the
library default would silently make an accuracy decision for this product.
[Official MLX Whisper README](https://github.com/ml-explore/mlx-examples/blob/796f5b53cab69a3d48a44233ce21aae889e94a08/whisper/README.md)

Its loader accepts a local model directory; a non-local reference invokes
Hugging Face download logic. Its model holder caches within a process, which
does not persist across separate CLI invocations. Recognition exposes silence
and hallucination-related controls, but those do not establish reliable narrator
identity or accuracy on application audio.
[Loader](https://github.com/ml-explore/mlx-examples/blob/796f5b53cab69a3d48a44233ce21aae889e94a08/whisper/mlx_whisper/load_models.py),
[transcription source](https://github.com/ml-explore/mlx-examples/blob/796f5b53cab69a3d48a44233ce21aae889e94a08/whisper/mlx_whisper/transcribe.py)

The official faster-whisper project offers a Python interface, CPU int8 execution,
word timestamps, and Silero voice activity detection. Its published performance
figures use specified hardware/settings and cannot be treated as measurements
for this Mac. It is a useful fallback candidate if MLX installation, accuracy, or
silence handling is unsatisfactory, rather than a second required backend.
[Official faster-whisper documentation](https://github.com/SYSTRAN/faster-whisper)

**Recommendation:** evaluate MLX first on this arm64 Mac. Compare a multilingual
small model with large-v3-turbo on a short representative recording; choose from
measured instruction accuracy, timing, runtime, memory, and first-download cost.
Do not select a final model solely from another project's speed chart. The
[large-v3-turbo model](https://huggingface.co/mlx-community/whisper-large-v3-turbo)
and [small MLX model](https://huggingface.co/mlx-community/whisper-small-mlx) are
candidate artifacts, not yet downloaded or accepted defaults.

Package metadata checked during this investigation: `mlx-whisper` 0.4.3,
`faster-whisper` 1.2.1, and Pillow 12.3.0. Resolve and lock the selected dependency
set when implementing; inspected upstream source can be newer than a package
release, so verify the installed release's interface at that point.
[MLX package](https://pypi.org/project/mlx-whisper/),
[faster-whisper package](https://pypi.org/project/faster-whisper/),
[Pillow package](https://pypi.org/project/Pillow/)

## Timing: facts to build around

FFmpeg documents that input seeking locates a preceding seek point and accurate
transcoding discards decoded content until the requested position. It also has
explicit timestamp-preservation and origin-shifting options. Requested seek time
therefore cannot substitute for the presentation timestamp of the decoded frame.
Rotation is applied by default during transcoding, which matters when defining
crop coordinates.
[Official FFmpeg documentation](https://ffmpeg.org/ffmpeg.html)

The installed tools are FFmpeg/ffprobe 8.1.2. A local synthetic experiment used a
three-second, 10 fps MOV with blue frames, a single red frame at 1.2 seconds, and
a one-second audio tone whose stream begins at 1.0 seconds. These are fixture
construction facts, not estimates from a transcription model.

| Experiment | Observed result | Design implication |
| --- | --- | --- |
| Extract audio to WAV normally | WAV lasts one second and starts at zero | Keep the source/audio mapping; WAV time alone loses the one-second offset. |
| Seek video at 1.25 s | First decoded frame has local PTS 0.05 s, corresponding to recording time 1.30 s | Return requested and actual times separately. |
| Keep timestamps, shift origin, resample with `first_pts=0` | WAV lasts two seconds; first tone sample above the probe threshold occurs at 1.0000625 s | Padding can preserve the leading audio offset on this fixture. |
| Overview at 0, 1, and 2 s | All selected frames are blue | Sparse overviews cannot guarantee brief-event coverage. |
| Decode nearby frames at 1.1, 1.2, and 1.3 s | Blue, red, blue | Dense follow-up retrieval recovers the missed event. |

The normalization command used `-copyts -start_at_zero` with
`aresample=16000:async=1:first_pts=0`. This verifies one delayed-audio example;
it does not validate every MOV edit list, audio discontinuity, rotation, or
variable-frame-rate recording. Use those as separate acceptance fixtures before
claiming general timestamp correctness. Keep integer PTS/time-base information
internally where practical; milliseconds in the public output are a display and
interchange convention, not a promise of millisecond ASR precision.

Raw local probe files are under the gitignored
`work/research/timing-probe/`, including `probe.json` and
`alignment-and-sampling.json`. They contain generated colors and tones only.

## What remains unverified

- No transcription model was installed or run. Model accuracy, speed, and memory
  on real narrated SpeechCatcher recordings remain open measurements.
- Neither Talkthrough nor Watch was installed or exercised; observations about
  them above come from the cited pinned source snapshots.
- The synthetic probe demonstrates two timing hazards and a sampling limitation;
  it is not a completed media adapter or a regression suite.
- The research supports a CLI/skill design, but the final skill still needs an
  end-to-end run inside a SpeechCatcher chat using a real recording.

The shortest credible route is to prove a small evidence-retrieval contract on
real media, then add convenience. OCR, embeddings, cloud video analysis, a custom
recorder, and a persistent MCP server do not resolve these initial uncertainties.
