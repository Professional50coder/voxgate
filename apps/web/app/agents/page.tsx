"use client";

import {
  ArrowRight,
  Briefcase,
  Buildings,
  Check,
  Copy,
  FirstAid,
  Headset,
  House,
  ShieldCheck,
  UserCircle,
  Users,
} from "@phosphor-icons/react";
import Link from "next/link";
import type { ReactNode } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { AgentComposer } from "@/components/agent-composer";
import { AppNav } from "@/components/app-nav";
import { Reveal } from "@/components/reveal";
import { SpotlightCard } from "@/components/spotlight-card";
import { ApiUnreachable, type Pack, createCase, getPacks } from "@/lib/api";

const MONO = { fontFamily: "var(--font-geist-mono), monospace" } as const;

/**
 * Presentation metadata per pack. Everything functional (fields, questions,
 * gate role) comes from the API, so this map only carries what the backend has
 * no opinion about: an icon, a one-line pitch, and a category.
 *
 * A pack with no entry here still renders, with a neutral icon. Adding a pack
 * must never require editing the frontend.
 */
const PRESENTATION: Record<
  string,
  { icon: ReactNode; category: string; pitch: string }
> = {
  "kyc-uae": {
    icon: <ShieldCheck size={22} weight="duotone" />,
    category: "Financial compliance",
    pitch:
      "Onboards a client for a regulated fintech, screening name, nationality and funding source before anyone reviews it.",
  },
  "sales-discovery": {
    icon: <Briefcase size={22} weight="duotone" />,
    category: "Revenue",
    pitch:
      "Runs a discovery call that never pitches, so a seller only spends an hour on deals with real budget and a real timeline.",
  },
  "realestate-lead": {
    icon: <House size={22} weight="duotone" />,
    category: "Property",
    pitch:
      "Qualifies a property enquiry on financing and timeline before an agent books a viewing.",
  },
  "claim-fnol": {
    icon: <Buildings size={22} weight="duotone" />,
    category: "Insurance",
    pitch:
      "Takes a first notice of loss calmly and completely, flagging late reports and narrative gaps for an adjuster.",
  },
  "patient-intake": {
    icon: <FirstAid size={22} weight="duotone" />,
    category: "Healthcare",
    pitch:
      "Collects symptoms and history without diagnosing, escalating red-flag presentations straight to a clinician.",
  },
  "loan-intake": {
    icon: <UserCircle size={22} weight="duotone" />,
    category: "Lending",
    pitch:
      "Captures income, obligations and purpose, and never hints at whether the application will succeed.",
  },
  "tenant-screening": {
    icon: <House size={22} weight="duotone" />,
    category: "Property",
    pitch:
      "Screens a tenancy application on affordability and history, without touching protected characteristics.",
  },
  "support-triage": {
    icon: <Headset size={22} weight="duotone" />,
    category: "Customer support",
    pitch:
      "Triages an incoming issue on real impact, and hears churn language before a human does.",
  },
  "recruit-screen": {
    icon: <Users size={22} weight="duotone" />,
    category: "Hiring",
    pitch:
      "Runs a first-round screen on experience, notice and expectations, staying neutral throughout.",
  },
};

const FALLBACK = {
  icon: <UserCircle size={22} weight="duotone" />,
  category: "Custom",
  pitch: "A scenario pack defining its own questions, screening and scoring.",
};

