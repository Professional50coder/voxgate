"use client";

import { CheckCircle, ShieldCheck, ShieldWarning, UserCircleGear } from "@phosphor-icons/react";
import Link from "next/link";

import { humanize } from "@/components/capture-panel";
import type { Case } from "@/lib/api";

const BAND_COLOR: Record<string, string> = {
  low: "var(--color-risk-low)",
  medium: "var(--color-risk-medium)",
  high: "var(--color-risk-high)",
};

/** Plain-language reason for one scorecard factor. */
function reason(feature: string, value: number, checks: Case["check_results"]): string {
  const pct = Math.round(value * 100);
  const check = (name: string) => checks.find((c) => c.check_name === name)?.status;
  if (feature === "sanctions_similarity") return `Closest sanctions list match is ${pct}% similar (${check("sanctions") ?? "checked"}).`;
  if (feature === "pep_similarity") return `Closest politically exposed person is ${pct}% similar (${check("pep") ?? "checked"}).`;
  if (feature === "adverse_media") return value > 0 ? "Negative news coverage was found." : "No negative news coverage found.";
  if (feature === "non_resident") return value > 0 ? "Applicant lives outside the country." : "Applicant is a resident.";
  return value > 0 ? `${humanize(feature)} adds risk.` : `${humanize(feature)} adds no risk.`;
}

/**
 * The outcome of the call: the decision, the risk score built factor by factor
 * with a reason for each, and the screening checks. This is what nobody else
 * shows on a voice-agent site, and what a compliance buyer actually buys.
 */
export function OutcomeCard({ result, gateRole }: { result: Case; gateRole: string }) {
  const prob = result.score?.probability ?? null;
  const band = result.score?.band ?? "low";
  const factors = [...(result.score?.contributions ?? [])]
    .filter((c) => c.contribution !== 0 || c.value !== 0)
    .sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution))
    .slice(0, 5);
  const maxContribution = Math.max(...factors.map((f) => Math.abs(f.contribution)), 0.01);

  const headline =
    result.status === "approved" ? { icon: <CheckCircle size={22} weight="fill" />, text: "Approved automatically", color: "var(--color-status-approved)" }
    : result.status === "rejected" ? { icon: <ShieldWarning size={22} weight="fill" />, text: "Declined", color: "var(--color-status-rejected)" }
    : result.status === "awaiting_interview" ? { icon: <ShieldWarning size={22} weight="fill" />, text: "A few answers need confirming", color: "var(--color-status-awaiting-interview)" }
    : { icon: <UserCircleGear size={22} weight="fill" />, text: `Sent to a ${gateRole} for review`, color: "var(--color-status-awaiting-review)" };

  return (
    <section className="glass mt-8 w-full rounded-[var(--r-card)] p-6 text-left" aria-label="Result of the interview">
      <p className="land flex items-center gap-2.5 text-[18px] font-semibold" style={{ color: headline.color }}>
        {headline.icon}{headline.text}
      </p>

      {prob !== null ? (
        <div className="mt-6">
          <div className="flex items-baseline justify-between text-[13px]">
            <span className="text-text-dim">Risk score</span>
            <span className="font-semibold capitalize" style={{ color: BAND_COLOR[band] }}>
              {band} · {Math.round(prob * 100)}%
            </span>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-white/[0.06]">
            <div className="grow-x h-full rounded-full" style={{ width: `${Math.max(prob * 100, 2)}%`, background: BAND_COLOR[band] }} />
          </div>
        </div>
      ) : null}

      {factors.length ? (
        <div className="mt-6">
          <p className="text-[12px] uppercase tracking-[0.14em] text-text-faint">Why</p>
          <ul className="mt-3 space-y-3">
            {factors.map((f, i) => (
              <li key={f.feature} className="land" style={{ animationDelay: `${150 + i * 120}ms` }}>
                <div className="flex justify-between gap-3 text-[13.5px]">
                  <span>{reason(f.feature, f.value, result.check_results)}</span>
                  <span className="shrink-0 text-text-faint">{f.contribution > 0 ? "+" : ""}{f.contribution.toFixed(2)}</span>
                </div>
                <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-white/[0.05]">
                  <div className="grow-x h-full rounded-full bg-[var(--color-siri-2)]"
                    style={{ width: `${(100 * Math.abs(f.contribution)) / maxContribution}%`, animationDelay: `${150 + i * 120}ms` }} />
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {result.check_results.length ? (
        <div className="mt-6 flex flex-wrap gap-2">
          {result.check_results.map((c) => (
            <span key={c.check_name} className="flex items-center gap-1.5 rounded-[var(--r-pill)] border border-glass-border px-3 py-1 text-[12.5px]">
              {c.status === "clear" ? <ShieldCheck size={14} className="text-[var(--color-status-approved)]" />
                : <ShieldWarning size={14} className="text-[var(--color-status-rejected)]" />}
              {humanize(c.check_name)}: {c.status}
            </span>
          ))}
        </div>
      ) : null}

      <p className="mt-6 text-[13px] leading-relaxed text-text-dim">
        Every factor above is recorded with the transcript, so the reviewer and an auditor see exactly why.
      </p>
      <Link href="/console" className="mt-4 inline-block text-[13.5px] font-medium text-[var(--color-siri-1)] hover:underline">
        See what the reviewer sees →
      </Link>
    </section>
  );
}
