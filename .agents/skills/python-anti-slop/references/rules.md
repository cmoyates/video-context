# Python review rules

Apply these to the requested scope. **Tool** names indicate partial mechanical
coverage; **Review** means the agent must establish the context. The
[source map](sources.md) separates documented language behavior from local policy.

## 1. Keep information in contracts

Use the narrowest truthful contract that expresses what the consumer needs:
specific return types, parameterized collections, `TypedDict` for known mapping
fields, a dataclass for a record with behavior or invariants, and `Protocol` for
a real structural dependency. Reuse existing models before creating another.

Flag `Any`, bare `dict`/`list`/`Callable`, or `dict[str, Any]` when they erase a
known contract and let unchecked operations spread. Trace untyped library values
through wrappers; a precise return annotation alone does not validate them.
Keep a genuinely extensible dictionary when its keys are data, not record fields.

Python's `object` is a safe broad type: arbitrary operations require narrowing.
It is appropriate for an external parser, an opaque container, a sentinel, or
`__eq__`. Do not replace `Any` mechanically with `object` and then cast it back.
Do not ban broad inputs that the function intentionally handles. An abstract
`Mapping` or `Sequence` can be a better consumer contract than a concrete class.

**Tool:** Ruff `ANN001/2/3`, `ANN201/2/4/5/6`, `ANN401`; ty
`missing-type-argument`, `unsound-return-statement`. `ANN401` is not a whole-program
Any detector; aliases and inferred dynamic values need additional inspection.
**Review:** schema choice, information loss, and intentional dynamic boundaries.

## 2. Establish facts instead of asserting types

`cast(T, value)` does not check or convert the value. Flag casts of decoded JSON
or third-party results that substitute for parsing, nested casts used to silence
incompatibility, and widen-then-cast flows. A `TypedDict` declaration, dataclass
annotation, or `NewType` call is not runtime validation either.

Prefer narrowing, an explicit parser, or the project's existing validation
library. A necessary cast should have a nearby invariant explanation identifying
the check or external guarantee the checker cannot express. A comment that just
says the value is safe supplies no evidence. Use rule-specific suppression with
the same justification for a genuine checker/stub limitation.

For example, when the contract requires a nonempty identifier:

```python
def parse_recording_id(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("recording_id must be a string")
    if not value.strip():
        raise ValueError("recording_id must be a nonempty string")
    return value
```

Keep `isinstance`, `is None`, and pattern matching where they establish actual
runtime facts. Validate nested fields, units, ranges, and missing/null semantics
that the boundary contract requires. Use `assert` for internal invariants, not
validation required under optimized Python. Preserve coercion policy: turning
`None` into `"None"`, missing counts into zero, or invalid records into `[]` can
silently change meaning. Test malformed and valid inputs at changed boundaries.

**Tool:** ty catches incompatible operations and redundant casts; neither the
templates nor the formatter enforces meaningful cast explanations.
**Review:** validation completeness, narrowing predicates, casts, and suppressions.

## 3. Call known capabilities directly

Use `obj.member` and ordinary typed calls when the member and operation are known.
Flag `getattr(obj, "known_method")(...)`, cascades of `hasattr`, and string-based
dispatch when they conceal a fixed interface or silently invent defaults.

Keep reflection for actual dynamic attribute names, plugin discovery, serializers,
and framework integration. A typed registry or small `Protocol` is useful when
it expresses an existing seam; avoid introducing one solely to eliminate a
legitimate dynamic operation. `getattr(obj, "x", default)` has different behavior
from `obj.x`; preserve absence behavior in any rewrite.

**Tool:** Ruff `B009/B010` cover some constant attribute access.
**Review:** dynamic dispatch contracts, default semantics, and interface design.

## 4. Preserve data and evaluation semantics when simplifying collections

Prefer a readable comprehension, generator, or loop with a fresh local
accumulator. Flag repeated copying of a growing list/dictionary, such as
`result = result + [item]`, `{**result, key: value}` in a loop, or
`reduce(lambda acc, batch: acc + batch, batches, [])`.

```python
def flatten(batches: list[list[int]]) -> list[int]:
    return [item for batch in batches for item in batch]
```

