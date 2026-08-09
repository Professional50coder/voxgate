"use client";

import { ArrowClockwise, Check, LinkSimple, Plus, WarningCircle } from "@phosphor-icons/react";
import Link from "next/link";

import { OperatorKeyGate } from "@/components/operator-key-gate";
import { useCallback, useEffect, useState } from "react";

import {
  ApiUnreachable,
  NotAuthorized,
  type Case,
  type Pack,
  createCase,
  getPacks,
  listCases,
  submitDecision,
  submitInterview,
} from "@/lib/api";

const STATUS_COLOR: Record<string, string> = {
  awaiting_interview: "var(--color-status-awaiting-interview)",
  processing: "var(--color-status-processing)",
  awaiting_review: "var(--color-status-awaiting-review)",
  approved: "var(--color-status-approved)",
  rejected: "var(--color-status-rejected)",
  needs_attention: "var(--color-status-needs-attention)",
};

const MONO = { fontFamily: "var(--font-geist-mono), monospace" } as const;

/**
 * The two demo applicants from scripts/demo_case.py, kept identical so the
 * console and the CLI demo exercise the same paths. Both are synthetic.
 * CLEAN routes to auto approval; RISKY hits screening and opens the reviewer gate.
 */
const CLEAN_FIELDS = {
  full_name: "Priya Raghavan",
  dob: "1992-04-15",
  nationality: "IN",
  residency_status: "uae_resident",
  source_of_funds: "salary",
  product: "spot_trading",
};

const RISKY_FIELDS = {
  full_name: "Muhammad Al-Rashid",
  dob: "1975-03-02",
  nationality: "SY",
  residency_status: "non_resident",
  source_of_funds: "crypto_trading",
  product: "derivatives",
};

