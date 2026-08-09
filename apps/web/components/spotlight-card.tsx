"use client";

import { motion, useMotionTemplate, useMotionValue, useReducedMotion } from "motion/react";
import type { ReactNode } from "react";

/**
 * Card whose border and surface illuminate under the cursor.
 *
 * Pointer position is held in motion values and piped straight into a CSS
 * variable, never into React state. State would re-render the whole subtree on
 * every mousemove, which is what makes most hover-spotlight implementations
 * stutter on mid-range hardware.
 *
 * The light follows the pointer without moving the click target, so it adds
 * feedback without the Fitts's-law penalty that magnetic-cursor effects carry.
 */
export function SpotlightCard({
  children,
  className = "",
  radius = 340,
}: {
  children: ReactNode;
  className?: string;
  radius?: number;
}) {
  const reduce = useReducedMotion();
  const mx = useMotionValue(-9999);
  const my = useMotionValue(-9999);

  const surface = useMotionTemplate`radial-gradient(${radius}px circle at ${mx}px ${my}px, rgba(200,123,255,0.14), transparent 70%)`;
  const border = useMotionTemplate`radial-gradient(${radius}px circle at ${mx}px ${my}px, rgba(200,123,255,0.55), rgba(255,255,255,0.06) 45%)`;

  function onMove(e: React.MouseEvent<HTMLDivElement>) {
    if (reduce) return;
    const rect = e.currentTarget.getBoundingClientRect();
    mx.set(e.clientX - rect.left);
    my.set(e.clientY - rect.top);
  }

  function onLeave() {
    mx.set(-9999);
    my.set(-9999);
  }

  return (
    <div
      onMouseMove={onMove}
      onMouseLeave={onLeave}
      className={`group relative rounded-[var(--r-card)] ${className}`}
    >
      {/* Border layer. A gradient-filled box masked to a 1px ring. */}
      {!reduce ? (
        <motion.span
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 rounded-[var(--r-card)] opacity-0 transition-opacity duration-300 group-hover:opacity-100"
          style={{
            background: border,
            WebkitMask:
              "linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0)",
            WebkitMaskComposite: "xor",
            maskComposite: "exclude",
            padding: 1,
          }}
        />
      ) : null}

      {!reduce ? (
        <motion.span
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 rounded-[var(--r-card)] opacity-0 transition-opacity duration-300 group-hover:opacity-100"
          style={{ background: surface }}
        />
      ) : null}

      <div className="relative h-full">{children}</div>
    </div>
  );
}
