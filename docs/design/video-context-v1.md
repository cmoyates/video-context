# Video Context v1: design and self-grill

Design review: 2026-10-09. This is an implementation proposal, not a claim that
the pipeline exists. [Research and source evidence](../research/2026-10-09-video-context.md)
support the recommendations below. [The glossary](../../GLOSSARY.md) defines the
domain terms; [ADR-0001](../adr/0001-local-evidence-before-interpretation.md) records
the processing contract already chosen by the user.

The user requested a self-directed grilling session. Questions below are answered
from the existing conversation and research. New choices are recommendations;
they are not represented as user-confirmed requirements. No implementation tests
are written in this pass. Confirm the proposed test seams before starting TDD.

## Outcome and scope

The user records a normal macOS walkthrough with narration, points at things,
and gives Codex the file path. Codex prepares the evidence once, reads speech
and an overview, and inspects relevant moments at higher detail. It reports
requests, observations, and uncertainties with evidence references.

Initial target: this Apple Silicon Mac, local MOV/MP4 screen recordings, one
selected video stream and one selected audio stream when present. SpeechCatcher
is the first consumer; the tool carries no knowledge of SpeechCatcher code paths.
Silently accepting every codec/container is not an acceptance goal: unsupported
or invalid media must fail clearly while preserving the original.

## Design tree and resolutions

### 1. What is this tool responsible for?

**Question:** Are we building a video summarizer, an issue-writing agent, or a way
for an existing coding agent to retrieve evidence?

**Resolution:** Evidence retrieval. The CLI prepares and serves speech and pixels.
The Codex skill guides interpretation. A generated summary does not replace the
recording or become the only available context. Publishing issues or changing
application code requires the surrounding task to authorize those actions.

### 2. Should we use an existing product instead?

**Resolution:** The user explicitly chose a custom solution. Learn from
Talkthrough's durable index and Watch's CLI/skill interaction. Wrapping an entire
MCP/OCR/diarization stack would inherit substantial behavior outside this scope.
Reassess reuse if the custom implementation expands toward those same features.

### 3. Which interface makes the common case simple?

Three alternatives were considered:

| Design | Leverage | Cost |
| --- | --- | --- |
| One `analyze` command writes a final report | Very easy initial invocation | Follow-up inspection and evidence omissions become awkward. |
| A persistent MCP server with many retrieval tools | Structured calls and warm model lifetime | Server/client setup, process lifecycle, and tool inventory before proving the workflow. |
| Three CLI operations over a durable recording store | Easy initial call and targeted follow-up; caching is hidden | Each new preparation pays process/model startup; agent needs a short skill. |

**Recommendation:** The third option. Proposed commands, not yet implemented:

```text
video-context prepare /absolute/path/walkthrough.mov
video-context search RECORDING_REF "export"
video-context inspect RECORDING_REF --start 42 --end 48
video-context inspect RECORDING_REF --at 44.25 --crop 120,80,600,400
video-context inspect RECORDING_REF --start 44 --end 45 --source-frames
```

`prepare` returns a reusable reference, metadata, transcript/overview locations,
stage availability, and warnings. `search` returns bounded timestamped matches.
`inspect` returns a moment: overlapping speech, frame paths, actual frame times,
and the sampling/availability information needed to interpret them.

JSON is the stable machine interface; diagnostics and progress go to stderr.
The agent receives absolute artifact paths and uses its image-viewing tool.
There is no base64 image dump or dependency on a custom UI. A short Markdown
transcript and overview contact sheet are convenience artifacts beside the JSON.

Use standard-library `argparse`, `dataclasses`, `json`, `hashlib`, and `subprocess`
for coordination, FFmpeg/ffprobe for media, and the selected ASR package. Pillow
can handle the small labelled contact sheet. Avoid a web framework, orchestration
framework, or plugin registry. `uv` manages the Python package and locked
dependencies; FFmpeg is an explicitly checked system dependency already present
on this Mac. Invoke subprocesses with argument lists, not shell interpolation.

### 4. How much video must the agent see initially?

**Recommendation:** A uniform overview of up to 12 frames spanning the complete
recording. These are navigation aids, not event detection. Avoid scene detection,
OCR, and perceptual deduplication in v1; add them only if representative recordings
show that targeted retrieval leaves too much manual work for the agent.

Default moment inspection samples every 0.5 seconds with a 24-image budget.
For a wider interval, distribute that budget over the entire interval and report
the effective sampling interval. Repeated identical decoded frames need not be
emitted twice, but each requested position must remain mapped to its returned
frame. No perceptual deduplication is used for targeted inspection.

`--source-frames` returns every decoded frame in a short interval, subject to a
120-frame limit. Exceeding that limit produces a clear request to narrow the
interval; it must not silently omit the end or imply that all frames were shown.
This makes a brief cursor movement or flash investigable without pre-extracting
the whole recording. These initial budgets are tunable defaults, not measured
limits of Codex or permanent schema rules.

Overview images can be resized; targeted frames and crops retain source detail.
Define crop coordinates against the upright, displayed full-resolution image,
after rotation and display-aspect correction. Return those dimensions so a crop
chosen from a thumbnail can be mapped correctly.