Python 3 `map` and `filter` are lazy. A pipeline is not automatically an eager
multi-pass defect. Materialization may provide reuse, a snapshot, or intentional
exception timing. Before fusing loops, check callback order, side effects,
one-shot iterators, truthiness filtering, and memory lifetime. Mutate only a
locally owned accumulator; retained snapshots or shared inputs change that choice.
For truly lazy flattening, consider `itertools.chain.from_iterable`.

Preserve absent versus explicit `None` keys. Conditional dictionary unpacking
can express omission correctly; an explicit `if` is often clearer but is not
required just to resemble the upstream rule. Do not filter all falsy values to
remove only missing values.

**Tool:** Ruff `RUF017` covers repeated list copying through `sum`;
`C400`-family rules cover selected redundant collection constructions.
**Review:** general quadratic accumulation, ownership, omission, and evaluation
order. Neither proves an algorithm's complexity or speed on a real workload.

## 5. Make failures observable and recovery specific

Catch expected exceptions around the smallest operation that can raise them.
Flag `except Exception: return None`, silent `pass`, log-and-success, and invented
fallback results when callers need to know an operation failed. Return a fallback
only when it is part of the contract. When translating an exception, preserve its
cause with `raise DomainError(...) from exc` unless intentionally hiding context
at an established public boundary.

Broad handling may be appropriate at a process/job boundary that records failure
and terminates, or during cleanup that re-raises. Logging alone does not prove
correct recovery. Explicit `contextlib.suppress(ExpectedError)` is appropriate
only if continuing after that particular failure is safe. Retries need a known
transient failure, a bound, and safe repeated effects; do not replay an uncertain
side effect automatically.

**Tool:** Ruff `E722`, `BLE001`, `B012`, `B904`. `BLE001` permits certain logged
or re-raised exceptions; it cannot prove that a logged fallback is valid.
**Review:** failure contracts, retry ownership, and recovery safety.

## 6. Respect Python lifetime and concurrency behavior

Use fresh mutable defaults and bind loop variables deliberately. Use context
managers or `finally` for resources whose lifetime spans failure paths. Keep
cleanup from overriding an earlier exception or return value.

In async code, await owned work, give background tasks an explicit owner, and
choose `TaskGroup` when sibling failure should cancel the group. `gather` has
different failure behavior; replacing it is a semantic change. Propagate
`CancelledError` after cleanup in ordinary tasks. Review blocking I/O and CPU work
on the event loop against the actual latency contract. Moving work to a thread
does not make it stop when its awaiting task is cancelled.

**Tool:** Ruff `B006/B008/B023/B012` and selected async rules if already enabled.
**Review:** resource ownership, cancellation, blocking behavior, and partial effects.

## 7. Test behavior through real seams

Prefer small real collaborators, temporary files, and fakes for actual external
boundaries. Flag tests that replace the function under test, merely repeat mock
return values, or patch many private helpers to reproduce an implementation.
Exercise the result or observable effect; add failure-path tests when behavior
changes. A mock-only test does not prove a real decoder, subprocess, or network
integration works.

Scoped `patch`/`monkeypatch` for environment, time, network, or legacy seams is
legitimate. Patch where the dependency is looked up, restore it afterward, and
use `autospec`/`spec_set` when useful to constrain mocks. Do not ban Python module
patching globally or refactor working code into an injection framework just to
avoid one focused patch.

**Review only:** test realism and appropriate seams. No template enforces this.

## 8. Keep structure proportional to present needs

Prefer domain names, cohesive functions, and existing project patterns. Flag a
one-use factory hierarchy, pass-through manager/service layers, compatibility
branches for unsupported versions, or unused configuration only when you can show
the cost and a simpler equivalent. A wrapper can earn its place through a stable
boundary, error translation, ownership, or a second real implementation.

Comments should preserve rationale, units, invariants, or external constraints.
Flag stale or misleading comments; leave useful public documentation intact.
Use the existing formatter for spacing. Names such as `shape` are legitimate in
Python scientific/media code and are not a blanket violation. Match the project's
framework rather than importing TypeScript Effect conventions.

**Tool:** existing Ruff/Pyflakes checks find some unused code; the formatter
handles layout. **Review:** necessity, naming, abstraction cost, and explanations.
