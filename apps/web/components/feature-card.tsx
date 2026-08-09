import type { Icon } from "@phosphor-icons/react";
import type { ReactNode } from "react";

/**
 * The page's one card shape.
 *
 * Written as a single primitive on purpose. The landing page previously carried
 * four different card treatments — a hairline grid, a bento with two cell
 * shapes, a definition list and a split row — and the eye reads that as four
 * unrelated systems rather than one product. One shape, repeated at three
 * spans, is what makes a dense page feel designed instead of assembled.
 *
 * A SERVER component, deliberately, and that is a performance decision as much
 * as an architectural one:
 *
 *   - Passing an icon component across a client boundary is not allowed at all
 *     ("Functions cannot be passed directly to Client Components"), so a
 *     client card would force either a string-to-icon lookup table or a
 *     pre-rendered element prop. Both are worse to read than `icon={Gavel}`.
 *   - The hover lift does not need JavaScript. As CSS it costs nothing at
 *     runtime, cannot stutter, and needs no hydration — this page renders
 *     twenty of these cards, so a spring-per-card would ship twenty
 *     subscriptions to do what one transition does.
 *
 * Motion budget: `transform` and `opacity` only, both compositor properties. No
 * animated `box-shadow`, `filter` or `height` anywhere — those relayout or
 * repaint every frame and are what actually makes a dense page stutter while
 * scrolling. `motion-reduce:` disables the lift for anyone who has asked for
 * less movement.
 */

export type Tone = "ice" | "periwinkle" | "lavender" | "mint";

export const TONE: Record<Tone, string> = {
  ice: "var(--color-siri-1)",
  periwinkle: "var(--color-siri-2)",
  lavender: "var(--color-siri-3)",
  mint: "var(--color-risk-low)",
};

export function FeatureCard({
  icon: IconGlyph,
  title,
  children,
  tone = "periwinkle",
  featured = false,
  meta,
  className = "",
}: {
  icon: Icon;
  title: string;
  children: ReactNode;
  tone?: Tone;
  /** One card per grid may carry the gradient wash. More than one and it stops
   *  meaning "start here". */
  featured?: boolean;
  /** Optional mono chips along the bottom — the concrete nouns behind the claim. */
  meta?: string[];
  className?: string;
}) {
  const accent = TONE[tone];

  return (
    <article
      className={`group/card relative flex h-full flex-col overflow-hidden rounded-[var(--r-card)] border border-glass-border-soft bg-[var(--color-surface-2)] p-7 transition-[transform,border-color] duration-300 ease-[var(--ease-out-expo)] hover:-translate-y-[3px] hover:border-glass-border motion-reduce:transition-none motion-reduce:hover:translate-y-0 md:p-8 ${className}`}
    >
      {/* The featured wash. A static gradient, never animated: a moving gradient
          behind text is the most expensive thing you can put on a scrolling
          page for the least benefit. */}
      {featured ? (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute -top-24 -left-16 h-56 w-72 rounded-full opacity-70"
          style={{
            background: `radial-gradient(closest-side, ${accent}38, transparent 72%)`,
          }}
        />
      ) : null}

      <span
        aria-hidden="true"
        className="relative inline-flex h-11 w-11 items-center justify-center rounded-[11px] border border-glass-border-soft"
        style={{ background: "rgba(255,255,255,0.04)" }}
      >
        <IconGlyph size={20} weight="duotone" color={accent} />
      </span>

      <h3 className="relative mt-6 text-[17px] font-semibold leading-snug tracking-tight text-text">
        {title}
      </h3>
      <p className="relative mt-3 text-[14px] leading-relaxed text-text-dim">{children}</p>

      {meta?.length ? (
        <ul
          className="relative mt-auto flex flex-wrap gap-x-5 gap-y-1.5 pt-7 text-[11.5px] text-text-faint"
          style={{ fontFamily: "var(--font-geist-mono), monospace" }}
        >
          {meta.map((m) => (
            <li key={m}>{m}</li>
          ))}
        </ul>
      ) : null}
    </article>
  );
}

/**
 * A number and what it counts. Used once, as a band — a page that argues from
 * engineering has to be willing to show the figures.
 */
export function StatCard({
  value,
  label,
  tone = "periwinkle",
}: {
  value: string;
  label: string;
  tone?: Tone;
}) {
  return (
    <div className="rounded-[var(--r-card)] border border-glass-border-soft bg-[var(--color-surface-2)] p-6 text-center">
      <div
        className="text-[30px] font-bold leading-none tracking-tight md:text-[36px]"
        style={{ color: TONE[tone] }}
      >
        {value}
      </div>
      <div className="mt-2.5 text-[12.5px] leading-snug text-text-dim">{label}</div>
    </div>
  );
}
