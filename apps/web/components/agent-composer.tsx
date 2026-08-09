"use client";

import { Check, Copy, Shuffle, Sparkle, WarningCircle } from "@phosphor-icons/react";
import { useState } from "react";

import {
  ApiUnreachable,
  NotAuthorized,
  SURPRISE_SEEDS,
  type Case,
  createCase,
  draftPack,
  publishPack,
} from "@/lib/api";

/** One place that turns a thrown value into something worth reading. */
function describeError(err: unknown, unreachable: string): string {
  if (err instanceof NotAuthorized) {
    return err.status === 401
      ? "Authoring an agent is operator-only. Add your key on the console and try again."
      : "That operator key was not accepted.";
  }
  if (err instanceof ApiUnreachable || err instanceof TypeError) return unreachable;
  return err instanceof Error ? err.message : String(err);
}

const MONO = { fontFamily: "var(--font-geist-mono), monospace" } as const;

type DraftField = {
  name: string;
  type: "enum" | "text";
  question: string;
  weight: number;
  values: { value: string; risk: number }[];
};

type DraftCheck = {
  name: string;
  field: string;
  hit_phrases: string[];
  review_phrases: string[];
};

type Draft = {
  pack_id: string;
  display_name: string;
  gate_role: string;
  persona: string;
  gate_reason: string;
  fields: DraftField[];
  checks: DraftCheck[];
  warnings: string[];
  spec: Record<string, unknown>;
};

const EXAMPLES = [
  "A dental clinic taking new patient enquiries. We need to know what the problem is, whether they are in pain right now, whether they have been here before, and when they can come in.",
  "A commercial solar installer qualifying leads. We need roof type, rough monthly electricity spend, whether they own the building, and their timeline.",
  "A recruitment agency screening contractors. We need their specialism, day rate expectation, notice period, and whether they have the right to work here.",
];

/**
 * Describe a business, get a drafted agent.
 *
 * The draft is a proposal. Nothing is created until a human has read the
 * questions, which is why the review step shows every question and every
 * warning before the launch control appears at all.
 */
