"use client";

import { useEffect, useRef } from "react";

/**
 * Flowing liquid-chrome ribbons.
 *
 * Drawn parametrically on canvas rather than as fixed SVG paths, because the
 * motion has to come from the geometry itself. Translating a static shape reads
 * as a sliding sticker; recomputing the centreline every frame reads as liquid.
 *
 * Material: each ribbon is filled with a vertical gradient recomputed from its
 * current vertical extent, so the specular core stays inside the band as it
 * moves. That cross-section (dark edge, near-white core, saturated mid-tone,
 * dark edge) is what makes a flat fill look like a rounded polished surface.
 * One gradient object per ribbon per frame, so the cost is trivial.
 *
 * Ribbons twist: the projected half-width collapses periodically along the
 * length, which is what produces depth without any shading maths.
 */

type Ribbon = {
  baseY: number; // fraction of height
  amp: number; // fraction of height
  freq: number; // waves across the canvas
  speed: number; // phase advance per ms
  thickness: number; // fraction of height, half-width at full face
  twistFreq: number;
  twistSpeed: number;
  phase: number;
  opacity: number;
  stops: [number, string][];
};

const CHROME_A: [number, string][] = [
  [0, "rgba(26,18,53,0.05)"],
  [0.26, "#7DEBFF"],
  [0.42, "#FFFFFF"],
  [0.58, "#6C7DFF"],
  [0.84, "rgba(200,123,255,0.75)"],
  [1, "rgba(26,18,53,0.04)"],
];

const CHROME_B: [number, string][] = [
  [0, "rgba(26,18,53,0.04)"],
  [0.3, "rgba(200,123,255,0.85)"],
  [0.47, "#FFFFFF"],
  [0.63, "#7DEBFF"],
  [0.88, "rgba(58,42,107,0.45)"],
  [1, "rgba(26,18,53,0.04)"],
];

const CHROME_C: [number, string][] = [
  [0, "rgba(15,10,38,0)"],
  [0.38, "rgba(108,125,255,0.9)"],
  [0.53, "#E8F6FF"],
  [0.71, "rgba(142,91,255,0.85)"],
  [1, "rgba(15,10,38,0)"],
];

const RIBBONS: Ribbon[] = [
  { baseY: 0.52, amp: 0.1, freq: 1.15, speed: 0.000075, thickness: 0.075, twistFreq: 1.5, twistSpeed: 0.00009, phase: 0, opacity: 0.92, stops: CHROME_A },
  { baseY: 0.66, amp: 0.085, freq: 0.9, speed: -0.00006, thickness: 0.045, twistFreq: 2.1, twistSpeed: 0.00012, phase: 1.9, opacity: 0.72, stops: CHROME_C },
  { baseY: 0.38, amp: 0.075, freq: 1.4, speed: 0.00005, thickness: 0.032, twistFreq: 1.8, twistSpeed: -0.00008, phase: 3.4, opacity: 0.52, stops: CHROME_B },
  { baseY: 0.46, amp: 0.11, freq: 0.75, speed: -0.00009, thickness: 0.058, twistFreq: 1.25, twistSpeed: 0.00007, phase: 5.1, opacity: 0.8, stops: CHROME_B },
  { baseY: 0.74, amp: 0.06, freq: 1.7, speed: 0.00011, thickness: 0.026, twistFreq: 2.6, twistSpeed: -0.0001, phase: 2.4, opacity: 0.42, stops: CHROME_A },
  { baseY: 0.3, amp: 0.05, freq: 1.05, speed: 0.00004, thickness: 0.022, twistFreq: 2.2, twistSpeed: 0.00013, phase: 0.8, opacity: 0.36, stops: CHROME_C },
];

const STEP = 10; // px along x. Finer than this buys nothing at these curvatures.

