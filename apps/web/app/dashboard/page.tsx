"use client";

import { ArrowRight } from "@phosphor-icons/react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { AppNav } from "@/components/app-nav";
import { ApiUnreachable, NotAuthorized, type Case, type Pack, getPacks, listCases } from "@/lib/api";
import { Insights } from "@/components/insights";
import { OperatorKeyGate } from "@/components/operator-key-gate";

const MONO = { fontFamily: "var(--font-geist-mono), monospace" } as const;

const STATUS_ORDER = [
  "awaiting_interview",
  "processing",
  "awaiting_review",
  "approved",
  "rejected",
  "needs_attention",
] as const;

const STATUS_COLOR: Record<string, string> = {
  awaiting_interview: "var(--color-status-awaiting-interview)",
  processing: "var(--color-status-processing)",
  awaiting_review: "var(--color-status-awaiting-review)",
  approved: "var(--color-status-approved)",
  rejected: "var(--color-status-rejected)",
  needs_attention: "var(--color-status-needs-attention)",
};

const BAND_COLOR: Record<string, string> = {
  low: "var(--color-risk-low)",
  medium: "var(--color-risk-medium)",
  high: "var(--color-risk-high)",
};

export default function Dashboard() {
  const [cases, setCases] = useState<Case[]>([]);
  const [packs, setPacks] = useState<Pack[]>([]);
  const [offline, setOffline] = useState(false);
  const [locked, setLocked] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([listCases(), getPacks()])
      .then(([c, p]) => {
        setCases(c);
        setPacks(p);
      })
      .catch((err) => {
        if (err instanceof ApiUnreachable) setOffline(true);
        else if (err instanceof NotAuthorized) setLocked(err.status);
      })
      .finally(() => setLoading(false));
  }, []);

  const stats = useMemo(() => {
    const byStatus = new Map<string, number>();
    const byBand = new Map<string, number>();
    for (const c of cases) {
      byStatus.set(c.status, (byStatus.get(c.status) ?? 0) + 1);
      const band = c.score?.band;
      if (band) byBand.set(band, (byBand.get(band) ?? 0) + 1);
    }
    const decided = (byStatus.get("approved") ?? 0) + (byStatus.get("rejected") ?? 0);
    const scored = [...byBand.values()].reduce((a, b) => a + b, 0);
    const durations = cases.flatMap((c) => c.audit.map((a) => a.duration_ms));
    const totalMs = durations.reduce((a, b) => a + b, 0);

    return {
      total: cases.length,
      open: cases.length - decided,
      awaitingReview: byStatus.get("awaiting_review") ?? 0,
      autoApprovalRate:
        decided > 0 ? Math.round(((byStatus.get("approved") ?? 0) / decided) * 100) : null,
      byStatus,
      byBand,
      scored,
      avgNodeMs: durations.length > 0 ? totalMs / durations.length : null,
    };
  }, [cases]);

  return (
    <div className="min-h-[100dvh]">
      <AppNav />
      <main className="mx-auto max-w-[1200px] px-6 py-10">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Overview</h1>
            <p className="mt-1.5 text-[14px] text-text-dim">
              {packs[0]?.display_name ?? "Compliance"} workspace
            </p>
          </div>
          <Link
            href="/console"
            className="inline-flex items-center gap-2 rounded-[var(--r-pill)] border border-glass-border px-4 py-2 text-[13.5px] text-text transition-all hover:border-white/25"
          >
            Go to case queue
            <ArrowRight size={14} weight="bold" />
          </Link>
        </div>

        {locked !== null ? (
          <div className="py-10">
            <OperatorKeyGate
              status={locked}
              onSaved={() => {
                setLocked(null);
                // Reload rather than re-run the fetch by hand: this page loads
                // its data from a mount-only effect with no named refresh.
                window.location.reload();
              }}
            />
          </div>
        ) : offline ? (
          <p className="mt-8 rounded-[var(--r-card)] border border-[var(--color-status-needs-attention)]/35 bg-[var(--color-surface-2)] px-6 py-5 text-[14px] text-text-dim">
            Backend is not running. Start it with{" "}
            <code style={MONO}>uv run uvicorn voxgate.service.app:app</code> and reload.
          </p>
        ) : null}

        {loading ? (
          <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-[104px] animate-pulse rounded-[var(--r-card)] bg-[var(--color-surface-2)]"
              />
            ))}
          </div>
        ) : null}

        {!loading && !offline && locked === null ? (
          <>
            {/* KPI row. Container queries let each tile reflow by its own width. */}
            <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Kpi label="Cases" value={stats.total} />
              <Kpi label="Open" value={stats.open} />
              <Kpi
                label="Awaiting review"
                value={stats.awaitingReview}
                tone={stats.awaitingReview > 0 ? "var(--color-status-awaiting-review)" : undefined}
              />
              <Kpi
                label="Auto approval rate"
                value={stats.autoApprovalRate === null ? "—" : `${stats.autoApprovalRate}%`}
                hint={stats.autoApprovalRate === null ? "No decided cases yet" : undefined}
              />
            </div>

            <div className="mt-6 grid gap-6 lg:grid-cols-12">
              {/* Status funnel. Pure CSS bars, no chart library. */}
              <section className="rounded-[var(--r-card)] border border-glass-border-soft bg-[var(--color-surface-2)] p-7 lg:col-span-7">
                <h2 className="text-[15px] font-semibold">Status breakdown</h2>
                {stats.total === 0 ? (
                  <Empty>No cases yet.</Empty>
                ) : (
                  <ul className="mt-6 space-y-3.5">
                    {STATUS_ORDER.filter((s) => (stats.byStatus.get(s) ?? 0) > 0).map((s) => {
                      const n = stats.byStatus.get(s) ?? 0;
                      const pct = Math.round((n / stats.total) * 100);
                      return (
                        <li key={s} className="grid grid-cols-[128px_1fr_36px] items-center gap-4">
                          <span className="text-[12.5px] text-text-dim">
                            {s.replace(/_/g, " ")}
                          </span>
                          <span className="h-2 overflow-hidden rounded-full bg-[var(--color-glass)]">
                            <span
                              className="block h-full rounded-full transition-[width] duration-500"
                              style={{ width: `${pct}%`, background: STATUS_COLOR[s] }}
                            />
                          </span>
                          <span className="text-right text-[12.5px]" style={MONO}>
                            {n}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </section>

              {/* Risk band distribution as a single segmented bar. */}
              <section className="rounded-[var(--r-card)] border border-glass-border-soft bg-[var(--color-surface-2)] p-7 lg:col-span-5">
                <h2 className="text-[15px] font-semibold">Risk bands</h2>
                {stats.scored === 0 ? (
                  <Empty>No scored cases yet.</Empty>
                ) : (
                  <>
                    <div className="mt-6 flex h-3 overflow-hidden rounded-full">
                      {(["low", "medium", "high"] as const).map((band) => {
                        const n = stats.byBand.get(band) ?? 0;
                        if (n === 0) return null;
                        return (
                          <span
                            key={band}
                            style={{
                              width: `${(n / stats.scored) * 100}%`,
                              background: BAND_COLOR[band],
                            }}
                          />
                        );
                      })}
                    </div>
                    <ul className="mt-5 space-y-2.5">
                      {(["low", "medium", "high"] as const).map((band) => (
                        <li
                          key={band}
                          className="flex items-center justify-between text-[13px]"
                        >
                          <span className="flex items-center gap-2.5">
                            <span
                              aria-hidden="true"
                              className="h-2 w-2 rounded-full"
                              style={{ background: BAND_COLOR[band] }}
                            />
                            <span className="text-text-dim">{band}</span>
                          </span>
                          <span style={MONO}>{stats.byBand.get(band) ?? 0}</span>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </section>
            </div>

            <section className="mt-6 rounded-[var(--r-card)] border border-glass-border-soft bg-[var(--color-surface-2)] p-7">
              <div className="flex items-baseline justify-between">
                <h2 className="text-[15px] font-semibold">Recent activity</h2>
                {stats.avgNodeMs !== null ? (
                  <span className="text-[12.5px] text-text-faint">
                    mean node time {stats.avgNodeMs.toFixed(2)}ms
                  </span>
                ) : null}
              </div>
              {cases.length === 0 ? (
                <Empty>
                  Nothing yet. Run the{" "}
                  <Link href="/apply" className="text-[var(--color-siri-1)] underline">
                    applicant interview
                  </Link>{" "}
                  to create one.
                </Empty>
              ) : (
                <ul className="mt-5 divide-y divide-[var(--color-glass-border-soft)]">
                  {cases.slice(0, 6).map((c) => (
                    <li key={c.case_id} className="flex items-center justify-between gap-4 py-3">
                      <span className="text-[12.5px] text-text-faint" style={MONO}>
                        {c.case_id.slice(0, 8)}
                      </span>
                      <span className="flex items-center gap-5">
                        {c.score?.band ? (
                          <span
                            className="text-[12.5px]"
                            style={{ ...MONO, color: BAND_COLOR[c.score.band] }}
                          >
                            {c.score.band}
                          </span>
                        ) : null}
                        <span
                          className="rounded-[var(--r-pill)] px-2.5 py-1 text-[11.5px]"
                          style={{
                            color: STATUS_COLOR[c.status] ?? "var(--color-text-dim)",
                            background: `color-mix(in oklab, ${
                              STATUS_COLOR[c.status] ?? "#a6acc2"
                            } 14%, transparent)`,
                          }}
                        >
                          {c.status.replace(/_/g, " ")}
                        </span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <Insights />
          </>
        ) : null}
      </main>
    </div>
  );
}

function Kpi({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: number | string;
  hint?: string;
  tone?: string;
}) {
  return (
    <div className="rounded-[var(--r-card)] border border-glass-border-soft bg-[var(--color-surface-2)] p-6">
      {/* Plain text, never gradient: a misread digit in a compliance tool is an incident. */}
      <p className="text-[30px] font-semibold leading-none" style={{ color: tone }}>
        {value}
      </p>
      <p className="mt-2.5 text-[12.5px] text-text-dim">{label}</p>
      {hint ? <p className="mt-1 text-[11.5px] text-text-faint">{hint}</p> : null}
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="mt-6 text-[13.5px] leading-relaxed text-text-dim">{children}</p>;
}
