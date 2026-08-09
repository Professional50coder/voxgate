"use client";

import { useEffect, useRef } from "react";

export type OrbState = "idle" | "listening" | "thinking" | "speaking";

/**
 * Siri-style reactive orb. Canvas 2D, not WebGL: at 160px on a DPR-2 display
 * this is ~102k pixels, which Canvas 2D fills in well under a millisecond. A
 * WebGL context would cost a library plus a GPU context competing with the
 * page's backdrop-filter layers, to draw an area smaller than a favicon grid.
 *
 * Amplitude comes from RMS over the time-domain data, not peak over frequency
 * bins: peak jitters and makes the orb twitch, RMS reads as voice energy.
 * The envelope is deliberately asymmetric (fast attack, slow release), which is
 * the single detail that separates "reactive" from "cheap".
 */

const TUNING: Record<OrbState, { gain: number; breathe: number; spin: number; lobes: number }> = {
  idle: { gain: 0, breathe: 0.03, spin: 0.1, lobes: 3 },
  listening: { gain: 2.6, breathe: 0.015, spin: 0.35, lobes: 4 },
  thinking: { gain: 0, breathe: 0.055, spin: 1.2, lobes: 5 },
  speaking: { gain: 2.0, breathe: 0.02, spin: 0.55, lobes: 4 },
};

const COLORS = ["#7debff", "#6c7dff", "#c87bff"];
const SIZE = 160;

export function VoiceOrb({
  state,
  analyser,
}: {
  state: OrbState;
  analyser: AnalyserNode | null;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stateRef = useRef<OrbState>(state);
  const analyserRef = useRef<AnalyserNode | null>(analyser);

  // Mirrored into refs from an effect, not during render. The draw loop below
  // must not be torn down and rebuilt every time `state` changes -- that would
  // restart the animation and lose the lerp -- so it reads the latest value
  // through a ref instead of closing over the prop. Writing the ref during
  // render is the tempting shortcut and is wrong: render must stay pure, and
  // under StrictMode or a discarded render it writes values that never commit.
  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    analyserRef.current = analyser;
  }, [analyser]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = SIZE * dpr;
    canvas.height = SIZE * dpr;
    ctx.scale(dpr, dpr);

    const cx = SIZE / 2;
    const cy = SIZE / 2;
    const timeData = new Uint8Array(2048);

    let env = 0;
    let raf = 0;
    // Tuning is lerped rather than switched so a state change never pops.
    const current = { ...TUNING.idle };

    function rms(): number {
      const node = analyserRef.current;
      if (!node) return 0;
      const buf = timeData.subarray(0, node.fftSize);
      node.getByteTimeDomainData(buf);
      let sum = 0;
      for (let i = 0; i < buf.length; i++) {
        const v = (buf[i] - 128) / 128;
        sum += v * v;
      }
      return Math.sqrt(sum / buf.length);
    }

    function draw(t: number) {
      const target = TUNING[stateRef.current];
      for (const key of ["gain", "breathe", "spin", "lobes"] as const) {
        current[key] += (target[key] - current[key]) * 0.08;
      }

      const raw = current.gain > 0.05 ? rms() * current.gain : 0;
      const k = raw > env ? 0.45 : 0.08; // fast attack, slow release
      env += (raw - env) * k;

      const radius =
        SIZE * 0.3 * (1 + env * 0.42 + Math.sin(t * 0.0016) * current.breathe);

      ctx!.clearRect(0, 0, SIZE, SIZE);
      ctx!.globalCompositeOperation = "lighter";

      for (let b = 0; b < 3; b++) {
        const phase = t * 0.0009 * current.spin + b * 2.094;
        ctx!.beginPath();
        for (let i = 0; i <= 90; i++) {
          const th = (i / 90) * Math.PI * 2;
          const wobble =
            1 +
            0.1 * env * Math.sin(current.lobes * th + phase * 3) +
            0.055 * env * Math.sin((current.lobes + 2) * th - phase * 2) +
            0.02 * Math.sin(2 * th + phase);
          const r = radius * wobble * (1 - b * 0.07);
          const x = cx + Math.cos(th + phase * 0.4) * r;
          const y = cy + Math.sin(th + phase * 0.4) * r;
          if (i === 0) ctx!.moveTo(x, y);
          else ctx!.lineTo(x, y);
        }
        ctx!.closePath();
        const grad = ctx!.createRadialGradient(cx, cy, radius * 0.1, cx, cy, radius * 1.25);
        grad.addColorStop(0, `${COLORS[b]}e6`);
        grad.addColorStop(1, `${COLORS[b]}00`);
        ctx!.fillStyle = grad;
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

    const onVisibility = () => {
      if (document.hidden) cancelAnimationFrame(raf);
      else if (!reduce) raf = requestAnimationFrame(draw);
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      cancelAnimationFrame(raf);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  return (
    <div
      className="relative grid place-items-center"
      style={{ width: SIZE, height: SIZE }}
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 rounded-full"
        style={{ boxShadow: "0 0 64px 8px rgba(200,123,255,0.24)" }}
      />
      {/* Decorative. The spoken state is announced in a live region by the caller. */}
      <canvas
        ref={canvasRef}
        aria-hidden="true"
        style={{ width: SIZE, height: SIZE }}
      />
    </div>
  );
}
