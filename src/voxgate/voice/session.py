"""Connect a voice interview to a real case.

`InterviewProcessor` deliberately knows nothing about packs, HTTP, or the LLM.
This module is where it meets them: it reads the questions from the pack, wires
extraction to the shared Groq client, and submits the finished answers back to
the API so the graph resumes and does the actual screening.

Talking to the service over HTTP rather than importing `CaseRunner` is the point
of the split. The voice worker is a separate process — it holds Whisper and
Kokoro in memory and would otherwise force every API worker to carry them — so
it uses the same public endpoints an applicant's browser does. That also means
the voice path cannot develop its own private way of advancing a case.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


class VoxGateClient:
    """The few API calls a voice session makes.

    Written against urllib rather than adding an HTTP client dependency: it is
    four requests, and the voice extra is already the heaviest install in the
    project.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8000", api_key: str | None = None):
        self.base = base_url.rstrip("/")
        self.api_key = api_key

    def _call(self, path: str, body: dict | None = None, method: str | None = None):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        request = urllib.request.Request(
            f"{self.base}{path}",
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
            method=method or ("POST" if body is not None else "GET"),
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    def get_pack(self, pack_id: str) -> dict:
        for pack in self._call("/packs"):
            if pack["pack_id"] == pack_id:
                return pack
        raise KeyError(f"unknown pack: {pack_id}")

    def get_case(self, case_id: str) -> dict:
        return self._call(f"/cases/{case_id}")

    def open_case(self, pack_id: str) -> dict:
        return self._call("/cases", {"pack_id": pack_id})

    def extract(self, pack_id: str, field: str, spoken: str) -> tuple[str | None, float]:
        """Map a spoken answer onto the value this pack's schema requires.

        Uses the service's own extractor rather than calling an LLM here, so the
        voice path and the browser path cannot disagree about what an answer
        means — and the allowed values come from the pack either way.
        """
        result = self._call(
            f"/packs/{pack_id}/extract", {"field": field, "spoken": spoken[:4000]}
        )
        return result.get("value"), float(result.get("confidence") or 0.0)

    def submit(self, case_id: str, fields: dict, confidence: dict) -> dict:
        return self._call(
            f"/cases/{case_id}/interview-result",
            {"fields": fields, "confidence": confidence},
        )

    def push_live_fields(self, case_id: str, fields: dict, confidence: dict) -> None:
        """Best-effort: makes answers appear on the reviewer's board as they are
        given. Never allowed to interrupt the interview, because a console that
        is a few seconds stale is not a reason to stop talking to someone."""
        try:
            self._call(
                f"/cases/{case_id}/fields",
                {"fields": fields, "confidence": confidence},
                method="PATCH",
            )
        except (urllib.error.URLError, OSError):
            logger.warning("live field push failed for %s", case_id, exc_info=True)


def build_interview(client: VoxGateClient, case_id: str, *, greeting: str | None = None):
    """An `InterviewProcessor` bound to a live case.

    Questions come from the pack's own `reask_hints`, so the wording an
    applicant hears is the wording the pack defines — not a paraphrase invented
    at runtime, which for a regulated question is a compliance problem rather
    than a style one.
    """
    import asyncio

    from voxgate.voice.interview import InterviewProcessor

    case = client.get_case(case_id)
    pack = client.get_pack(case["pack_id"])

    # The interrupt names the fields still outstanding when the case is
    # mid-interview; a fresh case has none, so fall back to the full schema.
    interrupt = case.get("interrupt") or {}
    field_names = interrupt.get("reask_fields") or pack["fields"]
    questions = {**(pack.get("reask_hints") or {}), **(interrupt.get("reask_hints") or {})}

    async def extract(field: str, spoken: str):
        # to_thread: the client is blocking, and blocking the event loop here
        # stalls audio for every other session this worker is carrying.
        return await asyncio.to_thread(client.extract, case["pack_id"], field, spoken)

    async def on_complete(fields: dict, confidence: dict):
        await asyncio.to_thread(client.submit, case_id, fields, confidence)
        logger.info("interview submitted for case %s (%d fields)", case_id, len(fields))

    # The pack's allowed values per field, so a re-ask can read the options
    # instead of repeating the question. This is the single largest improvement
    # available and it needs no model: the system already had this list.
    options = {}
    for name in field_names:
        values = (pack.get("field_values") or {}).get(name)
        if values:
            options[name] = list(values)

    async def classify_model(spoken: str, question: str):
        from voxgate.ml.understanding import classify_with_model

        return await asyncio.to_thread(classify_with_model, spoken, question)

    from voxgate.packs.agent import AgentProfile
    from voxgate.transcripts import TranscriptRecorder

    # The pack's own agent: its greeting, house rules and process answers.
    agent = AgentProfile.model_validate(pack.get("agent") or {})

    return InterviewProcessor(
        field_names=list(field_names),
        questions=questions,
        extract=extract,
        on_complete=on_complete,
        greeting=greeting or agent.greeting,
        options=options,
        classify_model=classify_model,
        agent=agent,
        recorder=TranscriptRecorder(case_id),
    )