export function GlassRibbons({ className }: { className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let w = 0;
    let h = 0;

    function resize() {
      const rect = canvas!.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = rect.width;
      h = rect.height;
      canvas!.width = Math.max(1, Math.floor(w * dpr));
      canvas!.height = Math.max(1, Math.floor(h * dpr));
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    resize();

    function drawRibbon(r: Ribbon, t: number) {
      const phase = r.phase + t * r.speed;
      const twistPhase = r.phase * 0.6 + t * r.twistSpeed;
      const amp = h * r.amp;
      const base = h * r.baseY;
      const thick = h * r.thickness;

      const tops: [number, number][] = [];
      const bottoms: [number, number][] = [];
      let minY = Infinity;
      let maxY = -Infinity;

      for (let x = -60; x <= w + 60; x += STEP) {
        const u = x / Math.max(1, w);
        // Two summed sines so the rhythm is uneven rather than a clean wave.
        const centre =
          base +
          Math.sin(u * Math.PI * 2 * r.freq + phase) * amp +
          Math.sin(u * Math.PI * 2 * r.freq * 2.3 - phase * 0.7) * amp * 0.28;
        // Twist collapses the projected width periodically.
        const twist = Math.cos(u * Math.PI * 2 * r.twistFreq + twistPhase);
        const half = thick * (0.22 + 0.78 * Math.abs(twist));
        const top = centre - half;
        const bottom = centre + half;
        tops.push([x, top]);
        bottoms.push([x, bottom]);
        if (top < minY) minY = top;
        if (bottom > maxY) maxY = bottom;
      }

      ctx!.beginPath();
      tops.forEach(([x, y], i) => (i === 0 ? ctx!.moveTo(x, y) : ctx!.lineTo(x, y)));
      for (let i = bottoms.length - 1; i >= 0; i--) ctx!.lineTo(bottoms[i][0], bottoms[i][1]);
      ctx!.closePath();

      // Gradient spans the ribbon's live vertical extent, so the specular core
      // travels with the band instead of drifting off it.
      const grad = ctx!.createLinearGradient(0, minY, 0, maxY);
      for (const [at, color] of r.stops) grad.addColorStop(at, color);
      ctx!.globalAlpha = r.opacity;
      ctx!.fillStyle = grad;
      ctx!.fill();

      // Specular edge along the top. This is the glass tell.
      ctx!.beginPath();
      tops.forEach(([x, y], i) => (i === 0 ? ctx!.moveTo(x, y) : ctx!.lineTo(x, y)));
      ctx!.globalAlpha = r.opacity * 0.55;
      ctx!.strokeStyle = "rgba(255,255,255,0.9)";
      ctx!.lineWidth = 1.1;
      ctx!.stroke();
      ctx!.globalAlpha = 1;
    }

    let raf = 0;

    function frame(t: number) {
      ctx!.clearRect(0, 0, w, h);
      // Additive so overlaps brighten, which is how layered glass behaves.
      ctx!.globalCompositeOperation = "lighter";
      for (const r of RIBBONS) drawRibbon(r, t);
      ctx!.globalCompositeOperation = "source-over";
      raf = requestAnimationFrame(frame);
    }

    if (reduce) {
      // One representative frame rather than a frozen blank canvas.
      ctx.clearRect(0, 0, w, h);
      ctx.globalCompositeOperation = "lighter";
      for (const r of RIBBONS) drawRibbon(r, 0);
      ctx.globalCompositeOperation = "source-over";
    } else {
      raf = requestAnimationFrame(frame);
    }

    const onResize = () => {
      resize();
      if (reduce) {
        ctx.clearRect(0, 0, w, h);
        ctx.globalCompositeOperation = "lighter";
        for (const r of RIBBONS) drawRibbon(r, 0);
        ctx.globalCompositeOperation = "source-over";
      }
    };
    const onVisibility = () => {
      if (document.hidden) cancelAnimationFrame(raf);
      else if (!reduce) raf = requestAnimationFrame(frame);
    };

    window.addEventListener("resize", onResize);
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  return <canvas ref={ref} aria-hidden="true" className={className} />;
}
