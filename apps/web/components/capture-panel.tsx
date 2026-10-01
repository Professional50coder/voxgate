"use client";

import { Check, CircleDashed, Minus } from "@phosphor-icons/react";

/** "source_of_funds" -> "Source of funds"; short codes stay upper-case. */
export function humanize(id: string): string {
  const words = id.replace(/_/g, " ").split(" ");
  return words
    .map((w, i) => (["uae", "dob", "pep", "id", "kyc"].includes(w) ? w.toUpperCase()
      : i === 0 ? w[0]?.toUpperCase() + w.slice(1) : w))
    .join(" ");
}

/**
 * What the agent has captured so far, filled in live as each answer is
 * understood. The point is to show the product working, not decorate it: the
 * visitor watches a spoken sentence become a structured, checked field.
 */
export function CapturePanel({
  fields,
  current,
  answers,
  skipped,
}: {
  fields: string[];
  current: string | undefined;
  answers: Record<string, string>;
  skipped: string[];
}) {
  const done = fields.filter((f) => answers[f]).length;
  return (
    <aside className="glass rounded-[var(--r-card)] p-5 text-left" aria-label="Answers captured so far">
      <div className="flex items-baseline justify-between">
        <h2 className="text-[13px] uppercase tracking-[0.14em] text-text-faint">Captured live</h2>
        <span className="text-[12.5px] text-text-dim">{done} of {fields.length}</span>
      </div>
      <div className="mt-3 h-1 overflow-hidden rounded-full bg-white/[0.06]">
        <div className="h-full rounded-full transition-[width] duration-700 ease-[var(--ease-out-expo)]"
          style={{ width: `${(100 * done) / Math.max(fields.length, 1)}%`, background: "var(--siri-gradient)" }} />
      </div>
      <ul className="mt-4 space-y-1">
        {fields.map((f) => {
          const value = answers[f];
          const isCurrent = f === current && !value;
          const isSkipped = skipped.includes(f) && !value;
          return (
            <li key={f} className={`flex items-start gap-3 rounded-[10px] px-2.5 py-2 transition-colors ${
              isCurrent ? "bg-[var(--color-siri-2)]/12" : ""}`}>
              <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center">
                {value ? <Check size={15} weight="bold" className="text-[var(--color-status-approved)]" />
                  : isSkipped ? <Minus size={15} className="text-text-faint" />
                  : <CircleDashed size={15} className={isCurrent ? "animate-spin text-[var(--color-siri-1)] [animation-duration:3s] motion-reduce:animate-none" : "text-text-faint"} />}
              </span>
              <div className="min-w-0">
                <p className={`text-[12.5px] ${isCurrent ? "text-text" : "text-text-faint"}`}>{humanize(f)}</p>
                {value ? (
                  <p key={value} className="land truncate text-[14px] font-medium text-text">{humanize(value)}</p>
                ) : isSkipped ? (
                  <p className="text-[13px] text-text-faint">Left for a colleague</p>
                ) : isCurrent ? (
                  <p className="text-[13px] text-text-dim">Listening…</p>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
