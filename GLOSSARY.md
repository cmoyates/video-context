# Video Context

Video Context turns narrated screen recordings into evidence a coding agent can
revisit while investigating a requested change.

## Language

**Recording**: The original captured video, including any captured audio and
cursor pixels. It is the source of evidence about what was shown and heard.
_Avoid_: summary, transcript (when referring to the whole recording)

**Recording time**: A position on the recording's playback timeline, measured
from its beginning. It is distinct from the time of day the recording was made.

**Transcript**: Recognized speech with estimated recording-time intervals.
It is an interpretation of captured audio, not a verified statement of intent.

**Moment**: A bounded interval of recording time containing related speech and
visual evidence. A moment can contain either kind of evidence without the other.

**Frame**: A still image from the recording at an identified recording time.
The time requested for inspection can differ from the time of the returned frame.

**Overview**: A small selection of frames spanning the recording, used to orient
the agent. It does not claim to include every event.

**Evidence**: Speech or imagery traceable to a recording and moment, together
with any limitations on its availability or interpretation.

**Request**: A change the narrator asks for. Recognized speech alone does not
establish that a request came from the narrator rather than captured app playback.

**Observation**: A claim about what is visibly or audibly present in the evidence.
An observation is distinct from a request or a proposed explanation.

**Uncertainty**: A limitation that prevents a confident interpretation, such as
an unclear spoken word, an ambiguous gesture, or unavailable frames.
