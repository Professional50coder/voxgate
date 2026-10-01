"""Render the website's sample calls to static MP3s, one file per turn.

    uv run python scripts/generate_sample_calls.py

Writes apps/web/public/samples/<pack>/<nn>.mp3 and apps/web/public/samples/
calls.json (the transcript the page plays along with). Run once and commit
the output: the site then plays these with no API, no key and no cost.

Agent lines are what the platform actually says in each situation (the pack's
questions and dialogue/phrasing.py), so a sample never promises behaviour the
product does not have. Callers are fictional and use a different voice from
the agent so the two are easy to tell apart.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from voxgate.config import get_settings
from voxgate.dialogue import phrasing
from voxgate.packs.agent import VoiceProfile
from voxgate.packs.loader import load_packs
from voxgate.tts import TTSUnavailable, synthesize

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "apps" / "web" / "public" / "samples"

# Caller voices (Cartesia sonic-3): distinct from every agent voice.
DECLAN = "ca6e2abc-f3e6-4f62-9625-92fada58eb9b"   # male, clear
MAX = "3945925b-9143-4b7d-9ab5-cc4878001106"      # male, warm
SOFIA = "9f14cf59-e7e2-4783-b733-dbae49640789"    # female, patient
RICARDO = "8499aae3-022c-4d55-8283-0c2e8adbefb4"  # male, calm


def calls(packs) -> list[dict]:
    kyc, pat, sales, rec = (packs[k] for k in
                            ("kyc-uae", "patient-intake", "sales-discovery", "recruit-screen"))
    q = lambda p, f: p.reask_hints[f]  # noqa: E731 - the pack's own wording
    return [
        {
            "pack": "kyc-uae", "title": "Banking KYC", "caller_voice": DECLAN,
            "shows": "A card number refused, then a correction",
            "turns": [
                ("agent", kyc.agent.greeting + " " + q(kyc, "full_name")),
                ("caller", "Sure. It's Omar Haddad, O-M-A-R, H-A-D-D-A-D."),
                ("agent", "Thank you. " + q(kyc, "dob")),
                ("caller", "Twelfth of June 1991. Do you need my card number to link the account?"),
                ("agent", phrasing.refuse_sensitive(q(kyc, "nationality"))),
                ("caller", "Got it. Jordan. Actually no, sorry, my passport is Emirati now."),
                ("agent", "Of course, let us go back. " + q(kyc, "nationality")),
                ("caller", "Emirati."),
            ],
        },
        {
            "pack": "patient-intake", "title": "Patient intake", "caller_voice": SOFIA,
            "shows": "A process question answered, then back on track",
            "turns": [
                ("agent", pat.agent.greeting + " " + q(pat, "full_name")),
                ("caller", "Hi, it's Priya Nair."),
                ("agent", "Thank you. " + q(pat, "primary_symptom")),
                ("caller", "Before that, who actually sees what I tell you?"),
                ("agent", phrasing.process_answer("privacy", q(pat, "primary_symptom"),
                                                  pat.agent.process_answers)),
                ("caller", "Okay. A sharp pain in my lower back, mostly in the mornings."),
                ("agent", "Thank you. " + q(pat, "duration")),
                ("caller", "About three weeks now."),
            ],
        },
        {
            "pack": "sales-discovery", "title": "Sales discovery", "caller_voice": MAX,
            "shows": "Small talk, then an off-limits topic declined",
            "turns": [
                ("agent", sales.agent.greeting + " " + q(sales, "company_name")),
                ("caller", "Hey Skylar, nice to talk to you!"),
                ("agent", phrasing.smalltalk(q(sales, "company_name"), 0, sales.agent.max_smalltalk)),
                ("caller", "Northwind Logistics. Any chance of a discount code?"),
                ("agent", phrasing.redirect(q(sales, "team_size"), 1)),
                ("caller", "Fair enough. About forty people on the ops team."),
                ("agent", "Thank you. " + q(sales, "primary_pain")),
                ("caller", "Our onboarding calls take forever and nothing is written down."),
            ],
        },
        {
            "pack": "recruit-screen", "title": "Recruiting screen", "caller_voice": RICARDO,
            "shows": "A vague answer, then a helpful re-ask",
            "turns": [
                ("agent", rec.agent.greeting + " " + q(rec, "full_name")),
                ("caller", "Daniel Okafor."),
                ("agent", "Thank you. " + q(rec, "years_experience")),
                ("caller", "Hmm, I'm not sure how you'd count it."),
                ("agent", phrasing.reask(question=q(rec, "years_experience"), attempt=1)),
                ("caller", "Okay, six years, mostly in operations."),
                ("agent", "Thank you. " + q(rec, "notice_period")),
                ("caller", "One month."),
            ],
        },
    ]


def main() -> int:
    settings = get_settings()
    if not settings.cartesia_api_key:
        print("CARTESIA_API_KEY is not set; nothing to render.")
        return 1
    packs = load_packs(settings.packs_dir, strict=True)
    manifest = []
    for call in calls(packs):
        agent = packs[call["pack"]].agent
        folder = OUT / call["pack"]
        folder.mkdir(parents=True, exist_ok=True)
        turns = []
        for i, (role, text) in enumerate(call["turns"]):
            voice = agent.voice if role == "agent" else VoiceProfile(
                primary=call["caller_voice"], fallback=None, speed=1.0)
            try:
                speech = synthesize(text, voice, settings, timeout=30)
            except TTSUnavailable as exc:
                print(f"failed {call['pack']} turn {i}: {exc}")
                return 1
            name = f"{i:02d}.mp3"
            (folder / name).write_bytes(speech.audio)
            turns.append({"role": role, "text": text, "audio": f"/samples/{call['pack']}/{name}"})
            print(f"{call['pack']:16} {i:02d} {role:6} {len(speech.audio) // 1024:4d} KB")
        manifest.append({"pack": call["pack"], "title": call["title"], "agent": agent.name,
                         "shows": call["shows"], "turns": turns})
    (OUT / "calls.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                                    encoding="utf-8")
    print(f"wrote {OUT / 'calls.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
