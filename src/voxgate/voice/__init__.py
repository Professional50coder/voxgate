"""Voice interviews over Pipecat.

`InterviewProcessor` is importable without the voice extra installed; it depends
only on Pipecat's frame types. Everything that touches Whisper, Kokoro or a
transport lives in `pipeline`, whose imports are deferred so that a service or
a test importing this package does not pull in torch.

    from voxgate.voice import InterviewProcessor          # cheap
    from voxgate.voice.pipeline import run_interview      # needs the voice extra
"""

from voxgate.voice.interview import (
    MAX_ATTEMPTS_PER_FIELD,
    MIN_CONFIDENCE,
    InterviewProcessor,
    InterviewState,
)

__all__ = [
    "InterviewProcessor",
    "InterviewState",
    "MAX_ATTEMPTS_PER_FIELD",
    "MIN_CONFIDENCE",
]