export function AgentComposer({ onPublished }: { onPublished?: () => void } = {}) {
  const [description, setDescription] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [drafting, setDrafting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [invite, setInvite] = useState<string | null>(null);
  const [launching, setLaunching] = useState(false);
  const [copied, setCopied] = useState(false);
  const [publishedId, setPublished] = useState<string | null>(null);
  const [lastSeed, setLastSeed] = useState<string | null>(null);

  /**
   * `text` is a parameter rather than being read from state, because "Surprise
   * me" sets the description and drafts in one action — and a setState is not
   * visible to the same tick that scheduled it, so reading state here would
   * have drafted the PREVIOUS description every time.
   */
  async function generate(text: string = description) {
    setDrafting(true);
    setError(null);
    setDraft(null);
    setInvite(null);
    setPublished(null);
    try {
      setDraft((await draftPack(text)) as unknown as Draft);
    } catch (err) {
      setError(describeError(err, "Backend unreachable. Start it and try again."));
    } finally {
      setDrafting(false);
    }
  }

  function surpriseMe() {
    // Never the same one twice in a row. With twelve seeds, a plain random pick
    // repeats often enough to look broken to someone pressing it twice.
    const pool = SURPRISE_SEEDS.filter((s) => s !== lastSeed);
    const pick = pool[Math.floor(Math.random() * pool.length)];
    setLastSeed(pick);
    setDescription(pick);
    void generate(pick);
  }

  /**
   * Publish the draft as a real pack, then open a case against it.
   *
   * Publishing writes the five pack files and compiles a graph, so the agent
   * is live in the library immediately. The case that follows is against the
   * NEW pack, not a stand-in.
   */
  async function launch(draft: Draft) {
    setLaunching(true);
    setError(null);
    try {
      const published = await publishPack(draft.spec, true);
      setPublished(published.pack_id);

      const created: Case = await createCase(published.pack_id);
      setInvite(`${window.location.origin}/apply/${created.case_id}`);
      onPublished?.();
    } catch (err) {
      setError(describeError(err, "Backend unreachable."));
    } finally {
      setLaunching(false);
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
    <section className="rounded-[var(--r-card)] border border-glass-border-soft bg-[var(--color-surface-2)] p-7 md:p-9">
      <div className="flex items-start gap-3.5">
        <Sparkle size={22} weight="duotone" color="var(--color-siri-3)" />
        <div>
          <h2 className="text-[17px] font-semibold tracking-tight">
            Describe your business. Get an agent.
          </h2>
          <p className="mt-2 max-w-[68ch] text-[13.5px] leading-relaxed text-text-dim">
            Say what you do and what the agent should find out. You get a full
            question flow to review before anything runs. The model fills in a fixed
            structure; it never writes code and never decides an outcome.
          </p>
        </div>
      </div>

      <textarea
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        rows={4}
        placeholder="We run a veterinary clinic. When someone calls about their pet we need to know what animal it is, what the symptom is, how urgent it seems, and whether they are already registered with us."
        aria-label="Describe your business and what the agent should find out"
        className="mt-6 w-full resize-y rounded-[var(--r-input)] border border-glass-border bg-[#05070e] p-4 text-[14px] leading-relaxed text-text outline-none placeholder:text-text-faint focus:border-[var(--color-siri-2)]"
      />

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className="text-[12px] text-text-faint">Try:</span>
        {["Dental clinic", "Solar installer", "Contractor screening"].map((label, i) => (
          <button
            key={label}
            onClick={() => setDescription(EXAMPLES[i])}
            className="rounded-[var(--r-pill)] border border-glass-border-soft px-3 py-1 text-[12px] text-text-dim transition-all hover:border-white/25 hover:text-text"
          >
            {label}
          </button>
        ))}
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-3">
        <button
          onClick={() => void generate()}
          disabled={drafting || description.trim().length < 20}
          className="inline-flex items-center gap-2 rounded-[var(--r-pill)] px-6 py-3 text-[14.5px] font-semibold text-[#0a0a12] transition-transform active:scale-[0.98] disabled:opacity-40"
          style={{ background: "var(--siri-gradient)" }}
        >
          <Sparkle size={15} weight="fill" />
          {drafting ? "Drafting the agent" : "Draft the agent"}
        </button>

        {/* Surprise me. For the visitor who has no idea what to type — which is
            most first-time visitors, and the reason an empty textarea is a bad
            first impression for a product whose whole claim is breadth. It
            fills the box AND drafts, because stopping to let someone read a
            description they did not write teaches them nothing. */}
        <button
          onClick={surpriseMe}
          disabled={drafting}
          className="inline-flex items-center gap-2 rounded-[var(--r-pill)] border border-glass-border-soft px-5 py-3 text-[14px] font-medium text-text transition-colors hover:border-white/25 active:scale-[0.98] disabled:opacity-40"
        >
          <Shuffle size={15} weight="bold" color="var(--color-siri-1)" />
          Surprise me
        </button>
      </div>
      {description.trim().length > 0 && description.trim().length < 20 ? (
        <p className="mt-2.5 text-[12.5px] text-text-faint">
          A sentence or two more. The draft is only as good as the description.
        </p>
      ) : null}

      {error ? (
        <p className="mt-5 rounded-[var(--r-input)] border border-[var(--color-status-rejected)]/35 px-4 py-3 text-[13px] text-[var(--color-status-rejected)]">
          {error}
        </p>
      ) : null}

      {drafting ? (
        <div className="mt-7 space-y-2.5">
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-11 animate-pulse rounded-[var(--r-input)] bg-[var(--color-glass)]"
            />
          ))}
        </div>
      ) : null}

      {draft ? (
        <div className="mt-8 border-t border-glass-border-soft pt-7">
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <h3 className="text-[16px] font-semibold">{draft.display_name}</h3>
            <span className="text-[12.5px] text-text-faint" style={MONO}>
              {draft.pack_id}
            </span>
          </div>
          <p className="mt-2.5 max-w-[70ch] text-[13.5px] leading-relaxed text-text-dim">
            {draft.persona}
          </p>

          {/* Warnings sit above the questions on purpose: they are the part a
              reviewer must actually read before approving. */}
          {draft.warnings.length > 0 ? (
            <ul className="mt-5 space-y-2">
              {draft.warnings.map((w) => (
                <li
                  key={w}
                  className="flex items-start gap-2.5 rounded-[var(--r-input)] border border-[var(--color-status-awaiting-interview)]/30 px-3.5 py-2.5 text-[12.5px] leading-relaxed text-[var(--color-status-awaiting-interview)]"
                >
                  <WarningCircle size={15} weight="fill" className="mt-[1px] shrink-0" />
                  {w}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-5 text-[12.5px] text-[var(--color-risk-low)]">
              No warnings. No protected characteristics, no secrets, every check
              points at a real field.
            </p>
          )}

          <h4 className="mt-7 text-[12px] uppercase tracking-[0.14em] text-text-faint">
            Questions it will ask
          </h4>
          <ol className="mt-4 space-y-4">
            {draft.fields.map((f, i) => (
              <li key={f.name} className="flex gap-3.5">
                <span className="w-5 shrink-0 pt-[3px] text-[12px] text-text-faint" style={MONO}>
                  {String(i + 1).padStart(2, "0")}
                </span>
                <div className="min-w-0">
                  <p className="text-[14px] leading-snug text-text">{f.question}</p>
                  <p className="mt-1.5 text-[11.5px] text-text-faint" style={MONO}>
                    {f.name}
                  </p>
                  {f.type === "enum" ? (
                    <ul className="mt-2 flex flex-wrap gap-1.5">
                      {f.values.map((v) => (
                        <li
                          key={v.value}
                          title={`risk ${v.risk}`}
                          className="rounded-[var(--r-pill)] border px-2.5 py-[3px] text-[11px]"
                          style={{
                            ...MONO,
                            borderColor:
                              v.risk >= 0.7
                                ? "color-mix(in oklab, var(--color-risk-high) 45%, transparent)"
                                : v.risk >= 0.4
                                  ? "color-mix(in oklab, var(--color-risk-medium) 40%, transparent)"
                                  : "color-mix(in oklab, var(--color-risk-low) 35%, transparent)",
                            color:
                              v.risk >= 0.7
                                ? "var(--color-risk-high)"
                                : v.risk >= 0.4
                                  ? "var(--color-risk-medium)"
                                  : "var(--color-risk-low)",
                          }}
                        >
                          {v.value}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-1.5 text-[11.5px] text-text-faint">free text</p>
                  )}
                </div>
              </li>
            ))}
          </ol>

          {draft.checks.length > 0 ? (
            <>
              <h4 className="mt-8 text-[12px] uppercase tracking-[0.14em] text-text-faint">
                What it escalates on
              </h4>
              <ul className="mt-3.5 space-y-2.5">
                {draft.checks.map((c) => (
                  <li key={c.name} className="text-[13px] leading-relaxed text-text-dim">
                    <span className="text-text" style={MONO}>
                      {c.name}
                    </span>{" "}
                    reads <span style={MONO}>{c.field}</span>
                    {c.hit_phrases.length > 0 ? (
                      <> and flags {c.hit_phrases.slice(0, 5).join(", ")}</>
                    ) : null}
                  </li>
                ))}
              </ul>
              <p className="mt-4 text-[13px] text-text-dim">
                Escalated cases go to a{" "}
                <span className="text-text">{draft.gate_role}</span>, for{" "}
                {draft.gate_reason}.
              </p>
            </>
          ) : null}

          <div className="mt-8 border-t border-glass-border-soft pt-6">
            {invite ? (
              <>
                {publishedId ? (
                  <p className="mb-4 text-[13px] text-[var(--color-risk-low)]">
                    Published as <span style={MONO}>{publishedId}</span>. It is live in
                    the library below and running as a compiled graph.
                  </p>
                ) : null}
                <p
                  className="break-all rounded-[var(--r-input)] border border-glass-border-soft bg-[#05070e] p-3.5 text-[12.5px] text-text-dim"
                  style={MONO}
                >
                  {invite}
                </p>
                <button
                  onClick={() => void copyInvite()}
                  className="mt-4 inline-flex items-center gap-2 rounded-[var(--r-pill)] px-5 py-2.5 text-[13.5px] font-semibold text-[#0a0a12] transition-transform active:scale-[0.98]"
                  style={{ background: "var(--siri-gradient)" }}
                >
                  {copied ? <Check size={14} weight="bold" /> : <Copy size={14} weight="bold" />}
                  {copied ? "Copied" : "Copy invite link"}
                </button>
              </>
            ) : (
              <>
                <button
                  onClick={() => void launch(draft)}
                  disabled={launching}
                  className="rounded-[var(--r-pill)] px-6 py-3 text-[14.5px] font-semibold text-[#0a0a12] transition-transform active:scale-[0.98] disabled:opacity-50"
                  style={{ background: "var(--siri-gradient)" }}
                >
                  {launching ? "Publishing the agent" : "Looks right, publish it"}
                </button>
                {/* Honesty beats a nicer-sounding button. Writing a new pack to
                    disk is a server-side deploy, and this UI does not do it. */}
                <p className="mt-3.5 max-w-[68ch] text-[12.5px] leading-relaxed text-text-faint">
                  This writes the five pack files, compiles a graph, and adds the
                  agent to the library permanently. You get an invite link for a
                  live case against it.
                </p>
              </>
            )}
          </div>
        </div>
      ) : null}
    </section>
  );
}
