"use client";

import { ArrowRight, Pause, Play } from "@phosphor-icons/react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { type Pack, getPacks } from "@/lib/api";
import { agentAnalyser, say, stopSpeaking } from "@/lib/voice";

/**
 * The hero's agent picker. Live, not a mock: the agents come from the running
 * API, Play speaks in that agent's real voice, the waveform is drawn from the
 * audio actually playing, and the button starts that agent's interview.
 */

type Featured = { pack: string; industry: string; voice: string };

// Leading with four industries keeps the choice instant; the rest are one
// click away on How it works.
const FEATURED: Featured[] = [
  { pack: "kyc-uae", industry: "Banking KYC", voice: "British · calm and reassuring" },
  { pack: "patient-intake", industry: "Patient intake", voice: "American · warm and unhurried" },
  { pack: "sales-discovery", industry: "Sales discovery", voice: "American · bright and friendly" },
  { pack: "recruit-screen", industry: "Recruiting", voice: "British · crisp and professional" },
];

const BAR_COUNT = 30;
const IDLE = Array.from({ length: BAR_COUNT }, (_, i) => 0.14 + 0.1 * Math.abs(Math.sin(i * 0.9)));

export function AgentCard() {
  const [packs, setPacks] = useState<Pack[]>([]);
  const [active, setActive] = useState(FEATURED[0].pack);
  const [playing, setPlaying] = useState(false);
  const [bars, setBars] = useState<number[]>(IDLE);
  const rafRef = useRef(0);

  useEffect(() => {
    getPacks().then(setPacks).catch(() => {
      // Offline is fine on a marketing page: the card keeps its static labels.
    });
    return () => {
      cancelAnimationFrame(rafRef.current);
      stopSpeaking();
    };
  }, []);

  const featured = FEATURED.find((f) => f.pack === active)!;
  const pack = packs.find((p) => p.pack_id === active);
  const name = pack?.agent?.name ?? "Lucy";
  const line = pack?.agent?.greeting ?? `Hi, I'm ${name}. I'll take you through a few short questions.`;

  // Bars follow the real audio while the agent is speaking, and rest otherwise.
  function animate() {
    const analyser = agentAnalyser();
    const data = new Uint8Array(analyser?.frequencyBinCount ?? 0);
    const loop = () => {
      if (analyser) {
        analyser.getByteFrequencyData(data);
        const step = Math.max(1, Math.floor(data.length / 2 / BAR_COUNT));
        setBars(Array.from({ length: BAR_COUNT }, (_, i) => Math.max(0.1, data[i * step] / 255)));
      }
      rafRef.current = requestAnimationFrame(loop);
    };
    rafRef.current = requestAnimationFrame(loop);
  }

  async function hear() {
    if (playing) {
      stopSpeaking();
      return;
    }
    setPlaying(true);
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const done = say(line, active);
    if (!reduce) animate();
    await done;
    cancelAnimationFrame(rafRef.current);
    setBars(IDLE);
    setPlaying(false);
  }

  function pick(id: string) {
    if (playing) stopSpeaking();
    setActive(id);
  }

  return (
    <div
      className="w-full max-w-[400px] rounded-[26px] border p-5 text-center"
      style={{
        background: "rgba(255,255,255,0.06)",
        borderColor: "rgba(255,255,255,0.10)",
        backdropFilter: "blur(28px) saturate(1.4)",
        boxShadow: "0 30px 90px rgba(9,3,12,0.55), inset 0 1px 0 rgba(255,255,255,0.14)",
      }}
    >
      <div role="tablist" aria-label="Choose an industry" className="grid grid-cols-2 gap-1.5">
        {FEATURED.map((f) => (
          <button key={f.pack} role="tab" aria-selected={f.pack === active} onClick={() => pick(f.pack)}
            className={`rounded-[var(--r-pill)] px-3 py-1.5 text-[12.5px] transition-colors ${
              f.pack === active ? "bg-white/[0.12] font-semibold text-white" : "text-[#B7B7C2] hover:text-white"}`}>
            {f.industry}
          </button>
        ))}
      </div>

      <div className="mt-5 flex items-center gap-3.5 text-left">
        <div className="grid h-12 w-12 shrink-0 place-items-center rounded-full text-[17px] font-bold text-[#0a0a12]"
          style={{ background: "var(--siri-gradient)", boxShadow: "0 0 32px rgba(108,125,255,0.45)" }}>
          {name[0]}
        </div>
        <div className="min-w-0">
          <p key={name} className="land text-[16px] font-semibold tracking-tight text-white">{name}</p>
          <p className="truncate text-[12.5px] text-[#B7B7C2]">{featured.voice}</p>
        </div>
      </div>

      <div className="mt-4 flex items-center gap-3.5">
        <button type="button" onClick={() => void hear()}
          aria-label={playing ? `Stop ${name}` : `Hear ${name}'s voice`}
          className="grid h-11 w-11 shrink-0 place-items-center rounded-full border transition-transform active:scale-[0.95]"
          style={{ background: "rgba(255,255,255,0.08)", borderColor: "rgba(255,255,255,0.12)" }}>
          {playing ? <Pause size={15} weight="fill" color="#FFFFFF" /> : <Play size={15} weight="fill" color="#FFFFFF" />}
        </button>
        <div className="flex h-9 flex-1 items-center gap-[3px]" aria-hidden="true">
          {bars.map((h, i) => (
            <span key={i} className="flex-1 rounded-full"
              style={{
                height: `${Math.min(1, h) * 100}%`,
                background: "linear-gradient(180deg, #7DEBFF, #6C7DFF)",
                opacity: playing ? 0.95 : 0.35,
                transition: "height 80ms linear, opacity 200ms linear",
              }} />
          ))}
        </div>
      </div>
      <p className="mt-2 text-left text-[11.5px] text-[#7a7490]">{playing ? `${name} is speaking` : `Press play to hear ${name}`}</p>

      <Link href={`/apply?pack=${active}`}
        className="mt-4 flex items-center justify-center gap-2 rounded-[var(--r-pill)] py-2.5 text-[14.5px] font-semibold text-[#0a0a12] transition-transform active:scale-[0.98]"
        style={{ background: "linear-gradient(120deg, #7DEBFF, #6C7DFF 52%, #C87BFF)" }}>
        Talk to {name} <ArrowRight size={15} weight="bold" />
      </Link>
    </div>
  );
}
