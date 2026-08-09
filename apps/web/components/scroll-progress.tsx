"use client";

import { motion, useScroll, useReducedMotion, useSpring } from "motion/react";

/**
 * Reading-progress rail under the header.
 *
 * Driven by useScroll, never a scroll event listener: a listener fires on every
 * frame, unbatched, and re-renders React if it touches state. The spring is what
 * stops the bar twitching on trackpad scroll.
 */
export function ScrollProgress() {
  const reduce = useReducedMotion();
  const { scrollYProgress } = useScroll();
  const width = useSpring(scrollYProgress, { stiffness: 140, damping: 26, mass: 0.3 });

  if (reduce) return null;

  return (
    <motion.div
      aria-hidden="true"
      className="fixed left-0 top-16 z-50 h-[2px] w-full origin-left"
      style={{
        scaleX: width,
        background: "var(--siri-gradient)",
      }}
    />
  );
}
