"use client";

import { MagnifyingGlass, Storefront } from "@phosphor-icons/react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { humanize } from "@/components/capture-panel";
import {
  type Analytics, type SearchHit, type StoreAgent, getAnalytics, getStore, searchTranscripts,
} from "@/lib/api";

const pct = (n: number | null | undefined) => (n == null ? "–" : `${Math.round(n * 100)}%`);
const secs = (n: number | null) => (n == null ? "–" : n < 90 ? `${Math.round(n)} s` : `${(n / 60).toFixed(1)} min`);

/** Per-agent performance, interview search and the agent store, for operators. */
export function Insights() {
  const [data, setData] = useState<Analytics | null>(null);
  const [store, setStore] = useState<StoreAgent[]>([]);

  useEffect(() => {
    getAnalytics().then(setData).catch(() => setData(null));
    getStore().then(setStore).catch(() => setStore([]));
  }, []);

  return (
    <div className="mt-14 space-y-14">
      <section>
        <h2 className="text-xl font-semibold tracking-tight">How each agent is performing</h2>
        <p className="mt-1 text-[13.5px] text-text-dim">
          Completion, automation and where applicants get stuck, from real cases and transcripts.
        </p>
        <div className="glass mt-5 overflow-x-auto rounded-[var(--r-card)]">
          <table className="w-full min-w-[760px] text-left text-[13px]">
            <thead className="text-[11.5px] uppercase tracking-[0.1em] text-text-faint">
              <tr className="border-b border-glass-border-soft">
                {["Agent", "Cases", "Completed", "Auto-approved", "Reviewed", "Median length", "Stuck on"].map((h) => (
                  <th key={h} className="px-4 py-3 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(data?.agents ?? []).map((a) => (
                <tr key={a.pack_id} className="border-b border-glass-border-soft last:border-0">
                  <td className="px-4 py-3 font-medium">{a.name}</td>
                  <td className="px-4 py-3">{a.cases}</td>
                  <td className="px-4 py-3">{pct(a.completion_rate)}</td>
                  <td className="px-4 py-3">{a.auto_approved} <span className="text-text-faint">({pct(a.automation_rate)})</span></td>
                  <td className="px-4 py-3">{a.human_reviewed}</td>
                  <td className="px-4 py-3">{secs(a.median_interview_seconds)}</td>
                  <td className="px-4 py-3 text-text-dim">
                    {a.most_reasked.length ? a.most_reasked.map(([f, n]) => `${humanize(f)} (${n})`).join(", ") : "–"}
                  </td>
                </tr>
              ))}
              {data && data.agents.length === 0 ? (
                <tr><td colSpan={7} className="px-4 py-8 text-center text-text-faint">No cases yet. Run an interview to see numbers here.</td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>

      <TranscriptSearch />

      <section>
        <h2 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
          <Storefront size={20} className="text-[var(--color-siri-1)]" /> Agent store
        </h2>
        <p className="mt-1 text-[13.5px] text-text-dim">
          Every agent you can run. Agents published from the builder are saved to the database and
          live on every server instantly.
        </p>
        <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {store.map((s) => (
            <div key={s.pack_id} className="rounded-[var(--r-card)] border border-glass-border-soft bg-[var(--color-surface-2)] p-4">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-[14.5px] font-semibold">{s.agent} · {s.display_name}</p>
                  <p className="text-[12px] text-text-faint">{s.questions} questions · reviewed by a {s.gate_role}</p>
                </div>
                <span className={`shrink-0 rounded-[var(--r-pill)] px-2 py-0.5 text-[11px] ${
                  s.source === "published" ? "bg-[var(--color-siri-3)]/20 text-[var(--color-siri-3)]" : "bg-white/[0.06] text-text-dim"}`}>
                  {s.source === "published" ? `by ${s.published_by ?? "operator"}` : "built in"}
                </span>
              </div>
              <Link href={`/apply?pack=${s.pack_id}`} className="mt-3 inline-block text-[12.5px] text-[var(--color-siri-1)] hover:underline">
                Try this agent →
              </Link>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function TranscriptSearch() {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    if (q.trim().length < 2) return;
    setBusy(true);
    try {
      setHits((await searchTranscripts(q.trim())).hits);
    } catch {
      setHits([]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <h2 className="text-xl font-semibold tracking-tight">Search every interview</h2>
      <p className="mt-1 text-[13.5px] text-text-dim">Find any phrase said in any interview, by either side.</p>
      <div className="mt-5 flex max-w-[640px] items-center gap-2 rounded-[var(--r-pill)] border border-glass-border bg-[var(--color-surface-2)] p-1.5 focus-within:border-[var(--color-siri-2)]">
        <MagnifyingGlass size={17} className="ml-2.5 shrink-0 text-text-faint" />
        <input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") void run(); }}
          placeholder='e.g. "source of funds" or "my brother"' aria-label="Search interviews"
          className="h-9 w-full min-w-0 bg-transparent text-[14px] outline-none placeholder:text-text-faint" />
        <button onClick={() => void run()} disabled={busy || q.trim().length < 2}
          className="rounded-[var(--r-pill)] px-4 py-2 text-[13px] font-semibold text-[#0a0a12] disabled:opacity-40"
          style={{ background: "var(--siri-gradient)" }}>
          Search
        </button>
      </div>
      {hits ? (
        <ul className="mt-4 max-w-[760px] space-y-2">
          {hits.length === 0 ? <li className="text-[13.5px] text-text-faint">No interview mentions that.</li> : null}
          {hits.map((h) => (
            <li key={`${h.case_id}-${h.session_id}-${h.turn_no}`} className="rounded-[10px] border border-glass-border-soft bg-[var(--color-surface-2)] px-4 py-3">
              <p className="text-[13.5px]"><span className="text-text-faint">{h.role === "agent" ? "Agent" : "Applicant"}:</span> {h.text}</p>
              <Link href={`/console?case=${h.case_id}`} className="mt-1 inline-block text-[12px] text-[var(--color-siri-1)] hover:underline">
                Open case {h.case_id.slice(0, 8)} →
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
