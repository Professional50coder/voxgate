"""Generate real, loadable scenario packs from compact declarative specs.

Every agent in the library is a pack, and a pack is five files on disk that the
existing loader reads with no platform changes. This script is the authoring
tool: it turns a spec into those five files.

The generated code is deliberately plain and readable rather than clever. These
files are shown to users in the library page and are meant to be edited by hand
afterwards, so they must look like code a person would write.

Run:  uv run python scripts/generate_packs.py
It is idempotent: re-running overwrites the generated packs and leaves any pack
not named in SPECS (notably kyc_uae, which is hand-written) untouched.

This file owns the SPECS only. The emitters live in `voxgate.packs.emit` and are
imported, so this and the publish endpoint genuinely share one implementation.
They did not always: this script carried a full second copy, and when the
emitters were hardened against injection the copy kept the vulnerable version —
so a pack built here and a pack built through the API were neither identical nor
equally safe, while a docstring claimed both.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PACKS = REPO / "packs"

# Run as a script (`uv run python scripts/generate_packs.py`), so the package is
# not importable without this.
sys.path.insert(0, str(REPO / "src"))

from voxgate.packs.emit import write_pack  # noqa: E402


# --------------------------------------------------------------------------
# Spec vocabulary
#
#   text  field: free text. Optional min_words guard.
#   enum  field: fixed choices, each carrying a 0..1 risk weight used by both
#                the scorecard and the keyword checks.
#   date  field: ISO date, optionally bounded by a plausible age range.
#   number field: numeric, with a range that maps onto a 0..1 risk ramp.
#
#   Checks are keyword screens over a named field. Each flag maps a phrase to a
#   band, so a check is honest about what it looked for and what it found.
# --------------------------------------------------------------------------

SPECS: list[dict] = [
    {
        "pack_id": "sales-discovery",
        "display_name": "B2B Sales Discovery Call",
        "gate_role": "Sales Manager",
        "persona": (
            "You are a B2B discovery interviewer. You are curious and concise, you never "
            "pitch, and you never promise pricing. Your job is to understand the "
            "prospect's problem, budget reality and buying timeline well enough that a "
            "human seller can decide whether to spend an hour on this."
        ),
        "gate_reason": "deals that look large, urgent or unqualified",
        "thresholds": {"low": 0.30, "high": 0.65},
        "bias": -2.4,
        "fields": [
            {"name": "company_name", "type": "text", "min_words": 1,
             "question": "Which company are you calling from?"},
            {"name": "team_size", "type": "enum", "weight": 1.1,
             "question": "Roughly how many people are in the team that would use this?",
             "values": {"1_10": 0.2, "11_50": 0.4, "51_250": 0.7, "over_250": 1.0},
             "synonyms": {"1_10": ["under ten", "less than ten", "small", "a few", "handful"],
                          "11_50": ["twenty", "thirty", "forty", "fifty"],
                          "51_250": ["hundred", "two hundred"],
                          "over_250": ["thousand", "large", "enterprise", "huge"]}},
            {"name": "current_tooling", "type": "text", "min_words": 1,
             "question": "What are you using for this today?"},
            {"name": "primary_pain", "type": "text", "min_words": 2,
             "question": "What is the single biggest problem you are trying to solve?"},
            {"name": "budget_band", "type": "enum", "weight": 1.6,
             "question": "Is there a budget already set aside for this, and roughly what range?",
             "values": {"none": 1.0, "under_10k": 0.6, "10k_50k": 0.3, "over_50k": 0.1},
             "synonyms": {"none": ["no budget", "nothing", "not yet", "unfunded"],
                          "under_10k": ["five thousand", "small budget", "a few thousand"],
                          "10k_50k": ["twenty thousand", "thirty thousand", "forty"],
                          "over_50k": ["hundred thousand", "large budget", "six figures"]}},
            {"name": "timeline", "type": "enum", "weight": 1.4,
             "question": "When would you want this working by?",
             "values": {"this_month": 0.9, "this_quarter": 0.5, "this_year": 0.3, "no_date": 1.0},
             "synonyms": {"this_month": ["immediately", "asap", "urgent", "weeks"],
                          "this_quarter": ["quarter", "three months"],
                          "this_year": ["year", "next year", "eventually"],
                          "no_date": ["no date", "unsure", "exploring", "just looking"]}},
            {"name": "decision_role", "type": "enum", "weight": 1.3,
             "question": "Would you be the one signing this off, or would someone else?",
             "values": {"decision_maker": 0.1, "influencer": 0.5, "researcher": 1.0},
             "synonyms": {"decision_maker": ["i decide", "my call", "i sign", "owner", "founder"],
                          "influencer": ["recommend", "input", "part of"],
                          "researcher": ["just researching", "looking around", "gathering"]}},
        ],
        "checks": [
            {"name": "competitor_mention", "field": "current_tooling",
             "flags": {"hit": ["salesforce", "hubspot", "outreach", "gong"],
                       "review": ["spreadsheet", "excel", "manual", "nothing"]}},
            {"name": "urgency_signal", "field": "primary_pain",
             "flags": {"hit": ["losing", "churn", "audit", "fine", "deadline", "regulator"],
                       "review": ["slow", "manual", "expensive", "error"]}},
        ],
    },
    {
        "pack_id": "realestate-lead",
        "display_name": "Real Estate Buyer Qualification",
        "gate_role": "Listing Agent",
        "persona": (
            "You are a property enquiry interviewer. You are warm, efficient and never "
            "give valuations or legal advice. You establish what the caller is looking "
            "for, whether their financing is real, and how soon they can move."
        ),
        "gate_reason": "buyers who are unfinanced, unusually urgent, or far outside the listing brief",
        "thresholds": {"low": 0.32, "high": 0.68},
        "bias": -2.2,
        "fields": [
            {"name": "full_name", "type": "text", "min_words": 2,
             "question": "Could I take your full name, please?"},
            {"name": "property_type", "type": "enum", "weight": 0.7,
             "question": "What kind of property are you looking for?",
             "values": {"apartment": 0.2, "villa": 0.3, "townhouse": 0.3, "commercial": 0.7},
             "synonyms": {"apartment": ["flat", "condo", "studio"],
                          "villa": ["house", "detached", "bungalow"],
                          "townhouse": ["terrace", "row house"],
                          "commercial": ["office", "retail", "shop", "warehouse"]}},
            {"name": "budget_band", "type": "enum", "weight": 1.5,
             "question": "What price range are you working with?",
             "values": {"under_500k": 0.5, "500k_1m": 0.3, "1m_3m": 0.2, "over_3m": 0.6},
             "synonyms": {"under_500k": ["under five hundred", "four hundred", "three hundred"],
                          "500k_1m": ["half a million", "seven hundred", "eight hundred"],
                          "1m_3m": ["a million", "two million", "three million"],
                          "over_3m": ["five million", "ten million", "no limit"]}},
            {"name": "financing", "type": "enum", "weight": 2.0,
             "question": "Will this be a cash purchase, or are you arranging a mortgage?",
             "values": {"cash": 0.15, "mortgage_approved": 0.25, "mortgage_pending": 0.8,
                        "not_arranged": 1.0},
             "synonyms": {"cash": ["cash", "outright", "no mortgage"],
                          "mortgage_approved": ["approved", "pre approved", "agreed in principle"],
                          "mortgage_pending": ["applying", "in progress", "waiting"],
                          "not_arranged": ["not yet", "havent", "need to sort"]}},
            {"name": "move_timeline", "type": "enum", "weight": 1.2,
             "question": "How soon are you hoping to move?",
             "values": {"immediate": 0.8, "three_months": 0.3, "six_months": 0.25,
                        "over_a_year": 0.7},
             "synonyms": {"immediate": ["now", "asap", "this month", "urgent"],
                          "three_months": ["three months", "quarter"],
                          "six_months": ["six months", "half a year"],
                          "over_a_year": ["next year", "no rush", "eventually"]}},
            {"name": "purpose", "type": "enum", "weight": 1.0,
             "question": "Is this to live in yourself, or as an investment?",
             "values": {"own_use": 0.2, "investment": 0.5, "resale": 0.9},
             "synonyms": {"own_use": ["live in", "myself", "family", "home"],
                          "investment": ["rent out", "investment", "yield", "portfolio"],
                          "resale": ["flip", "resell", "quick sale"]}},
        ],
        "checks": [
            {"name": "financing_risk", "field": "financing",
             "flags": {"hit": ["not_arranged"], "review": ["mortgage_pending"]}},
            {"name": "speculation_signal", "field": "purpose",
             "flags": {"hit": ["resale"], "review": ["investment"]}},
        ],
    },
    {
        "pack_id": "claim-fnol",
        "display_name": "Insurance First Notice of Loss",
        "gate_role": "Claims Adjuster",
        "persona": (
            "You are a first-notice-of-loss interviewer. You are calm and methodical. "
            "You never estimate settlement amounts and never say whether something is "
            "covered. You capture what happened, when, and what was damaged."
        ),
        "gate_reason": "claims with late reporting, high value, or inconsistent circumstances",
        "thresholds": {"low": 0.28, "high": 0.62},
        "bias": -2.6,
        "fields": [
            {"name": "policy_holder", "type": "text", "min_words": 2,
             "question": "What is the name on the policy?"},
            {"name": "incident_date", "type": "date", "max_age_years": 3,
             "question": "What date did the incident happen?"},
            {"name": "incident_type", "type": "enum", "weight": 1.2,
             "question": "What kind of incident was it?",
             "values": {"collision": 0.4, "theft": 0.8, "fire": 0.7, "water": 0.4,
                        "third_party": 0.5},
             "synonyms": {"collision": ["crash", "accident", "hit", "bump"],
                          "theft": ["stolen", "burglary", "robbed"],
                          "fire": ["fire", "burnt", "smoke"],
                          "water": ["flood", "leak", "water damage", "burst"],
                          "third_party": ["someone else", "other driver", "third party"]}},
            {"name": "reported_delay", "type": "enum", "weight": 1.7,
             "question": "How long after it happened are you reporting this?",
             "values": {"same_day": 0.1, "within_a_week": 0.3, "within_a_month": 0.7,
                        "over_a_month": 1.0},
             "synonyms": {"same_day": ["same day", "today", "immediately"],
                          "within_a_week": ["few days", "this week"],
                          "within_a_month": ["few weeks", "this month"],
                          "over_a_month": ["months", "long time", "a while ago"]}},
            {"name": "estimated_value", "type": "enum", "weight": 1.4,
             "question": "Roughly what do you think the loss is worth?",
             "values": {"under_1k": 0.15, "1k_10k": 0.35, "10k_50k": 0.7, "over_50k": 1.0},
             "synonyms": {"under_1k": ["few hundred", "small", "minor"],
                          "1k_10k": ["few thousand", "several thousand"],
                          "10k_50k": ["twenty thousand", "thirty thousand"],
                          "over_50k": ["hundred thousand", "total loss", "written off"]}},
            {"name": "description", "type": "text", "min_words": 4,
             "question": "In your own words, what happened?"},
        ],
        "checks": [
            {"name": "late_report", "field": "reported_delay",
             "flags": {"hit": ["over_a_month"], "review": ["within_a_month"]}},
            {"name": "narrative_flags", "field": "description",
             "flags": {"hit": ["no witness", "cash", "friend borrowed", "cannot remember"],
                       "review": ["night", "alone", "unlit", "no cctv"]}},
        ],
    },
    {
        "pack_id": "patient-intake",
        "display_name": "Clinic Patient Intake",
        "gate_role": "Triage Nurse",
        "persona": (
            "You are a clinical intake interviewer. You are gentle and unhurried. You "
            "never diagnose, never advise treatment, and never reassure about severity. "
            "You capture symptoms, duration and risk factors for a clinician to review."
        ),
        "gate_reason": "presentations with red-flag symptoms or high-risk history",
        "thresholds": {"low": 0.25, "high": 0.55},
        "bias": -2.9,
        "fields": [
            {"name": "full_name", "type": "text", "min_words": 2,
             "question": "Could you tell me your full name?"},
            {"name": "dob", "type": "date", "min_age_years": 0, "max_age_years": 120,
             "question": "What is your date of birth?"},
            {"name": "primary_symptom", "type": "text", "min_words": 1,
             "question": "What is the main problem you are coming in with?"},
            {"name": "duration", "type": "enum", "weight": 1.1,
             "question": "How long has this been going on?",
             "values": {"today": 0.8, "days": 0.5, "weeks": 0.35, "months": 0.5},
             "synonyms": {"today": ["today", "this morning", "just started", "hours"],
                          "days": ["days", "couple of days"],
                          "weeks": ["weeks", "fortnight"],
                          "months": ["months", "long time", "years"]}},
            {"name": "severity", "type": "enum", "weight": 1.8,
             "question": "On a scale of mild, moderate or severe, how would you describe it?",
             "values": {"mild": 0.1, "moderate": 0.45, "severe": 1.0},
             "synonyms": {"mild": ["mild", "slight", "manageable", "annoying"],
                          "moderate": ["moderate", "medium", "uncomfortable"],
                          "severe": ["severe", "terrible", "worst", "unbearable", "agony"]}},
            {"name": "existing_conditions", "type": "text", "min_words": 1,
             "question": "Do you have any ongoing conditions we should know about?"},
        ],
        "checks": [
            {"name": "red_flag_symptom", "field": "primary_symptom",
             "flags": {"hit": ["chest pain", "short of breath", "breathing", "numbness",
                               "slurred", "bleeding", "fainted", "unconscious"],
                       "review": ["dizzy", "headache", "fever", "vomiting"]}},
            {"name": "comorbidity", "field": "existing_conditions",
             "flags": {"hit": ["heart", "cardiac", "stroke", "cancer", "immunosuppressed"],
                       "review": ["diabetes", "asthma", "blood pressure", "pregnant"]}},
        ],
    },
    {
        "pack_id": "loan-intake",
        "display_name": "Consumer Loan Application",
        "gate_role": "Credit Officer",
        "persona": (
            "You are a loan application interviewer. You are neutral and precise. You "
            "never quote rates, never indicate whether an application will succeed, and "
            "never give financial advice. You capture income, obligations and purpose."
        ),
        "gate_reason": "applications with thin affordability or high-risk purpose",
        "thresholds": {"low": 0.30, "high": 0.60},
        "bias": -2.5,
        "fields": [
            {"name": "full_name", "type": "text", "min_words": 2,
             "question": "Could I take your full name?"},
            {"name": "employment_status", "type": "enum", "weight": 1.6,
             "question": "What is your current employment situation?",
             "values": {"permanent": 0.15, "contract": 0.45, "self_employed": 0.6,
                        "unemployed": 1.0},
             "synonyms": {"permanent": ["permanent", "full time", "salaried", "employed"],
                          "contract": ["contract", "temporary", "fixed term", "part time"],
                          "self_employed": ["self employed", "freelance", "own business"],
                          "unemployed": ["unemployed", "between jobs", "not working"]}},
            {"name": "income_band", "type": "enum", "weight": 1.5,
             "question": "Roughly what is your monthly income after tax?",
             "values": {"under_2k": 0.9, "2k_5k": 0.45, "5k_10k": 0.2, "over_10k": 0.1},
             "synonyms": {"under_2k": ["under two thousand", "fifteen hundred", "low"],
                          "2k_5k": ["three thousand", "four thousand"],
                          "5k_10k": ["six thousand", "eight thousand"],
                          "over_10k": ["twelve thousand", "fifteen thousand", "high"]}},
            {"name": "existing_debt", "type": "enum", "weight": 1.7,
             "question": "Do you have other loans or credit commitments at the moment?",
             "values": {"none": 0.1, "one": 0.35, "two_or_three": 0.65, "many": 1.0},
             "synonyms": {"none": ["none", "no", "nothing", "clear"],
                          "one": ["one", "a car loan", "single"],
                          "two_or_three": ["two", "three", "couple"],
                          "many": ["several", "many", "four", "five", "a lot"]}},
            {"name": "loan_purpose", "type": "enum", "weight": 1.2,
             "question": "What would the loan be used for?",
             "values": {"home_improvement": 0.25, "vehicle": 0.3, "education": 0.25,
                        "debt_consolidation": 0.8, "other": 0.6},
             "synonyms": {"home_improvement": ["home", "renovation", "kitchen", "extension"],
                          "vehicle": ["car", "vehicle", "van", "motorbike"],
                          "education": ["education", "course", "tuition", "university"],
                          "debt_consolidation": ["consolidate", "pay off", "clear debts"],
                          "other": ["other", "personal", "holiday", "wedding"]}},
            {"name": "residency_years", "type": "enum", "weight": 0.9,
             "question": "How long have you lived at your current address?",
             "values": {"under_1": 0.8, "one_to_three": 0.4, "over_three": 0.15},
             "synonyms": {"under_1": ["few months", "less than a year", "just moved"],
                          "one_to_three": ["two years", "a year", "three years"],
                          "over_three": ["five years", "ten years", "long time"]}},
        ],
        "checks": [
            {"name": "affordability", "field": "income_band",
             "flags": {"hit": ["under_2k"], "review": ["2k_5k"]}},
            {"name": "debt_stacking", "field": "existing_debt",
             "flags": {"hit": ["many"], "review": ["two_or_three"]}},
        ],
    },
    {
        "pack_id": "tenant-screening",
        "display_name": "Rental Tenant Screening",
        "gate_role": "Letting Manager",
        "persona": (
            "You are a tenancy application interviewer. You are polite and even-handed. "
            "You never comment on whether an application will be accepted and never ask "
            "about protected characteristics. You capture occupancy, income and history."
        ),
        "gate_reason": "applications with unstable history or affordability strain",
        "thresholds": {"low": 0.30, "high": 0.62},
        "bias": -2.4,
        "fields": [
            {"name": "full_name", "type": "text", "min_words": 2,
             "question": "Could I take your full name?"},
            {"name": "occupants", "type": "enum", "weight": 0.8,
             "question": "How many people would be living in the property?",
             "values": {"one": 0.15, "two": 0.2, "three_or_four": 0.45, "five_plus": 0.85},
             "synonyms": {"one": ["just me", "one", "myself", "alone"],
                          "two": ["two", "me and my partner", "couple"],
                          "three_or_four": ["three", "four", "family"],
                          "five_plus": ["five", "six", "large family", "share"]}},
            {"name": "employment_status", "type": "enum", "weight": 1.4,
             "question": "What is your current employment situation?",
             "values": {"permanent": 0.15, "contract": 0.5, "self_employed": 0.55,
                        "student": 0.7, "unemployed": 1.0},
             "synonyms": {"permanent": ["permanent", "full time", "salaried"],
                          "contract": ["contract", "temporary", "part time"],
                          "self_employed": ["self employed", "freelance"],
                          "student": ["student", "studying", "university"],
                          "unemployed": ["unemployed", "not working"]}},
            {"name": "rent_to_income", "type": "enum", "weight": 1.8,
             "question": "Roughly what share of your monthly income would the rent be?",
             "values": {"under_third": 0.15, "third_to_half": 0.5, "over_half": 1.0},
             "synonyms": {"under_third": ["a quarter", "less than a third", "under thirty"],
                          "third_to_half": ["a third", "forty percent"],
                          "over_half": ["half", "most of it", "sixty percent"]}},
            {"name": "tenancy_history", "type": "enum", "weight": 1.5,
             "question": "Have you rented before, and did that tenancy end normally?",
             "values": {"clean": 0.1, "first_time": 0.5, "dispute": 1.0},
             "synonyms": {"clean": ["yes", "no problems", "ended normally", "good reference"],
                          "first_time": ["first time", "never rented", "lived at home"],
                          "dispute": ["dispute", "argument", "deposit", "evicted", "court"]}},
            {"name": "move_in", "type": "enum", "weight": 0.7,
             "question": "When would you want to move in?",
             "values": {"immediate": 0.6, "one_month": 0.2, "later": 0.4},
             "synonyms": {"immediate": ["now", "asap", "this week", "urgent"],
                          "one_month": ["next month", "four weeks"],
                          "later": ["two months", "later", "flexible"]}},
        ],
        "checks": [
            {"name": "affordability_strain", "field": "rent_to_income",
             "flags": {"hit": ["over_half"], "review": ["third_to_half"]}},
            {"name": "history_flag", "field": "tenancy_history",
             "flags": {"hit": ["dispute"], "review": ["first_time"]}},
        ],
    },
    {
        "pack_id": "support-triage",
        "display_name": "Customer Support Triage",
        "gate_role": "Support Lead",
        "persona": (
            "You are a support triage interviewer. You are efficient and never defensive. "
            "You never promise a fix or a timeline. You capture what broke, how badly it "
            "is affecting the customer, and what they already tried."
        ),
        "gate_reason": "tickets with outage-level impact or churn risk",
        "thresholds": {"low": 0.28, "high": 0.60},
        "bias": -2.7,
        "fields": [
            {"name": "account_name", "type": "text", "min_words": 1,
             "question": "Which account are you calling about?"},
            {"name": "issue_area", "type": "enum", "weight": 0.9,
             "question": "Which part of the product is affected?",
             "values": {"login": 0.6, "billing": 0.7, "data": 0.8, "performance": 0.5,
                        "other": 0.4},
             "synonyms": {"login": ["login", "sign in", "password", "locked out"],
                          "billing": ["billing", "invoice", "payment", "charged"],
                          "data": ["data", "missing", "deleted", "wrong numbers"],
                          "performance": ["slow", "timeout", "lagging", "hanging"],
                          "other": ["other", "something else"]}},
            {"name": "impact", "type": "enum", "weight": 1.9,
             "question": "How badly is this affecting your work right now?",
             "values": {"annoyance": 0.15, "workaround": 0.4, "blocked": 0.85,
                        "outage": 1.0},
             "synonyms": {"annoyance": ["annoying", "minor", "cosmetic"],
                          "workaround": ["workaround", "manageable", "we cope"],
                          "blocked": ["blocked", "cannot work", "stuck"],
                          "outage": ["everyone", "whole team", "down", "outage", "nothing works"]}},
            {"name": "started", "type": "enum", "weight": 0.8,
             "question": "When did this start?",
             "values": {"today": 0.5, "this_week": 0.4, "longer": 0.7},
             "synonyms": {"today": ["today", "this morning", "an hour ago"],
                          "this_week": ["yesterday", "this week", "few days"],
                          "longer": ["weeks", "months", "always"]}},
            {"name": "tried_already", "type": "text", "min_words": 1,
             "question": "What have you already tried?"},
        ],
        "checks": [
            {"name": "severity", "field": "impact",
             "flags": {"hit": ["outage", "blocked"], "review": ["workaround"]}},
            {"name": "churn_language", "field": "tried_already",
             "flags": {"hit": ["cancel", "refund", "competitor", "leaving", "lawyer"],
                       "review": ["frustrated", "third time", "again", "still"]}},
        ],
    },
    {
        "pack_id": "recruit-screen",
        "display_name": "Candidate Phone Screen",
        "gate_role": "Hiring Manager",
        "persona": (
            "You are a first-round candidate screener. You are friendly and neutral. You "
            "never evaluate the candidate out loud, never discuss other applicants, and "
            "never ask about protected characteristics. You capture experience, notice "
            "period and expectations."
        ),
        "gate_reason": "candidates outside the band, or with availability that breaks the plan",
        "thresholds": {"low": 0.32, "high": 0.66},
        "bias": -2.3,
        "fields": [
            {"name": "full_name", "type": "text", "min_words": 2,
             "question": "Could I take your full name?"},
            {"name": "years_experience", "type": "enum", "weight": 1.3,
             "question": "How many years have you worked in this kind of role?",
             "values": {"under_2": 0.8, "two_to_five": 0.35, "five_to_ten": 0.15,
                        "over_ten": 0.2},
             "synonyms": {"under_2": ["one year", "just started", "graduate", "less than two"],
                          "two_to_five": ["three years", "four years", "couple"],
                          "five_to_ten": ["six years", "eight years", "seven"],
                          "over_ten": ["twelve years", "fifteen", "twenty", "a long time"]}},
            {"name": "current_role", "type": "text", "min_words": 1,
             "question": "What is your current job title?"},
            {"name": "notice_period", "type": "enum", "weight": 1.1,
             "question": "What notice period would you need to give?",
             "values": {"immediate": 0.3, "one_month": 0.2, "three_months": 0.7,
                        "longer": 1.0},
             "synonyms": {"immediate": ["immediately", "available now", "no notice"],
                          "one_month": ["a month", "four weeks"],
                          "three_months": ["three months", "quarter"],
                          "longer": ["six months", "long notice"]}},
            {"name": "salary_band", "type": "enum", "weight": 1.5,
             "question": "What salary range are you targeting?",
             "values": {"below_band": 0.4, "in_band": 0.1, "above_band": 0.9,
                        "not_stated": 0.6},
             "synonyms": {"below_band": ["flexible", "negotiable", "modest"],
                          "in_band": ["market rate", "in line", "around"],
                          "above_band": ["premium", "significant increase", "top of market"],
                          "not_stated": ["prefer not", "depends", "open"]}},
            {"name": "motivation", "type": "text", "min_words": 3,
             "question": "Why are you looking to move?"},
        ],
        "checks": [
            {"name": "availability_risk", "field": "notice_period",
             "flags": {"hit": ["longer"], "review": ["three_months"]}},
            {"name": "motivation_flags", "field": "motivation",
             "flags": {"hit": ["fired", "dismissed", "conflict", "tribunal"],
                       "review": ["redundant", "restructure", "bored", "money"]}},
        ],
    },
]


def main() -> None:
    for spec in SPECS:
        directory = write_pack(spec, PACKS, REPO / "tests")
        print(f"generated {spec['pack_id']:<20} -> {directory.relative_to(REPO)}")

    print(f"\n{len(SPECS)} packs generated. Run: uv run pytest -q")


if __name__ == "__main__":
    main()
