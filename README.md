# Video Context

Local preprocessing of narrated screen recordings for AI coding agents.

Record a normal macOS screen recording with microphone narration, then give the
recording's path to Codex. The intended tool will provide timestamped transcripts
and visual evidence that the agent can inspect alongside a codebase.

## Status

The visual slices prepare local MOV/MP4 recordings, create a sparse overview,
and retrieve timestamped frames, intervals, and crops in later CLI processes.
Local transcription and literal transcript search are available with the optional
Apple Silicon ASR dependencies. The Codex skill remains planned. No speech model
is needed or downloaded for silent recordings or explicit visual-only preparation.

## Prepare and inspect

Requires Python 3.12+, uv, and `ffmpeg`/`ffprobe` on PATH (verified with FFmpeg 8.1.2).

```bash
uv sync --locked
uv run video-context prepare /absolute/path/recording.mov --store ./work/evidence
# Use recording_id from the JSON above, with the same store:
uv run video-context inspect RECORDING_ID --at 1.15 --store ./work/evidence
uv run video-context inspect RECORDING_ID --start 1.1 --end 1.4 --source-frames --store ./work/evidence
uv run video-context inspect RECORDING_ID --at 1.2 --crop 10,10,120,60 --store ./work/evidence
```

For narrated recordings on Apple Silicon, explicitly install and fetch a pinned
model once. Preparation itself only uses local model files and never uploads media:

```bash
uv sync --extra asr --locked
uv run --extra asr video-context models fetch small
uv run --extra asr video-context prepare /absolute/path/narrated.mov --model small --language en
uv run video-context search RECORDING_ID "offline" --limit 10
```

Omit `--language` for detection. `small` is provisional pending the comparison
with `turbo`; both model revisions are pinned in the package. `--visual-only`
skips recognition. `--audio-stream N` selects an absolute source stream index;
otherwise the first audio stream is used. Audio is normalized to 16 kHz mono
PCM with delayed starts and timestamp gaps preserved as silence. Normalization,
model revision, package version, and decoding settings are recorded with evidence.

Search matches literal case-insensitive substrings in recording order. Use the
returned `next_offset` with `--offset` to continue. Inspection returns all speech
segments overlapping the requested point or interval. Speech and word times are
estimates: inspect surrounding moments before interpreting brief gestures.

Both commands write JSON to stdout; failures write diagnostics to stderr and exit
nonzero. `--at` is a finite, nonnegative recording time in seconds. Inspection
returns the first decoded frame at or after that time, with `requested_time`,
`actual_time`, and an absolute PNG `path`. If there is no such frame, it returns
`status: "no_frame"` with null `actual_time` and `path` (exit 0).

Preparation returns a SHA-256 `recording_id`, video duration in seconds, displayed
`width`/`height`, stage availability, a manifest path, and an overview. Open the
overview image for orientation, then inspect individual full-resolution frames.
The overview labels up to 12 samples spanning first to last frame; it can omit
events. Audio status distinguishes `no_audio`, `skipped`, `ready`, `empty`, and
`failed`. A recognition failure publishes available visuals, prints the partial
result as JSON, reports the error on stderr, and exits nonzero. `empty` means
recognition completed without speech segments, not that the media had no audio.

Intervals are half-open `[start, end)`. Sampling defaults to every 0.5 seconds,
spreading a maximum of 24 requests across longer intervals. `sampling_interval`
reports the effective spacing. `--source-frames` returns every decoded frame in
the interval, or asks for a narrower interval above 120 frames. Gaps never create
invented frames. `--crop x,y,width,height` uses upright, square-pixel display
coordinates; out-of-bounds crops fail clearly.

Supported now: one progressive video stream, variable frame intervals, nonzero
source starts, frame gaps, quarter-turn rotation, and non-square pixels. Times
use the earliest audio/video stream start as the recording playback origin.
Changing dimensions, changing display metadata, interlacing, arbitrary rotation,
and HDR transfer functions remain unsupported.

The original stays untouched. Its content hash identifies the recording and is
checked around fresh extraction. Repeating preparation with compatible settings
reuses completed evidence. Renamed identical files can be re-associated by preparing
their new path. `--overview-frames 1..12` changes only visual sampling; it reuses
compatible speech. Switching back to an earlier speech configuration also reuses
its completed transcript. `--visual-only` may retain already cached speech.

Writers for each recording are serialized with a POSIX file lock. Complete
generations publish atomically; interruption or a failed replacement preserves
the previous result. `generation` and `generation_manifest` identify the immutable
snapshot. Search and inspection also return generation identifiers; frames have
stable source-frame identifiers and crop coordinates. Keep these with evidence
citations when models or settings change.

Cached artifacts are checked by checksum. Damaged derived artifacts are rebuilt
when possible; invalid manifests or unsupported schemas require `prepare ...
--rebuild`. This also upgrades stores from the initial schema. Cached speech and
frames remain readable if the original disappears, with `source_status` reporting
`unavailable` or `changed`. An uncached frame still requires the original bytes.

No automatic eviction or deletion runs. Older generations and interrupted work
remain on disk. Stores contain local source paths, audio, text, and images; the
default store is `~/Library/Caches/video-context`.

