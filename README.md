# Video Context

Local preprocessing of narrated screen recordings for AI coding agents.

Record a normal macOS screen recording with microphone narration, then give the
recording's path to Codex. The intended tool will provide timestamped transcripts
and visual evidence that the agent can inspect alongside a codebase.

## Status

Project scaffold only. Media processing, transcription, frame retrieval, and the
Codex skill are not implemented yet. No runtime dependencies or model weights
have been installed.

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

The proposal is not implemented. The transcription model and real-recording
acceptance remain to be evaluated; test seams must be confirmed before TDD begins.

## Development

The Python 3.12 baseline is retained from the template. Development dependencies
are locked in `uv.lock`. Run commands from this directory:

```bash
uv sync --locked
uv run main.py
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
```

The starter currently has no tests; pytest reports no tests collected (exit 5).
Tests will live under `tests/`, with source modules under `src/`, as configured by
the template. Local recordings and derived artifacts belong in the gitignored
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
