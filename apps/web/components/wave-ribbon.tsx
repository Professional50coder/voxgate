"use client";

import { useEffect, useRef } from "react";

/**
 * Self-illuminated parametric wireframe ribbon.
 *
 * A rectangular lattice warped by a sine envelope, with the ribbon's visible
 * half-width narrowing where the surface twists toward the viewer. That twist,
 * not shading, is what produces the depth. Stroke colour is sampled along the
 * ribbon rather than across the screen, so the gradient follows the geometry
 * and reads as holographic.
 *
 * Canvas 2D rather than WebGL: this is a few thousand short strokes per frame,
 * which Canvas handles comfortably, and it avoids a GPU context competing with
 * the page's backdrop-filter layers.
 */

type Stop = { at: number; color: [number, number, number] };

// Cyan -> blue -> violet -> pink -> coral, with a mint accent at the left edge.
const RAMP: Stop[] = [
  { at: 0.0, color: [34, 255, 153] },
  { at: 0.14, color: [125, 235, 255] },
  { at: 0.36, color: [108, 125, 255] },
  { at: 0.56, color: [142, 108, 255] },
  { at: 0.78, color: [200, 123, 255] },
  { at: 1.0, color: [255, 143, 92] },
];

function sample(t: number): [number, number, number] {
  const u = Math.min(1, Math.max(0, t));
  let lo = RAMP[0];
  let hi = RAMP[RAMP.length - 1];
  for (let i = 0; i < RAMP.length - 1; i++) {
    if (u >= RAMP[i].at && u <= RAMP[i + 1].at) {
      lo = RAMP[i];
      hi = RAMP[i + 1];
      break;
    }
  }
  const span = hi.at - lo.at || 1;
  const k = (u - lo.at) / span;
  return [
    Math.round(lo.color[0] + (hi.color[0] - lo.color[0]) * k),
    Math.round(lo.color[1] + (hi.color[1] - lo.color[1]) * k),
    Math.round(lo.color[2] + (hi.color[2] - lo.color[2]) * k),
  ];
}

const COLS = 132; // along the ribbon
const ROWS = 11; // across the ribbon

export function WaveRibbon({ className }: { className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let w = 0;
    let h = 0;
    let dpr = 1;

    function resize() {
      const rect = canvas!.getBoundingClientRect();
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = rect.width;
      h = rect.height;
      canvas!.width = Math.floor(w * dpr);
      canvas!.height = Math.floor(h * dpr);
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    resize();

    const particles = Array.from({ length: 54 }, (_, i) => ({
      x: (i * 97) % 1000 / 1000,
      y: ((i * 61) % 1000) / 1000,
      r: 1 + ((i * 7) % 5) * 0.6,
      a: 0.18 + ((i * 13) % 60) / 100,
      drift: 0.3 + ((i * 11) % 40) / 100,
    }));

    /** Surface point for lattice coordinates u (0..1 along) and v (-1..1 across). */
    function surface(u: number, v: number, t: number) {
      const x = u * w;
      // Two summed sines give an uneven rhythm: one dominant crest, softer echoes.
      const envelope =
        Math.sin(u * Math.PI * 2.1 + t * 0.00022) * 0.62 +
        Math.sin(u * Math.PI * 3.7 - t * 0.00031) * 0.26;
      const amp = h * 0.19;
      const baseY = h * 0.56 + envelope * amp;
      // Twist: the ribbon rotates toward the viewer, so its projected width
      // collapses periodically. This is what sells the third dimension.
      const twist = Math.cos(u * Math.PI * 2.6 - t * 0.00026);
      const halfWidth = h * 0.085 * (0.32 + 0.68 * Math.abs(twist));
      return { x, y: baseY + v * halfWidth, twist };
    }

    let raf = 0;

    function draw(t: number) {
      ctx!.clearRect(0, 0, w, h);
      ctx!.globalCompositeOperation = "lighter";

      // Lines running along the ribbon.
      for (let r = 0; r < ROWS; r++) {
        const v = (r / (ROWS - 1)) * 2 - 1;
        const edgeFade = 1 - Math.abs(v) * 0.55;
        for (let c = 0; c < COLS - 1; c++) {
          const u0 = c / (COLS - 1);
          const u1 = (c + 1) / (COLS - 1);
          const p0 = surface(u0, v, t);
          const p1 = surface(u1, v, t);
          const [cr, cg, cb] = sample(u0);
          const glow = 0.3 + 0.7 * Math.abs(p0.twist);
          ctx!.strokeStyle = `rgba(${cr},${cg},${cb},${0.5 * edgeFade * glow})`;
          ctx!.lineWidth = 1;
          ctx!.beginPath();
          ctx!.moveTo(p0.x, p0.y);
          ctx!.lineTo(p1.x, p1.y);
          ctx!.stroke();
        }
      }

      // Lines running across the ribbon, forming the lattice cells.
      for (let c = 0; c < COLS; c += 2) {
        const u = c / (COLS - 1);
        const [cr, cg, cb] = sample(u);
        const p = surface(u, 0, t);
        const glow = 0.25 + 0.75 * Math.abs(p.twist);
        ctx!.strokeStyle = `rgba(${cr},${cg},${cb},${0.34 * glow})`;
        ctx!.lineWidth = 1;
        ctx!.beginPath();
        for (let r = 0; r < ROWS; r++) {
          const v = (r / (ROWS - 1)) * 2 - 1;
          const q = surface(u, v, t);
          if (r === 0) ctx!.moveTo(q.x, q.y);
          else ctx!.lineTo(q.x, q.y);
        }
        ctx!.stroke();

        // Energy nodes where the surface is most edge-on.
        if (Math.abs(p.twist) > 0.965) {
          const g = ctx!.createRadialGradient(p.x, p.y, 0, p.x, p.y, 22);
          g.addColorStop(0, `rgba(255,255,255,0.5)`);
          g.addColorStop(0.35, `rgba(${cr},${cg},${cb},0.32)`);
          g.addColorStop(1, `rgba(${cr},${cg},${cb},0)`);
          ctx!.fillStyle = g;
          ctx!.beginPath();
          ctx!.arc(p.x, p.y, 22, 0, Math.PI * 2);
          ctx!.fill();
        }
      }

      // Floating particles.
      for (const p of particles) {
        const px = ((p.x + t * 0.0000085 * p.drift) % 1) * w;
        const py = p.y * h;
        const [cr, cg, cb] = sample(px / w);
        ctx!.fillStyle = `rgba(${cr},${cg},${cb},${p.a})`;
        ctx!.beginPath();
        ctx!.arc(px, py, p.r, 0, Math.PI * 2);
        ctx!.fill();
      }

      ctx!.globalCompositeOperation = "source-over";
      raf = requestAnimationFrame(draw);
    }

    if (reduce) {
      draw(0);
      cancelAnimationFrame(raf);
    } else {
      raf = requestAnimationFrame(draw);
    }

    const onResize = () => {
      resize();
      if (reduce) draw(0);
    };
    const onVisibility = () => {
      if (document.hidden) cancelAnimationFrame(raf);
      else if (!reduce) raf = requestAnimationFrame(draw);
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