export default function AgentLibrary() {
  const [packs, setPacks] = useState<Pack[]>([]);
  const [offline, setOffline] = useState(false);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Pack | null>(null);
  const [invite, setInvite] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [copied, setCopied] = useState(false);
  const [filter, setFilter] = useState<string>("All");

  const loadPacks = useCallback(() => {
    getPacks()
      .then(setPacks)
      .catch((err) => {
        if (err instanceof ApiUnreachable) setOffline(true);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadPacks();
  }, [loadPacks]);

  const categories = useMemo(() => {
    const found = new Set(packs.map((p) => (PRESENTATION[p.pack_id] ?? FALLBACK).category));
    return ["All", ...[...found].sort()];
  }, [packs]);

  const visible = useMemo(
    () =>
      filter === "All"
        ? packs
        : packs.filter((p) => (PRESENTATION[p.pack_id] ?? FALLBACK).category === filter),
    [packs, filter],
  );

  async function generateInvite(pack: Pack) {
    setCreating(true);
    setCopied(false);
    try {
      const created = await createCase(pack.pack_id);
      setInvite(`${window.location.origin}/apply/${created.case_id}`);
    } catch {
      setInvite(null);
    } finally {
      setCreating(false);
    }
  }

  async function copyInvite() {
    if (!invite) return;
    try {
      await navigator.clipboard.writeText(invite);
    } catch {
      window.prompt("Copy this invite link", invite);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="min-h-[100dvh]">
      <AppNav />

      <main className="mx-auto max-w-[1200px] px-6 py-12">
        <Reveal>
          <h1 className="max-w-[20ch] text-3xl font-semibold leading-[1.12] tracking-tight md:text-4xl">
            Every agent is a folder of Python.
          </h1>
          <p className="mt-5 max-w-[64ch] text-[15px] leading-relaxed text-text-dim">
            Each card is a scenario pack: its own schema, its own screening checks, its own
            weighted scorecard and its own question phrasings. Adding one touches no
            platform code, and a shared conformance suite proves it. Pick one, generate a
            link, and the completed interview lands on your board.
          </p>
        </Reveal>

        <Reveal delay={0.08}>
          <div className="mt-10">
            <AgentComposer onPublished={loadPacks} />
          </div>
        </Reveal>

        {offline ? (
          <p className="mt-10 rounded-[var(--r-card)] border border-[var(--color-status-needs-attention)]/35 bg-[var(--color-surface-2)] px-6 py-5 text-[14px] text-text-dim">
            Backend is not running, so the library cannot load. Start it with{" "}
            <code style={MONO}>uv run uvicorn voxgate.service.app:app</code>.
          </p>
        ) : null}

        {loading ? (
          <div className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <div
                key={i}
                className="h-[210px] animate-pulse rounded-[var(--r-card)] bg-[var(--color-surface-2)]"
              />
            ))}
          </div>
        ) : null}

        {!loading && !offline ? (
          <>
            <h2 className="mt-14 text-[17px] font-semibold tracking-tight">
              Or start from one that exists
            </h2>
            <div className="mt-5 flex flex-wrap gap-2">
              {categories.map((c) => (
                <button
                  key={c}
                  onClick={() => setFilter(c)}
                  aria-pressed={filter === c}
                  className={`rounded-[var(--r-pill)] border px-4 py-1.5 text-[13px] transition-all ${
                    filter === c
                      ? "border-[var(--color-siri-2)]/60 bg-[var(--color-glass)] text-text"
                      : "border-glass-border-soft text-text-dim hover:border-white/20 hover:text-text"
                  }`}
                >
                  {c}
                </button>
              ))}
            </div>

            <div className="mt-8 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
              {visible.map((pack, i) => {
                const meta = PRESENTATION[pack.pack_id] ?? FALLBACK;
                return (
                  <Reveal key={pack.pack_id} delay={Math.min(i, 6) * 0.05}>
                    <SpotlightCard className="h-full border border-glass-border-soft bg-[var(--color-surface-2)]">
                      <article className="flex h-full flex-col p-6">
                        <div className="flex items-start justify-between gap-3">
                          <span style={{ color: "var(--color-siri-1)" }}>{meta.icon}</span>
                          <span className="text-[11px] uppercase tracking-[0.14em] text-text-faint">
                            {meta.category}
                          </span>
                        </div>

                        <h2 className="mt-5 text-[16px] font-semibold leading-snug">
                          {pack.display_name}
                        </h2>
                        <p
                          className="mt-1.5 text-[12px] text-text-faint"
                          style={MONO}
                        >
                          {pack.pack_id}
                        </p>

                        <p className="mt-4 flex-1 text-[13.5px] leading-relaxed text-text-dim">
                          {meta.pitch}
                        </p>

                        <dl className="mt-5 flex flex-wrap gap-x-6 gap-y-1.5 text-[12px] text-text-faint">
                          <div className="flex gap-1.5">
                            <dt>Questions</dt>
                            <dd className="text-text-dim">{pack.fields.length}</dd>
                          </div>
                          <div className="flex gap-1.5">
                            <dt>Gate</dt>
                            <dd className="text-text-dim">{pack.gate_role}</dd>
                          </div>
                        </dl>

                        <button
                          onClick={() => {
                            setSelected(pack);
                            setInvite(null);
                          }}
                          className="mt-6 inline-flex items-center justify-center gap-2 rounded-[var(--r-pill)] border border-glass-border px-4 py-2.5 text-[13.5px] font-medium text-text transition-all hover:border-white/25 active:scale-[0.98]"
                        >
                          Configure and invite
                          <ArrowRight size={14} weight="bold" />
                        </button>
                      </article>
                    </SpotlightCard>
                  </Reveal>
                );
              })}
            </div>
          </>
        ) : null}
      </main>

      {/* Customizer. A dialog rather than a route, so the library stays in place
          behind it and a generated link is never one back-button from lost. */}
      {selected ? (
        <div
          className="fixed inset-0 z-[70] grid place-items-center bg-black/70 p-6"
          role="dialog"
          aria-modal="true"
          aria-label={`Configure ${selected.display_name}`}
          onClick={(e) => {
            if (e.target === e.currentTarget) setSelected(null);
          }}
        >
          <div className="glass max-h-[86dvh] w-full max-w-[560px] overflow-y-auto rounded-[var(--r-card)] p-7">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-[18px] font-semibold">{selected.display_name}</h2>
                <p className="mt-1 text-[12.5px] text-text-faint" style={MONO}>
                  {selected.pack_id}
                </p>
              </div>
              <button
                onClick={() => setSelected(null)}
                aria-label="Close"
                className="rounded-full px-2 text-[20px] leading-none text-text-faint transition-colors hover:text-text"
              >
                &times;
              </button>
            </div>

            <section className="mt-6">
              <h3 className="text-[12px] uppercase tracking-[0.14em] text-text-faint">
                What it asks
              </h3>
              <ol className="mt-3 space-y-2.5">
                {selected.fields.map((f, i) => (
                  <li key={f} className="flex gap-3 text-[13.5px] leading-relaxed">
                    <span className="w-5 shrink-0 text-text-faint" style={MONO}>
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <span className="text-text-dim">
                      {selected.reask_hints?.[f] ?? f.replace(/_/g, " ")}
                    </span>
                  </li>
                ))}
              </ol>
              <p className="mt-4 text-[12.5px] leading-relaxed text-text-faint">
                These come from the pack&apos;s own <code style={MONO}>REASK_HINTS</code>,
                so editing the Python changes what the agent says. Nothing is duplicated
                here.
              </p>
            </section>

            <section className="mt-7 border-t border-glass-border-soft pt-6">
              <h3 className="text-[12px] uppercase tracking-[0.14em] text-text-faint">
                Escalation
              </h3>
              <p className="mt-3 text-[13.5px] leading-relaxed text-text-dim">
                High-risk cases, and anything a screening check flags, pause for a{" "}
                <span className="text-text">{selected.gate_role}</span>. Everything else
                completes without a human.
              </p>
            </section>

            <section className="mt-7 border-t border-glass-border-soft pt-6">
              {invite ? (
                <>
                  <h3 className="text-[12px] uppercase tracking-[0.14em] text-text-faint">
                    Invite link
                  </h3>
                  <p
                    className="mt-3 break-all rounded-[var(--r-input)] border border-glass-border-soft bg-[#05070e] p-3.5 text-[12.5px] text-text-dim"
                    style={MONO}
                  >
                    {invite}
                  </p>
                  <div className="mt-4 flex flex-wrap gap-2.5">
                    <button
                      onClick={() => void copyInvite()}
                      className="inline-flex items-center gap-2 rounded-[var(--r-pill)] px-5 py-2.5 text-[13.5px] font-semibold text-[#0a0a12] transition-transform active:scale-[0.98]"
                      style={{ background: "var(--siri-gradient)" }}
                    >
                      {copied ? <Check size={14} weight="bold" /> : <Copy size={14} weight="bold" />}
                      {copied ? "Copied" : "Copy link"}
                    </button>
                    <Link
                      href={invite.replace(window.location.origin, "")}
                      className="inline-flex items-center gap-2 rounded-[var(--r-pill)] border border-glass-border px-5 py-2.5 text-[13.5px] font-medium text-text transition-all hover:border-white/25"
                    >
                      Open it yourself
                    </Link>
                  </div>
                  <p className="mt-4 text-[12.5px] leading-relaxed text-text-faint">
                    Send this to the person being interviewed. They answer whenever suits
                    them and the completed case appears on your board.
                  </p>
                </>
              ) : (
                <>
                  <button
                    onClick={() => void generateInvite(selected)}
                    disabled={creating}
                    className="w-full rounded-[var(--r-pill)] py-3 text-[14.5px] font-semibold text-[#0a0a12] transition-transform active:scale-[0.98] disabled:opacity-50"
                    style={{ background: "var(--siri-gradient)" }}
                  >
                    {creating ? "Creating case" : "Generate invite link"}
                  </button>
                  <p className="mt-3 text-[12.5px] leading-relaxed text-text-faint">
                    This opens a real case against{" "}
                    <span style={MONO}>{selected.pack_id}</span> and returns a link tied to
                    it.
                  </p>
                </>
              )}
            </section>
          </div>
        </div>
      ) : null}
    </div>
  );
}
