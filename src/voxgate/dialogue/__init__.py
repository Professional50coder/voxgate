"""Conversation logic shared by every interview surface.

Deliberately outside `voxgate.voice`. Both the voice worker and the browser
`/apply` flow ask the same questions and must escalate the same way when an
answer does not land, so the ladder lives where both can reach it — and
critically, where importing it does not drag in Pipecat.

That last part was a real break, caught before it shipped: the extract endpoint
imported `voxgate.voice.phrasing`, which executes `voxgate/voice/__init__.py`,
which imports Pipecat. The import was inside the handler so nothing failed at
start-up; the first applicant answer on a server without the heavy voice extra
would have been a 500.
"""

from voxgate.dialogue.phrasing import (
    acknowledge_refusal,
    concede,
    confirm_volunteered,
    explain,
    humanize,
    reask,
    spoken_options,
)

__all__ = [
    "acknowledge_refusal",
    "concede",
    "confirm_volunteered",
    "explain",
    "humanize",
    "reask",
    "spoken_options",
]
