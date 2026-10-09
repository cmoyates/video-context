#!/usr/bin/env bash
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
skill_target="${CODEX_HOME:-$HOME/.codex}/skills/video-context"
package="$root[asr]"
export_args=(--project "$root" --locked --no-dev --no-emit-project --format requirements-txt)
if [[ $# -eq 1 && "$1" == "--visual-only" ]]; then
  package="$root"
elif [[ $# -ne 0 ]]; then
  echo "Usage: bash scripts/install.sh [--visual-only]" >&2
  exit 2
else
  export_args+=(--extra asr)
fi
if [[ -e "$skill_target" || -L "$skill_target" ]]; then
  if [[ ! -L "$skill_target" || "$(readlink "$skill_target")" != "$root/skills/video-context" ]]; then
    echo "Existing skill at $skill_target belongs to another installation; preserve it before continuing." >&2
    exit 1
  fi
fi
requirements="$(mktemp -t video-context-requirements)"
uv export "${export_args[@]}" --output-file "$requirements" >/dev/null
uv tool install --python 3.12 --force --refresh-package video-context \
  --constraints "$requirements" "$package"
mkdir -p "$(dirname "$skill_target")"
if [[ ! -L "$skill_target" ]]; then
  ln -s "$root/skills/video-context" "$skill_target"
fi
echo "Installed: $(uv tool dir --bin)/video-context"
echo "Skill: $skill_target"
echo "Locked dependency snapshot retained at $requirements"