export default function Console() {
  const [packs, setPacks] = useState<Pack[]>([]);
  const [cases, setCases] = useState<Case[]>([]);
  const [selected, setSelected] = useState<Case | null>(null);
  const [offline, setOffline] = useState(false);
  // null = authorised. 401 = no key sent, 403 = key rejected; the gate
  // gives different advice for each.
  const [locked, setLocked] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  /**
   * Reload the board.
   *
   * `isStale` lets a caller abandon a response that arrived after it stopped
   * caring — the mount effect passes an unmount flag. Without it, a reviewer
   * navigating away during a slow load had state set on a component that no
   * longer existed.
   */
  const refresh = useCallback(async (isStale: () => boolean = () => false) => {
    try {
      const [p, c] = await Promise.all([getPacks(), listCases()]);
      if (isStale()) return;
      setPacks(p);
      setCases(c);
      setOffline(false);
      setError(null);
    } catch (err) {
      if (isStale()) return;
      if (err instanceof ApiUnreachable) setOffline(true);
      else if (err instanceof NotAuthorized) setLocked(err.status);
      else setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (!isStale()) setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    // Kicked off from a microtask rather than the effect body. `refresh` only
    // sets state after its fetch resolves, but calling it directly from the
    // body is indistinguishable to the compiler from a synchronous setState,
    // and the whole point of that rule is that the effect body must not itself
    // schedule a render. `cancelled` discards a response that lands after the
    // reviewer has navigated away.
    void Promise.resolve().then(() => refresh(() => cancelled));
    return () => {
      cancelled = true;
    };
  }, [refresh]);

  async function act<T>(fn: () => Promise<T>) {
    setBusy(true);
    setError(null);
    try {
      const result = await fn();
      await refresh();
      return result;
    } catch (err) {
      if (err instanceof ApiUnreachable) setOffline(true);
      else if (err instanceof NotAuthorized) setLocked(err.status);
      else setError(err instanceof Error ? err.message : String(err));
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function copyInvite(id: string) {
    const url = `${window.location.origin}/apply/${id}`;
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      // Clipboard can be blocked by permissions policy. Falling back to a
      // prompt is ugly but beats silently doing nothing.
      window.prompt("Copy this invite link", url);
    }
    setCopied(id);
    setTimeout(() => setCopied((c) => (c === id ? null : c)), 2000);
  }

  const onCreate = () =>
    act(async () => {
      const created = await createCase(packs[0]?.pack_id ?? "kyc-uae");
      setSelected(created);
      return created;
    });

  const onInterview = (id: string, fields: Record<string, unknown>) =>
    act(async () => {
      const updated = await submitInterview(id, fields);
      setSelected(updated);
      return updated;
    });

  const onDecide = (id: string, action: string) =>
    act(async () => {
      const updated = await submitDecision(id, action, "Reviewed in console");
      setSelected(updated);
      return updated;
    });

  return (
    <div className="min-h-[100dvh]">
      <header className="sticky top-0 z-50 h-16 glass border-x-0 border-t-0">
        <div className="mx-auto flex h-full max-w-[1200px] items-center justify-between px-6">
          <Link href="/" className="flex items-center gap-2.5">
            <span
              aria-hidden="true"
              className="h-5 w-5 rounded-full"
              style={{ background: "var(--siri-gradient)" }}
            />
            <span className="text-[15px] font-semibold tracking-tight">VoxGate</span>
            <span className="ml-1 text-[13px] text-text-faint">Console</span>
          </Link>
          <div className="flex items-center gap-3">
            <button
              onClick={() => void refresh()}
              disabled={busy}
              className="inline-flex items-center gap-2 rounded-[var(--r-pill)] border border-glass-border px-4 py-2 text-[13px] text-text transition-all hover:border-white/25 active:scale-[0.98] disabled:opacity-50"
            >
              <ArrowClockwise size={14} weight="bold" />
              Refresh
            </button>
            <button
              onClick={() => void onCreate()}
              disabled={busy || offline || packs.length === 0}
              className="inline-flex items-center gap-2 rounded-[var(--r-pill)] px-4 py-2 text-[13px] font-semibold text-[#0a0a12] transition-transform active:scale-[0.98] disabled:opacity-40"
              style={{ background: "var(--siri-gradient)" }}
            >
              <Plus size={14} weight="bold" />
              New case
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1200px] px-6 py-10">
        {locked !== null ? (
          <div className="py-10">
            <OperatorKeyGate status={locked} onSaved={() => {
              setLocked(null);
              setLoading(true);
              void refresh();
            }} />
          </div>
        ) : offline ? (
          <div className="rounded-[var(--r-card)] border border-[var(--color-status-needs-attention)]/35 bg-[var(--color-surface-2)] p-8">
            <div className="flex items-start gap-4">
              <WarningCircle
                size={22}
                weight="duotone"
                color="var(--color-status-needs-attention)"
              />
              <div>
                <h2 className="text-[16px] font-semibold">Backend is not running</h2>
                <p className="mt-2 max-w-[62ch] text-[14px] leading-relaxed text-text-dim">
                  This console talks to the VoxGate API. Start it from the repo root, then
                  press Refresh.
                </p>
                <pre
                  className="mt-5 overflow-x-auto rounded-[var(--r-input)] border border-glass-border-soft bg-[#05070e] p-4 text-[12.5px] text-text-dim"
                  style={MONO}
                >
                  uv run uvicorn voxgate.service.app:app
                </pre>
              </div>
            </div>
          </div>
        ) : null}

        {error ? (
          <p className="mb-6 rounded-[var(--r-input)] border border-[var(--color-status-rejected)]/35 px-4 py-3 text-[13px] text-[var(--color-status-rejected)]">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="space-y-3">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="h-[76px] animate-pulse rounded-[var(--r-card)] bg-[var(--color-surface-2)]"
              />
            ))}
          </div>
        ) : null}

        {!loading && !offline && locked === null ? (
          <div className="grid grid-cols-1 gap-8 lg:grid-cols-12 lg:gap-12">
            <section className="lg:col-span-7">
              <div className="mb-4 flex items-baseline justify-between">
                <h1 className="text-[17px] font-semibold">Case board</h1>
                <span className="text-[12.5px] text-text-faint">
                  {cases.length} {cases.length === 1 ? "case" : "cases"}
                </span>
              </div>

              {cases.length === 0 ? (
                <div className="rounded-[var(--r-card)] border border-glass-border-soft bg-[var(--color-surface-2)] p-10 text-center">
                  <h2 className="text-[15px] font-semibold">No cases yet</h2>
                  <p className="mx-auto mt-2 max-w-[44ch] text-[13.5px] leading-relaxed text-text-dim">
                    Start a case against the {packs[0]?.display_name ?? "compliance"} pack
                    to watch it move through the pipeline.
                  </p>
                </div>
              ) : (
                <ul className="space-y-2.5">
                  {cases.map((c) => (
                    <li key={c.case_id}>
                      <button
                        onClick={() => setSelected(c)}
                        className={`w-full rounded-[var(--r-card)] border p-5 text-left transition-all ${
                          selected?.case_id === c.case_id
                            ? "border-white/25 bg-[var(--color-glass)]"
                            : "border-glass-border-soft bg-[var(--color-surface-2)] hover:border-white/15"
                        }`}
                      >
                        <div className="flex items-center justify-between gap-4">
                          <span className="text-[12.5px] text-text-faint" style={MONO}>
                            {c.case_id.slice(0, 8)}
                          </span>
                          <span
                            className="rounded-[var(--r-pill)] px-2.5 py-1 text-[11.5px] font-medium"
                            style={{
                              color: STATUS_COLOR[c.status] ?? "var(--color-text-dim)",
                              background: `color-mix(in oklab, ${
                                STATUS_COLOR[c.status] ?? "#a6acc2"
                              } 14%, transparent)`,
                            }}
                          >
                            {c.status.replace(/_/g, " ")}
                          </span>
                        </div>
                        <div className="mt-3 flex items-center justify-between gap-4">
                          <span className="text-[14px]">{c.pack_id}</span>
                          {c.score?.band ? (
                            <span
                              className="text-[12.5px]"
                              style={{
                                ...MONO,
                                color:
                                  c.score.band === "low"
                                    ? "var(--color-risk-low)"
                                    : c.score.band === "medium"
                                      ? "var(--color-risk-medium)"
                                      : "var(--color-risk-high)",
                              }}
                            >
                              {c.score.band}
                              {c.score.probability !== null
                                ? ` ${c.score.probability.toFixed(2)}`
                                : ""}
                            </span>
                          ) : null}
                        </div>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="lg:col-span-5">
              <h2 className="mb-4 text-[17px] font-semibold">Detail</h2>
              {selected === null ? (
                <div className="rounded-[var(--r-card)] border border-glass-border-soft bg-[var(--color-surface-2)] p-8 text-[13.5px] leading-relaxed text-text-dim">
                  Select a case to see its audit trail and act on its open gate.
                </div>
              ) : (
                <div className="rounded-[var(--r-card)] border border-glass-border-soft bg-[var(--color-surface-2)] p-6">
                  <p className="text-[12.5px] text-text-faint" style={MONO}>
                    {selected.case_id}
                  </p>

                  {selected.interrupt?.type === "interview" ? (
                    <div className="mt-5">
                      <p className="text-[13.5px] leading-relaxed text-text-dim">
                        Waiting on the interview. Send the applicant an invite link, or
                        drive the graph directly with one of two synthetic applicants.
                      </p>
                      {selected.interrupt.reask_fields &&
                      selected.interrupt.reask_fields.length > 0 ? (
                        <p className="mt-3 rounded-[var(--r-input)] border border-[var(--color-status-awaiting-interview)]/30 px-3 py-2 text-[12.5px] text-[var(--color-status-awaiting-interview)]">
                          Re-ask {(selected.interrupt.attempt ?? 0) + 1} of{" "}
                          {selected.interrupt.max_attempts ?? 2} on{" "}
                          {selected.interrupt.reask_fields.join(", ")}
                        </p>
                      ) : null}
                      <button
                        onClick={() => void copyInvite(selected.case_id)}
                        className="mt-4 flex w-full items-center justify-center gap-2 rounded-[var(--r-pill)] border border-glass-border px-5 py-2.5 text-[13.5px] font-medium text-text transition-all hover:border-white/25 active:scale-[0.98]"
                      >
                        {copied === selected.case_id ? (
                          <>
                            <Check size={15} weight="bold" color="var(--color-risk-low)" />
                            Invite link copied
                          </>
                        ) : (
                          <>
                            <LinkSimple size={15} weight="bold" />
                            Copy invite link
                          </>
                        )}
                      </button>
                      <p className="mt-2.5 text-[12px] leading-relaxed text-text-faint">
                        Send this to the applicant. They answer at their convenience and the
                        completed case returns to this board.
                      </p>

                      <div className="mt-5 grid gap-2.5">
                        <button
                          onClick={() => void onInterview(selected.case_id, CLEAN_FIELDS)}
                          disabled={busy}
                          className="w-full rounded-[var(--r-pill)] px-5 py-2.5 text-[13.5px] font-semibold text-[#0a0a12] transition-transform active:scale-[0.98] disabled:opacity-40"
                          style={{ background: "var(--siri-gradient)" }}
                        >
                          Low risk applicant
                        </button>
                        <button
                          onClick={() => void onInterview(selected.case_id, RISKY_FIELDS)}
                          disabled={busy}
                          className="w-full rounded-[var(--r-pill)] border border-glass-border px-5 py-2.5 text-[13.5px] font-medium text-text transition-all hover:border-white/25 active:scale-[0.98] disabled:opacity-40"
                        >
                          High risk applicant
                        </button>
                      </div>
                    </div>
                  ) : null}

                  {selected.interrupt?.type === "review" ? (
                    <div className="mt-5">
                      <p className="text-[13.5px] leading-relaxed text-text-dim">
                        This case reached the reviewer gate. A human decides.
                      </p>
                      <div className="mt-4 flex gap-2.5">
                        <button
                          onClick={() => void onDecide(selected.case_id, "approve")}
                          disabled={busy}
                          className="flex-1 rounded-[var(--r-pill)] border border-[var(--color-risk-low)]/40 px-4 py-2.5 text-[13.5px] font-medium text-[var(--color-risk-low)] transition-all hover:border-[var(--color-risk-low)]/70 active:scale-[0.98] disabled:opacity-40"
                        >
                          Approve
                        </button>
                        <button
                          onClick={() => void onDecide(selected.case_id, "reject")}
                          disabled={busy}
                          className="flex-1 rounded-[var(--r-pill)] border border-[var(--color-risk-high)]/40 px-4 py-2.5 text-[13.5px] font-medium text-[var(--color-risk-high)] transition-all hover:border-[var(--color-risk-high)]/70 active:scale-[0.98] disabled:opacity-40"
                        >
                          Reject
                        </button>
                      </div>
                    </div>
                  ) : null}

                  {selected.check_results.length > 0 ? (
                    <div className="mt-7">
                      <h3 className="text-[12px] uppercase tracking-[0.14em] text-text-faint">
                        Checks
                      </h3>
                      <ul className="mt-3 space-y-2">
                        {selected.check_results.map((chk) => (
                          <li
                            key={chk.check_name}
                            className="flex items-center justify-between text-[13px]"
                          >
                            <span style={MONO}>{chk.check_name}</span>
                            <span
                              style={{
                                color:
                                  chk.status === "clear"
                                    ? "var(--color-risk-low)"
                                    : chk.status === "hit"
                                      ? "var(--color-risk-high)"
                                      : "var(--color-risk-medium)",
                              }}
                            >
                              {chk.status}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}

                  {selected.audit.length > 0 ? (
                    <div className="mt-7">
                      <h3 className="text-[12px] uppercase tracking-[0.14em] text-text-faint">
                        Audit trail
                      </h3>
                      <ol className="mt-3 space-y-2">
                        {selected.audit.map((entry) => (
                          <li
                            key={`${entry.seq}-${entry.node}`}
                            className="flex items-baseline justify-between gap-3 text-[12.5px]"
                            style={MONO}
                          >
                            <span className="text-text-dim">
                              {String(entry.seq).padStart(2, "0")} {entry.node}
                            </span>
                            <span className="shrink-0 text-text-faint">
                              {entry.duration_ms}ms
                            </span>
                          </li>
                        ))}
                      </ol>
                    </div>
                  ) : null}
                </div>
              )}
            </section>
          </div>
        ) : null}
      </main>
    </div>
  );
}
