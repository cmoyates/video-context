# Install or update checks

This skill supplies additive Ruff and ty templates, plus agent-review rules.
Ruff has no third-party plugin interface; do not claim these files install a
custom analyzer or enforce every rule in [rules.md](rules.md).

## Inspect the target

Establish whether the request is fresh installation, reconfiguration, or update.
Read repository instructions and `git status`; locate the effective Ruff config
(`ruff.toml`, `.ruff.toml`, or `pyproject.toml`), nested configs and `extend`
relationships, per-file ignores, CI commands, Python target, dependency groups,
lockfile, and existing type checker. Record the baseline check results before
changing policy. Respect intentionally excluded files.

Use installed rule documentation (`ruff rule CODE`) and checker help to verify
support. The templates were exercised with Ruff 0.16.10 and ty 0.0.85, not every
older release. If a selected rule is unavailable, report the gap and determine
whether an upgrade is within the request. Do not silently drop checks, enable
preview rules, replace tools, or upgrade unrelated dependencies.

## Merge the policy

1. Merge [the Ruff rule list](../assets/ruff.toml) into `lint.extend-select` in
   the effective Ruff file, or `tool.ruff.lint.extend-select` in `pyproject.toml`.
   Union existing entries without duplication. Preserve `select`, `ignore`,
   `per-file-ignores`, formatter settings, target version, and config inheritance.
   Show existing ignores that defeat requested rules; preserve intentional policy
   until the user has authorized changing it. An install request authorizes normal
   compatible additions, not removal of documented exceptions.
2. For an existing ty project, merge [the ty rules](../assets/ty.toml) into
   `[rules]` in `ty.toml` or `[tool.ty.rules]` in `pyproject.toml`. Preserve
   overrides and explicit severities; report conflicts. For mypy or Pyright,
   keep that checker and verify its equivalent diagnostics in its installed
   documentation. Do not paste ty options into it or claim perfect parity.
   If there is no checker, select one consistent with repository guidance and
   the user's installation scope; Ruff alone cannot check types.
3. If a needed tool is absent, add it to the existing development dependency
   group with the repository's package manager and lockfile workflow. Existing
   compatible installations need no dependency change. These templates have no
   coupled Ruff/ty version requirement and need no validation framework dependency.
4. Integrate checks into the existing lint/check entry point when installation
   includes enforcement. Preserve meaningful CI exit codes. Do not create a
   second competing CI pipeline or suppress a whole directory to get a green run.

The templates are merge inputs, not drop-in replacements. Passing
`ruff --config <template>` selects that file instead of the repository's normal
configuration. Use it only for isolated template verification. Likewise,
`ty --config-file` selects a standalone ty configuration.

## Validate the result

Use the repository's runner; for a uv project the usual commands are:

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check
```

Inspect Ruff's `check --show-settings path/to/owned_file.py` for representative
files, including nested-config and test paths where relevant. Check that added
rules actually apply, not merely that TOML parses. Verify changed checker rules
with a tiny failing fixture in an isolated scratch directory; confirm the expected
diagnostic and a valid counterpart. Keep such fixtures out of application source.

Report existing violations separately from new regressions. Install-only work
does not imply a repository-wide cleanup. When fixes are authorized, review tool
fixes for behavior and comment loss, use the normal formatter, then rerun checks.
Do not use blanket suppressions, `--exit-zero`, `--add-ignore`, or unsafe fixes
as a substitute for resolving a finding. After formatting/fixing, a second pass
must leave the affected files unchanged. Run behavior tests for semantic edits;
report unavailable tests or no tests collected accurately.

## Update without overwriting local policy

Read the installed skill and any provenance/customization notes before updating.
Stage incoming content separately. Compare old and new rules and templates with
the effective local configuration. When a pristine previous version exists, use
a three-way comparison; otherwise port selected changes conservatively. Preserve
local additions, exceptions, and framework decisions. A new upstream rule is a
policy proposal to evaluate, not automatic authority to rewrite project code.

Record the actual source identity, selected rules, tool versions, intentional
deviations, and validation results in the repository's established tooling notes
(or a small provenance note beside a separately stored policy). The upstream
TypeScript commit in [sources.md](sources.md) identifies inspiration, not Python
plugin assets. This Python skill is locally maintained and has no published
upstream update feed. Do not invent one or replace it with the TypeScript installer.

Complete when the diff preserves unrelated configuration, repeated merging adds
no duplicates, effective checks have run, and every remaining failure or
unenforced review rule is disclosed.
