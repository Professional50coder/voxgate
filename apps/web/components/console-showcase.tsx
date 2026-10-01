"use client";

import {
  ArrowCounterClockwise, CheckCircle, ChatCircleText, ShieldCheck, ShieldWarning, XCircle,
} from "@phosphor-icons/react";
import { useState } from "react";

/**
 * What the reviewer sees, as an interactive sample. The case is synthetic and
 * labelled as such; deciding it only changes this page. It exists because a
 * compliance buyer is buying the review step, and a screenshot cannot show a
 * decision being recorded.
 */

const SAMPLE = {
  applicant: "Mohammed Al Rashed",
  pack: "Banking KYC",
  fields: [
    ["Full name", "Mohammed Al Rashed"],
    ["Date of birth", "1984-11-02"],
    ["Nationality", "AE"],
    ["Residency", "UAE resident"],
    ["Source of funds", "Business income"],
    ["Product", "Derivatives"],
  ],
  probability: 0.71,
  factors: [
    { reason: "Name is 91% similar to a UN sanctions list entry", weight: 2.73 },
    { reason: "Derivatives carry higher product risk", weight: 0.64 },
    { reason: "Business income needs source documents", weight: 0.45 },
    { reason: "No negative news coverage found", weight: 0 },
  ],
  checks: [
    { name: "Sanctions", status: "hit", note: "UN Consolidated · Mohammed Al Rashid · 91%" },
    { name: "PEP", status: "clear", note: "Closest match 48%" },
    { name: "Adverse media", status: "clear", note: "No articles" },
  ],
  summary:
    "Applicant answered all six questions in under three minutes and corrected his date of birth once. The name closely matches a UN sanctions entry, but the date of birth differs by eleven years. Recommend confirming identity documents before deciding.",
  transcript: [
    ["agent", "Could you tell me your full name, exactly as it appears on your passport?"],
    ["applicant", "Mohammed Al Rashed."],
    ["agent", "Thank you. And your date of birth?"],
    ["applicant", "Second of November 1985. Sorry, 1984."],
  ],
};

type Decision = { action: "approve" | "reject" | "info"; at: string } | null;

