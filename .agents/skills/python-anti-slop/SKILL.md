---
name: python-anti-slop
description: Review or clean up low-evidence Python code, or install and update an anti-slop lint policy using Ruff and the existing type checker. Use for Python anti-slop requests, unjustified casts or Any, swallowed failures, and speculative abstractions.
---

# Python anti-slop

Keep contracts specific, validate external data where it enters, and require
evidence for complexity. This is a local, opinionated Python adaptation inspired
by [dmmulroy/anti-slop](https://github.com/dmmulroy/anti-slop), not an official
port or a custom Ruff plugin. Ruff checks syntax; the type checker checks typed
contracts; agent review covers intent and runtime guarantees.

## Establish the operation

Read repository instructions, `git status`, the requested diff or paths, Python
version constraints, and the effective lint/type-check configuration. Inspect
nearby callers and tests before judging a suspicious pattern. Preserve existing
work and the project's formatter, package manager, and type checker.

- **Review:** read [rules.md](references/rules.md), inspect the scoped code, and
  report findings without edits. Follow its exceptions as well as its defaults.
- **Implement or clean up:** apply those same rules to the authorized change.
  Preserve signatures, failure semantics, ordering, mutation ownership, and
  data representation unless the requested behavior requires a change.
- **Install, configure, or update checks:** read
  [configure.md](references/configure.md). Adding this skill alone installs
  guidance; enabling its configuration templates is a separate operation.

When invoked without a target, use the current working diff. If there is no diff
or identifiable target, ask for the target rather than auditing the entire repo.

## Evidence before a finding

For each candidate, identify the lost guarantee or concrete unnecessary work,
trace where the value or dependency originates, and check whether the pattern is
a deliberate boundary or repository convention. A name, cast, mock, or broad
annotation by itself is a lead, not proof of a defect.

Prefer a local simplification that restores the contract. New generic frameworks,
validation dependencies, interfaces, and fallback behavior need a present use
case. Match the supported Python version; newer syntax is not a cleanup goal.

Use configured tools to confirm mechanical findings. Treat successful lint/type
checks as partial evidence: they do not establish runtime validation, cancellation
correctness, test realism, or absence of unnecessary abstractions. Consult
[sources.md](references/sources.md) when a rule's rationale, Python exception,
upstream mapping, or tool coverage is disputed.

## Finish

For a review, report actionable findings first: file and line, violated rule,
concrete consequence, and smallest useful correction. Separate confirmed defects
from policy suggestions. Say when no actionable findings remain; do not fill a
quota or infer who authored the code.

For edits, run the existing focused lint/type checks and behavior tests warranted
by the change. Report changed paths, checks and their results, and unresolved
coverage. For configuration changes, also verify effective rules and repeatability
as described in the configuration reference. Never weaken checks or fabricate
validation merely to make a command pass.