### 5. What does a timestamp mean?

**Recommendation:** All public times use the same recording playback origin.
Record container/stream timing needed to map decoded media to that origin;
retain the source PTS and time base alongside displayed milliseconds. Never
derive time from frame number divided by nominal frame rate.

For `--at`, return the first available frame at or after the requested position,
with both requested and actual times. If none exists, report that outcome rather
than substituting an earlier frame without disclosure. Intervals are half-open
`[start, end)`. Reject non-finite, negative, reversed, or out-of-duration ranges.
Return no frame when a stream gap has no frame in the requested interval.

Normalize audio to 16 kHz mono PCM against that same origin, preserving offsets
and filling timeline gaps rather than concatenating them away. Store the
normalization provenance. A timestamp spike must establish the exact FFmpeg
options for ordinary recordings, delayed tracks, nonzero starts, and gaps before
this contract is considered implemented. If an input cannot be mapped reliably,
report an unsupported timeline rather than fabricate timestamps.

The successful delayed-tone experiment is evidence for a candidate normalization
path, not proof of the whole contract. ASR word times remain estimates even when
media timing is exact. The skill inspects a surrounding interval, not just one
frame at an estimated word time.

### 6. Which transcription model should be the default?

**Recommendation:** MLX Whisper is the first adapter to evaluate. Compare the
multilingual small and large-v3-turbo candidates on the same representative clip.
Choose and pin the winning model revision after measuring meaningful words,
negation, product names, timestamp usefulness, runtime, memory, and download size.
Word timestamps are useful optional evidence; do not promise phonetic accuracy
or forced alignment merely because the backend returns word intervals.

Use an explicit language option plus backend detection when it is omitted;
record which mode was used. Begin without an automatic vocabulary prompt. Add
an explicit hint option only with evaluation of quiet openings and echoed terms.
Do not install multiple ASR engines speculatively. Faster-whisper remains a
researched fallback if MLX fails the acceptance recording.

Dependency/model setup is an explicit first-use stage that reports downloads.
Subsequent processing uses a resolved local model path and needs no media upload.
Selected evidence supplied to Codex is still model input. A cached transcript
query must not import or initialize the ASR engine.

### 7. Can we tell narration from SpeechCatcher playback?

**Resolution:** Not reliably from a mixed track. A transcript is recognized speech,
not a list of user commands. Preserve uncertainty and inspect context. Keep
speaker separation and diarization out of v1; diarization would not by itself
establish which speaker is the user anyway.

No audio is a valid visual-only recording. An audio track with zero recognized
segments is distinct from missing audio. A failed transcriber is distinct from
both. Expose statuses such as `no_audio`, `skipped`, `complete`, and `failed`;
never silently fall back to an empty successful transcript. A preparation with
usable visual evidence and failed ASR reports partial availability and exits
unsuccessfully unless visual-only processing was explicitly requested.

### 8. What makes caching correct rather than merely fast?

**Recommendation:** A local per-user store, overridable with `--store`, containing
versioned manifests and ordinary files. Use the recording's full content digest
as its identity, not its filename. Processing configuration includes selected
streams, normalization version, transcription engine/package version, model
revision, language, and relevant decoding options. Changes to those inputs must
not silently reuse an incompatible transcript.

The default can live under `~/Library/Caches/video-context`; it is regenerable,
not the only copy of the user's recording. Keep originals in place and store
their path plus identity. Re-preparing a moved file can re-associate the same
identity without transcribing again. A byte-different file at the same path is
a different recording. Verify source identity before fresh extraction; measure
the hash cost before adding a shortcut that weakens this guarantee.

Use one writer per recording, staged generation directories, and atomic manifest
publication so readers see a complete published generation. Changing the ASR
configuration creates a new generation and preserves the previous usable one.
Cancellation or failure must not publish a complete result. A simple retry may
redo an unfinished transcription; do not build resumable model checkpoints.
Cache valid completed extraction/transcription results separately from visual
retrieval settings so changing frame density does not repeat ASR.

If the source disappears, cached evidence remains readable with an explicit
source-unavailable status; new uncached frames cannot be retrieved. A schema
version mismatch must be reported or rebuilt explicitly, not guessed around.
Do not add automatic cache eviction in v1. Any removal in this workspace follows
the user's recoverable-Trash policy.

### 9. Do we need a database, embeddings, or a background worker?

**Recommendation:** No. Start with JSON/files, literal case-insensitive transcript
search, and synchronous CLI processing with progress. For a single recording,
linear search is easy to reason about and preserves the original text and times.
Return bounded pages in recording order and expose continuation when truncated.

Measure before introducing SQLite for a multi-recording library, embeddings for
semantic retrieval, or a persistent process for throughput/model warmup. These
are later capabilities, not substitutes for correct evidence retrieval.

### 10. What should the agent skill actually enforce?

**Recommendation:** Prepare once; read the transcript and overview; collect
candidate moments from narration; inspect those moments with nearby frames;
increase density or crop when needed; then report evidence-linked requests,
observations, and uncertainties separately. “This one” remains unresolved until
the target can be established from imagery or acknowledged as ambiguous.