export function ConsoleShowcase() {
  const [decision, setDecision] = useState<Decision>(null);
  const [tab, setTab] = useState<"why" | "transcript">("why");
  const max = Math.max(...SAMPLE.factors.map((f) => f.weight));

  const decide = (action: "approve" | "reject" | "info") =>
    setDecision({ action, at: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) });

  const label = { approve: "Approved", reject: "Rejected", info: "More information requested" };

  return (
    <div className="glass overflow-hidden rounded-[var(--r-card)] text-left">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-glass-border-soft px-5 py-3.5">
        <div>
          <p className="text-[15px] font-semibold">{SAMPLE.applicant}</p>
          <p className="text-[12px] text-text-faint">{SAMPLE.pack} · sample case, synthetic data</p>
        </div>
        <span className="rounded-[var(--r-pill)] px-3 py-1 text-[12px] font-semibold text-[#0a0a12]"
          style={{ background: decision ? (decision.action === "approve" ? "var(--color-status-approved)" : decision.action === "reject" ? "var(--color-status-rejected)" : "var(--color-status-awaiting-interview)") : "var(--color-status-awaiting-review)" }}>
          {decision ? label[decision.action] : "Awaiting your review"}
        </span>
      </div>

      <div className="grid gap-0 md:grid-cols-[1fr_1.25fr]">
        <div className="border-b border-glass-border-soft p-5 md:border-b-0 md:border-r">
          <p className="text-[11.5px] uppercase tracking-[0.14em] text-text-faint">Captured by voice</p>
          <dl className="mt-3 space-y-2">
            {SAMPLE.fields.map(([k, v]) => (
              <div key={k} className="flex justify-between gap-3 text-[13px]">
                <dt className="text-text-faint">{k}</dt><dd className="text-right">{v}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-5 text-[11.5px] uppercase tracking-[0.14em] text-text-faint">Screening</p>
          <ul className="mt-2 space-y-2">
            {SAMPLE.checks.map((c) => (
              <li key={c.name} className="flex items-start gap-2 text-[13px]">
                {c.status === "clear" ? <ShieldCheck size={16} className="mt-0.5 shrink-0 text-[var(--color-status-approved)]" />
                  : <ShieldWarning size={16} weight="fill" className="mt-0.5 shrink-0 text-[var(--color-status-rejected)]" />}
                <span><b className="font-medium">{c.name}</b> <span className="text-text-faint">· {c.note}</span></span>
              </li>
            ))}
          </ul>
        </div>

        <div className="p-5">
          <div className="flex items-baseline justify-between">
            <span className="text-[13px] text-text-dim">Risk score</span>
            <span className="text-[13px] font-semibold text-[var(--color-risk-high)]">High · {Math.round(SAMPLE.probability * 100)}%</span>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-white/[0.06]">
            <div className="h-full rounded-full bg-[var(--color-risk-high)]" style={{ width: `${SAMPLE.probability * 100}%` }} />
          </div>

          <div role="tablist" className="mt-5 flex gap-1">
            {(["why", "transcript"] as const).map((t) => (
              <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
                className={`rounded-[var(--r-pill)] px-3 py-1 text-[12.5px] ${tab === t ? "bg-white/[0.1] text-text" : "text-text-dim hover:text-text"}`}>
                {t === "why" ? "Why this score" : "Transcript"}
              </button>
            ))}
          </div>

          {tab === "why" ? (
            <ul className="mt-3 space-y-2.5">
              {SAMPLE.factors.map((f) => (
                <li key={f.reason}>
                  <p className="text-[13px]">{f.reason}</p>
                  <div className="mt-1 h-1 overflow-hidden rounded-full bg-white/[0.05]">
                    <div className="h-full rounded-full bg-[var(--color-siri-2)]" style={{ width: `${(100 * f.weight) / max}%` }} />
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <ul className="mt-3 space-y-2">
              {SAMPLE.transcript.map(([who, text], i) => (
                <li key={i} className="text-[13px]">
                  <span className="text-text-faint">{who === "agent" ? "Lucy" : "Applicant"}:</span> {text}
                </li>
              ))}
            </ul>
          )}

          <div className="mt-4 rounded-[10px] bg-[var(--color-surface-2)] p-3">
            <p className="flex items-center gap-1.5 text-[11.5px] uppercase tracking-[0.14em] text-text-faint">
              <ChatCircleText size={13} /> Summary for the reviewer
            </p>
            <p className="mt-1.5 text-[13px] leading-relaxed text-text-dim">{SAMPLE.summary}</p>
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 border-t border-glass-border-soft px-5 py-3.5">
        {decision ? (
          <>
            <p className="land text-[13px] text-text-dim">
              Recorded at {decision.at}: <b className="text-text">{label[decision.action]}</b> by you, with the score,
              checks and transcript attached to the audit trail.
            </p>
            <button onClick={() => setDecision(null)} className="ml-auto flex items-center gap-1.5 text-[12.5px] text-text-faint hover:text-text">
              <ArrowCounterClockwise size={14} /> Reset sample
            </button>
          </>
        ) : (
          <>
            <span className="mr-auto text-[13px] text-text-dim">Your call:</span>
            <button onClick={() => decide("info")} className="rounded-[var(--r-pill)] border border-glass-border px-4 py-2 text-[13px] hover:border-white/25">
              Ask for documents
            </button>
            <button onClick={() => decide("reject")} className="flex items-center gap-1.5 rounded-[var(--r-pill)] border border-[var(--color-status-rejected)]/40 px-4 py-2 text-[13px] text-[var(--color-status-rejected)] hover:bg-[var(--color-status-rejected)]/10">
              <XCircle size={15} /> Reject
            </button>
            <button onClick={() => decide("approve")} className="flex items-center gap-1.5 rounded-[var(--r-pill)] px-4 py-2 text-[13px] font-semibold text-[#0a0a12]" style={{ background: "var(--color-status-approved)" }}>
              <CheckCircle size={15} weight="fill" /> Approve
            </button>
          </>
        )}
      </div>
    </div>
  );
}
