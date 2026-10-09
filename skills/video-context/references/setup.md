# Setup

Requires Python 3.12+, uv, and ffmpeg/ffprobe on PATH. Local narration recognition
uses MLX on Apple Silicon. Visual-only operation needs no speech model.

From a Video Context checkout, run `bash scripts/install.sh`. It installs the
locked ASR dependencies as an isolated uv tool and links this skill into
`${CODEX_HOME:-$HOME/.codex}/skills/video-context`. Keep the checkout for that skill
link; the installed CLI itself is independent of the checkout and caller cwd.
Restart Codex or start a new chat if the installed skill is not yet discovered.

Run `video-context models fetch turbo` once to download the pinned default model.
Use `models fetch small` and `prepare --model small` for the smaller alternative.
Preparation never automatically downloads weights. For a visual-only installation,
run `bash scripts/install.sh --visual-only`.

Re-run the installer after updating the checkout. It refuses to replace an
unrelated existing skill. If needed, move that skill to recoverable Trash before
installing; do not overwrite it silently.
