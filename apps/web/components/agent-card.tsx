"use client";

import { Play } from "@phosphor-icons/react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { getPacks } from "@/lib/api";

/**
 * The hero's product card. Deliberately a live component rather than a mock:
 * the pack name and question count are fetched from the running API, and the
 * button starts a real interview. A styled-div imitation of a screenshot would
 * be the easier build and the more dishonest one.
 */

// Fixed bar heights: a deterministic pattern reads as a waveform, whereas
// random heights re-rolled per render read as noise.
const BARS = [
  0.24, 0.42, 0.66, 0.38, 0.82, 0.54, 0.3, 0.7, 0.94, 0.48, 0.26, 0.6, 0.86, 0.4,
  0.68, 0.32, 0.52, 0.78, 0.44, 0.28, 0.62, 0.9, 0.36, 0.56, 0.74, 0.34, 0.46,
  0.66, 0.22, 0.5,
];

export function AgentCard() {
  const [packName, setPackName] = useState<string | null>(null);
  const [questions, setQuestions] = useState<number | null>(null);
  const [playing, setPlaying] = useState(true);
  const [tick, setTick] = useState(0);

  // The waveform runs on its own so the card reads as live rather than parked.
  // Stops when paused, when the tab is hidden, or under reduced motion.
  useEffect(() => {
    if (!playing) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let raf = 0;
    let last = 0;
    const loop = (t: number) => {
      if (t - last > 90) {
        last = t;
        if (!document.hidden) setTick((n) => n + 1);
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [playing]);

  useEffect(() => {
    getPacks()
      .then((packs) => {
        const p = packs[0];
        if (!p) return;
        setPackName(p.pack_id);
        setQuestions(p.fields.length);
      })
      .catch(() => {
        // Offline is fine here. The card degrades to its static labels rather
        // than showing an error on a marketing page.
      });
  }, []);

  return (
    <div
      className="w-full max-w-[352px] rounded-[26px] border p-6 text-center"
      style={{
        background: "rgba(255,255,255,0.06)",
        borderColor: "rgba(255,255,255,0.10)",
        backdropFilter: "blur(28px) saturate(1.4)",
        boxShadow: "0 30px 90px rgba(9,3,12,0.55), inset 0 1px 0 rgba(255,255,255,0.14)",
      }}
    >
      <div
        className="mx-auto grid h-14 w-14 place-items-center rounded-full"
        style={{
          background: "linear-gradient(140deg, #7DEBFF 0%, #6C7DFF 52%, #C87BFF 100%)",
          boxShadow: "0 0 32px rgba(108,125,255,0.45)",
        }}
      >
        <span className="text-[17px] font-bold text-[#0a0a12]">VG</span>
      </div>

      <h2 className="mt-4 text-[16px] font-semibold tracking-tight">VoxGate Agent</h2>
      <p className="mt-1 text-[13px] text-[#B7B7C2]">Compliance interviewer</p>

      <div className="mt-4 flex flex-wrap justify-center gap-2">
        <Pill>{packName ?? "kyc-uae"}</Pill>
        <Pill>{questions ? `${questions} questions` : "Voice interview"}</Pill>
      </div>

      <div className="mt-5 flex items-center gap-4">
        <button
          type="button"
          onClick={() => setPlaying((p) => !p)}
          aria-label={playing ? "Pause the sample waveform" : "Play the sample waveform"}
          aria-pressed={playing}
          className="grid h-11 w-11 shrink-0 place-items-center rounded-full border transition-transform active:scale-[0.95]"
          style={{
            background: "rgba(255,255,255,0.08)",
            borderColor: "rgba(255,255,255,0.12)",
          }}
        >
          <Play size={15} weight="fill" color="#FFFFFF" />
        </button>

        <div className="flex h-8 flex-1 items-center gap-[3px]" aria-hidden="true">
          {BARS.map((h, i) => {
            // A slow travelling envelope over the fixed pattern. Reads as speech
            // energy moving through the buffer rather than random flicker.
            const wave = playing
              ? 0.55 + 0.45 * Math.sin((i * 0.55) - tick * 0.22)
              : 0.45;
            return (
              <span
                key={i}
                className="flex-1 rounded-full"
                style={{
                  height: `${Math.max(0.12, h * wave) * 100}%`,
                  background: "linear-gradient(180deg, #7DEBFF, #6C7DFF)",
                  opacity: playing ? 0.5 + 0.45 * wave : 0.3,
                  transition: "height 110ms linear, opacity 110ms linear",
                }}
              />
            );
          })}
        </div>
      </div>

      <Link
        href="/apply"
        className="mt-5 block rounded-[var(--r-pill)] py-2.5 text-[14.5px] font-semibold text-[#0a0a12] transition-transform active:scale-[0.98]"
        style={{ background: "linear-gradient(120deg, #7DEBFF, #6C7DFF 52%, #C87BFF)" }}
      >
        Start an interview
      </Link>
    </div>
  );
}

function Pill({ children }: { children: React.ReactNode }) {
  return (
    <span
      className="rounded-[var(--r-pill)] border px-3 py-1.5 text-[12px] text-[#B7B7C2]"
      style={{
        background: "rgba(255,255,255,0.05)",
        borderColor: "rgba(255,255,255,0.09)",
      }}
    >
      {children}
    </span>
  );
}
