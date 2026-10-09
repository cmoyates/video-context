# Research and provenance

Researched 2026-10-09. This is an original Python policy and workflow informed by
primary sources, not copied TypeScript plugin code. Language/tool behavior below
is documented; choosing to prefer a particular contract or design is local policy.

## Reference project

Examined [dmmulroy/anti-slop at c44ef22](https://github.com/dmmulroy/anti-slop/tree/c44ef22ca116d0ba62a3ff663a0bd13a3f3fa40b):
its [rule descriptions](https://github.com/dmmulroy/anti-slop/blob/c44ef22ca116d0ba62a3ff663a0bd13a3f3fa40b/README.md)
and [installer skill](https://github.com/dmmulroy/anti-slop/blob/c44ef22ca116d0ba62a3ff663a0bd13a3f3fa40b/skills/install-anti-slop/SKILL.md).
It vendors opinionated Oxlint rules and preserves local customization during
updates. We retain the evidence-oriented review and additive installation
approach; the Python implementation uses existing tools rather than vendoring
an Oxlint equivalent.

| Upstream rule or family | Python adaptation | Coverage |
| --- | --- | --- |
| `no-array-filter-map` | Inspect eager intermediate containers; allow lazy Python pipelines | Collection lints plus review |
| `no-reduce-accumulator-copy`, companion accumulating-spread check | Avoid repeated copying of growing local accumulators | RUF017 for list summation; review other loops/reducers |
| `no-chained-type-assertions`, `no-widen-then-assert` | Restore real type evidence instead of laundering through casts | Type checker plus review |
| `require-safety-comment-for-type-assertion` | Explain a necessary cast's actual invariant | Review |
| `no-known-value-widening` | Preserve useful contracts without over-constraining consumers | Review |
| `no-object-parameters`, `no-unknown-parameters/returns/type-aliases` | Contain Any; allow intentional object boundaries and generic contracts | Annotation/type checks plus review |
| `no-unsafe-dictionary-type` | Distinguish known-field records from real dynamic dictionaries | Review plus missing type argument checks |
| `no-reflect-get`, `no-reflect-apply` | Prefer direct known-member access and typed calls | B009/B010 for selected access; review dispatch |
| `no-runtime-typeof` | Validate boundaries; retain Python narrowing operations | Deliberate departure; review |
| `no-conditional-empty-object-spread` | Preserve omission versus None; simplify only when clearer | Deliberate departure; review |
| `no-module-mocking` | Prefer observable behavior and real seams; permit scoped patches | Deliberate departure; review |
| `no-shape-in-symbol-names` | Use meaningful domain names; shape is valid vocabulary | Not ported as a lexical ban |
| `require-readable-spacing` | Use the established Python formatter | Formatter; no custom spacing engine |
| Five Effect-specific rules | No generic Python framework analogue | Not ported |

Python-specific additions cover exception/recovery semantics, mutable defaults,
late binding, resource ownership, and async cancellation.

## Primary sources and resulting decisions

- [Typing specification: special types](https://typing.python.org/en/latest/spec/special-types.html):
  Any permits unchecked assignments; omitted generic parameters introduce dynamic
  types. This motivates containing dynamic values, not universal bans on generic APIs.
- [Python 3.12 typing](https://docs.python.org/3.12/library/typing.html):
  annotations are not runtime enforcement; object and Any differ; TypedDict
  describes dictionaries statically. Prefer explicit boundary parsing where runtime
  guarantees matter. Protocols express structural contracts without inheritance.
- [Typing directives and cast](https://typing.python.org/en/latest/spec/directives.html#cast):
  cast leaves the runtime value untouched. Invariant comments are this skill's
  review policy, not a requirement of Python or a check performed by the templates.
- [Built-in functions](https://docs.python.org/3.12/library/functions.html):
  map and filter return iterators; getattr supports dynamic access and defaults.
  Literal translations of eager-array and reflection bans would create false positives.
- [itertools](https://docs.python.org/3.12/library/itertools.html#itertools.chain.from_iterable):
  chain.from_iterable provides lazy flattening. Changing materialization still
  requires review of consumption and evaluation timing.
- [Exception handling](https://docs.python.org/3.12/tutorial/errors.html):
  narrow try blocks avoid catching unrelated failures; explicit chaining records
  causes. Our rejection of invented fallback results is a contract-level policy.
- [contextlib](https://docs.python.org/3.12/library/contextlib.html):
  context managers manage cleanup and suppress deliberately selected exceptions.
  Suppression is not inherently wrong; the continuing state must be valid.
- [Asyncio tasks](https://docs.python.org/3.12/library/asyncio-task.html):
  TaskGroup owns task lifetimes and depends on cancellation; swallowed cancellation
  can break structured concurrency. Moving blocking work to a thread is not a
  guarantee of cancellation of that work.
- [unittest.mock](https://docs.python.org/3.12/library/unittest.mock.html#where-to-patch):
  patch where the name is looked up; autospec constrains signatures. Scoped mocks
  remain valid Python test tools. Favoring real seams is local design policy.
- [Ruff FAQ](https://docs.astral.sh/ruff/faq/#can-i-write-my-own-linter-plugins-for-ruff):
  third-party plugins are unsupported; Ruff complements a type checker. This
  skill does not claim a custom Ruff plugin or full semantic enforcement.
- [Ruff configuration](https://docs.astral.sh/ruff/configuration/):
  use extend-select for additive rules and inspect nested configuration and ignores.
  Standalone configuration files and pyproject tables use different prefixes.
- [Ruff rules](https://docs.astral.sh/ruff/rules/), checked against installed
  `ruff rule --all --output-format json`: the template selects stable explicit
  codes for annotations, common bug patterns, collection construction, and
  suppression hygiene. It avoids enabling all rules or a competing style preset.
- [ANN401](https://docs.astral.sh/ruff/rules/any-type/): covers annotated function
  arguments/returns, with alias limitations. It cannot establish freedom from Any.
- [RUF017](https://docs.astral.sh/ruff/rules/quadratic-list-summation/): detects
  quadratic list summation. General accumulator analysis remains manual.
- [RUF100](https://docs.astral.sh/ruff/rules/unused-noqa/): detects unused Ruff
  suppressions. An ignore that is technically used may still lack justification.
- [ty rules](https://docs.astral.sh/ty/reference/rules/): the template checks
  missing generic arguments, dynamic leakage through fully static return
  contracts, redundant casts, and blanket/unused ty ignores. These rules do not
  ban all casts or enforce runtime schemas.
- [ty migration guidance](https://docs.astral.sh/ty/coming-from-mypy-or-pyright/):
  type checking and annotation linting complement each other. The skill keeps
  an existing checker and avoids treating different tools' strict modes as identical.

## Search trail

Eight Firecrawl web searches covered typing/casts, Ruff rules, ty rules, async
cancellation, exceptions, mock seams, collection performance, and configuration.
Queries targeted `typing.python.org`, `docs.python.org`, and `docs.astral.sh`.
Read the primary pages above after discovery; rejected translated/older-version
duplicates and new Python syntax above this project's 3.12 baseline. Raw search
responses are local scratch data, not required to use the skill.

## Validation of this revision

On 2026-10-09, validated with this repository's Ruff 0.16.10 and ty 0.0.85:

- All 36 explicitly selected Ruff codes exist and are stable in the installed
  rule catalog; all five ty rule settings are accepted.
- Seventeen isolated fixtures passed: seven Ruff violations, four legitimate
  Python patterns, five ty violations, and one validated-return counterpart.
  Positive cases cover object/isinstance boundaries, lazy map/filter, shape
  vocabulary, and a scoped environment patch.
- Both Python examples in the rule guide passed the standalone Ruff and ty
  templates. Skill frontmatter validation and local reference/symlink checks passed.
- Existing repository lint, format, and type checks passed. Active project
  lint settings and dependencies were not changed by installing this skill.

These are configuration and example checks, not an independent agent-behavior
evaluation, exhaustive rule tests, or proof of the manual review judgments.

### Project activation

Later on 2026-10-09, the user requested activation. Merged the 36 Ruff selectors
and five ty error settings into `video-context/pyproject.toml`, preserving all
previous settings and dependency versions. Existing quality hooks already run
these tools with the project configuration, so no hook changes were needed.
Confirmed all selected Ruff codes in effective settings, an idempotent merge,
and all 17 fixtures against the active project configuration. Repository lint,
format, and type checks passed with the new policy. Manual review rules remain
agent guidance rather than automatic enforcement.