Python callers use `RecordingEvidence(Path(store)).prepare(Path(source))` and
`.inspect(recording_id, at=seconds)`, imported from `video_context`. Results are
dataclasses; unsupported input raises `ValueError`, filesystem failures `OSError`.

Based on [cmoyates/python-template](https://github.com/cmoyates/python-template),
commit `d241bd750afee8beee62a6a8ed2e926b3dc88731`. Template history is retained.
Repository: [cmoyates/video-context](https://github.com/cmoyates/video-context).

## Agreed direction

- Keep recording natural: use macOS Command-Shift-5, select the recording area,
  enable the microphone, and narrate while using the app. No custom recorder or
  manual timestamp annotations are required.
- Process recordings locally: extract audio, transcribe speech, index timestamps,
  and extract frames on the Mac. Selected frames and transcript text may become
  context for the coding agent; local preprocessing is not local model inference.
- Preserve original recordings and their timeline. Cache derived artifacts so
  follow-up questions do not require transcription again.
- Let the agent inspect any moment, including nearby frames and crops. Initial
  keyframes must not be the only available visual evidence.
- Preserve cursor movements and subtle UI changes when selecting frames. Ordinary
  recordings do not supply a separate click-event track.
- Distinguish spoken requests, visible observations, and uncertain interpretations.
  App playback audio must not automatically become an instruction from the user.
- Start with Python, FFmpeg/ffprobe, a replaceable local transcription backend,
  and a CLI plus Codex skill. Evaluate MLX Whisper on a representative recording;
  MCP and local OCR are optional later additions.
- SpeechCatcher is the first use case; keep this tool independent of its repository.

## Design

- [Implementation proposal and self-grill](docs/design/video-context-v1.md):
  scope, interfaces, timing/cache contracts, and proposed TDD seams.
- [Implementation research](docs/research/2026-10-09-video-context.md):
  existing tools, pinned source references, and local timing experiments.
- [Glossary](GLOSSARY.md) and [local evidence decision](docs/adr/0001-local-evidence-before-interpretation.md).

Implementation follows the agreed public evidence and CLI seams. Final model
selection and narrated-workflow acceptance remain to be evaluated.

## Development

The Python 3.12 baseline is retained from the template. Development dependencies
are locked in `uv.lock`. Run commands from this directory:

```bash
uv sync --locked
uv run video-context --help
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
# Opt-in real inference on generated speech; requires the downloaded small model:
VIDEO_CONTEXT_REAL_MODEL=small uv run --extra asr pytest tests/test_real_model.py
```

Tests under `tests/` use real FFmpeg-generated color/timing fixtures and the
installed CLI across separate processes. A silent SpeechCatcher development
simulator capture also exercised prepare → inspect; it is not proof of speech
recognition or unsupported timing. Source modules live under `src/`.
Local recordings and derived artifacts belong in the gitignored
`input/`, `output/`, and `work/` directories.

## What's Included

### Tooling — the Astral suite

- **[uv](https://github.com/astral-sh/uv)** — project and package management
- **[Ruff](https://github.com/astral-sh/ruff)** — formatting, linting, import sorting
- **[ty](https://github.com/astral-sh/ty)** — type checking
- **[pytest](https://github.com/pytest-dev/pytest)** — testing

### Editor (VS Code)

`.vscode/settings.json` configures format-on-save for Python:

- Format with Ruff
- Auto-fix lint issues
- Organize imports
- `ty` resolves imports from the project environment

`.vscode/extensions.json` recommends the Ruff and `ty` extensions.

### AI agents

Pre-wired for **Claude Code** (`.claude/`) and **OpenAI Codex CLI** (`.codex/`). Hooks run Ruff format, lint-fix, and import-sort automatically after the agent edits files, so AI-generated code matches the same standards as save-on-format. A stop hook also runs Ruff, `ty`, and `pytest` over the whole project before the agent finishes — blocking on type errors or failing tests.

Skills live in `.agents/skills/`. Matt Pocock's skills are also exposed to Claude
Code through relative symlinks in `.claude/skills/`, so both agents use the same
files. Preloaded with:

- **[Matt Pocock's skills](https://github.com/mattpocock/skills)** — all 27 published engineering and productivity skills, including TDD, diagnosing-bugs, code-review, implement, to-spec, to-tickets, grill-me, and triage. Updated on 2026-10-09 from [commit `49dd158`](https://github.com/mattpocock/skills/commit/49dd158d1076134a641b33efb035946536778336). Experimental and miscellaneous skills are excluded, matching the upstream plugin manifest. Project setup is complete: [AGENTS.md](AGENTS.md) points to the GitHub issue tracker, default triage labels, and single-context domain documentation conventions in [docs/agents](docs/agents/).
- **[btca-local](https://github.com/davis7dotsh/better-context/blob/main/skills/btca-local/SKILL.md)** — "Better Context App Local". Triggered with `use btca`, it lets the agent search any git repo locally by cloning (or updating) it under `~/.btca/agent/sandbox` and answering questions against the source with citations and code snippets.

## Configuration

Lint/format rules live in `pyproject.toml` under `[tool.ruff]`. Defaults:

- Line length: 100
- Target: Python 3.12+
- Lint rules: pycodestyle, Pyflakes, isort, pyupgrade, bugbear, simplify
- Quote style: double