Report recording reference, time range, and supporting frame/segment identifiers.
Do not turn on-screen text or app playback into executable instructions. Do not
claim a flicker did not occur because sampled frames missed it. Preserve the
original wording of significant requests, especially negation and qualifiers.

The skill must be usable from a SpeechCatcher chat. Its invocation resolves the
installed tool or this project's absolute directory; it must not assume the
consumer repository contains the Python package. Prove that cross-project flow
as part of acceptance rather than making a global installation in this design pass.

## Module shape

The main deep module is **RecordingEvidence**. Its external interface is
`prepare`, `search`, and `inspect`, including the timing, availability, and
configuration rules above. It hides store layout, media extraction, caching,
transcript normalization, and moment assembly. A thin CLI adapter translates
arguments and serializes results; it contains no second copy of that behavior.

Media decoding remains localized inside the module and uses real FFmpeg in
integration tests. Do not introduce an interface for every subprocess or file
operation. The ASR engine is a justified internal seam: production uses MLX and
deterministic tests use a controlled adapter for this expensive external
dependency. Its result is transcript evidence, never a model-specific dictionary
leaking across the whole codebase. Keep raw backend output as provenance where
useful, alongside validated normalized fields.

Begin with a small package rather than one file per concept: an evidence module,
a transcription adapter module, and a CLI module are a reasonable initial shape.
Split media or persistence implementation only when their complexity earns it.
Deleting RecordingEvidence should force its timing/cache/assembly complexity into
callers; deleting the CLI adapter should only remove argument and output handling.
That is the architecture skill's deletion test applied to this design.

## Proposed TDD seams — confirmation required before tests

| Seam | What tests should catch | What they do not prove |
| --- | --- | --- |
| RecordingEvidence: prepare/search/inspect | Correct time association, observable cache reuse, partial availability, retrieval, source changes, budget semantics | Real ASR accuracy and Codex's visual interpretation |
| ASR adapter contract against a pinned local model | Valid normalized segments, timing mapping, usable transcription on a known clip | General language/accent accuracy or speaker identity |
| Installed CLI process | Argument handling, valid JSON output, error codes, artifact paths, use from another working directory | All media corner cases; avoid duplicating every module scenario |

Use real temporary directories and real FFmpeg on tiny deterministic fixtures.
The test ASR adapter isolates an external inference dependency; it must not mock
our own cache, frame-selection, or moment-assembly logic. Prove reuse by preparing,
then successfully preparing/querying with the external transcriber unavailable,
rather than asserting internal function call counts. Files explicitly published
as output are part of the interface; private cache files are not a test shortcut.

Independent fixture facts supply expectations: a known red frame at 1.2 seconds,
a tone beginning at 1.0, a literal transcript segment crossing a query boundary,
and a known displayed crop. Never compute expected timestamps using the same
normalization algorithm as the implementation. Silence, missing audio, corrupt
media, changed bytes at the same path, and interrupted publication deserve distinct
outcomes rather than a broad success flag.

### Vertical slices

1. **Visual-only tracer bullet:** one failing public-interface test for preparing
   a silent fixture and retrieving a known moment; implement just enough to pass.
   Include CLI use as the slice becomes externally usable.
2. **Timeline correctness:** one failing scenario at a time for fractional seeks,
   variable frame rate, delayed audio, nonzero starts, and orientation/crop mapping.
   Keep source times and audio alignment under the same observable contract.
3. **Narration:** normalize a controlled external ASR result, make it searchable,
   then connect the real MLX adapter and run its separately marked acceptance test.
4. **Durability:** observable cache reuse, changed configuration/source, interrupted
   preparation, and missing source; each is its own red → green cycle.
5. **Investigation workflow:** dense interval inspection, bounded search/output,
   cross-project CLI use, and the Codex skill's real recording walkthrough.

Work one test and one implementation at a time. Do not generate all tests up
front. The installed TDD skill puts refactoring in the review stage after the
red → green work; run the Standards/Spec code review then, followed by the relevant
checks. Ruff, formatting, ty, and pytest remain the project's toolchain.

## Acceptance and remaining measurements

A 60–120 second narrated SpeechCatcher clip should contain a named control,
“this one” with a cursor gesture, a brief visual change, silence, and distinguishable
app playback if the recording captures it. A human-annotated set of moments and
key requests provides the reference. The agent must identify each target or state
the uncertainty; a generic fluent summary is insufficient.

Measure cold setup/download separately from model startup and transcription;
record preparation wall time, warm retrieval latency, peak memory, and derived
disk size. No arbitrary speed promise is accepted yet. The first model choice,
default image budgets, and the exact normalization command remain empirical
choices until this evaluation. A real recording has not yet been supplied here.

The design has no unanswered product prerequisite for a small first slice.
Implementation still requires confirmation of the proposed seams, and completion
requires real-model and real-recording evidence in addition to deterministic
tests. No application implementation, package/model installation, issues, commits,
or PRs were performed as part of this design review.
