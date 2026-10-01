"use client";

import { Pause, Play } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";

import { stopSpeaking } from "@/lib/voice";

type Call = {
  pack: string;
  title: string;
  agent: string;
  shows: string;
  turns: { role: "agent" | "caller"; text: string; audio: string }[];
};

/**
 * Recorded sample calls, for visitors who will not turn their microphone on.
 * Pre-rendered static audio (scripts/generate_sample_calls.py), so playing one
 * needs no API and costs nothing. The transcript follows the audio turn by
 * turn, so it reads as a real call rather than a clip.
 */
export function SampleCalls() {
  const [calls, setCalls] = useState<Call[]>([]);
  const [active, setActive] = useState(0);
  const [turn, setTurn] = useState(-1);
  const [playing, setPlaying] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const stopRef = useRef(false);

  useEffect(() => {
    fetch("/samples/calls.json")
      .then((r) => (r.ok ? r.json() : []))
      .then(setCalls)
      .catch(() => setCalls([]));
    return () => {
      stopRef.current = true;
      audioRef.current?.pause();
    };
  }, []);

  function stop() {
    stopRef.current = true;
    audioRef.current?.pause();
    setPlaying(false);
  }

  async function play() {
    if (playing) return stop();
    const call = calls[active];
    if (!call) return;
    stopSpeaking(); // never talk over Lucy
    stopRef.current = false;
    setPlaying(true);
    for (let i = 0; i < call.turns.length && !stopRef.current; i++) {
      setTurn(i);
      await new Promise<void>((resolve) => {
        const el = new Audio(call.turns[i].audio);
        audioRef.current = el;
        el.onended = () => resolve();
        el.onerror = () => resolve();
        el.onpause = () => resolve();
        el.play().catch(() => resolve());
      });
      if (!stopRef.current) await new Promise((r) => setTimeout(r, 280));
    }
    setPlaying(false);
  }

  function pick(i: number) {
    stop();
    setActive(i);
    setTurn(-1);
  }

  if (!calls.length) return null;
  const call = calls[active];

  return (
    <div className="glass overflow-hidden rounded-[var(--r-card)] text-left">
      <div role="tablist" aria-label="Sample calls by industry" className="flex flex-wrap gap-1.5 border-b border-glass-border-soft p-3">
        {calls.map((c, i) => (
          <button key={c.pack} role="tab" aria-selected={i === active} onClick={() => pick(i)}
            className={`rounded-[var(--r-pill)] px-3.5 py-1.5 text-[13px] transition-colors ${
              i === active ? "bg-white/[0.12] font-semibold text-text" : "text-text-dim hover:text-text"}`}>
            {c.title}
          </button>
        ))}
      </div>
      <div className="flex items-center gap-4 px-5 pt-5">
        <button onClick={() => void play()} aria-label={playing ? "Stop the call" : `Play the ${call.title} call`}
          className="grid h-12 w-12 shrink-0 place-items-center rounded-full text-[#0a0a12] transition-transform active:scale-95"
          style={{ background: "var(--siri-gradient)" }}>
          {playing ? <Pause size={18} weight="fill" /> : <Play size={18} weight="fill" />}
        </button>
        <div>
          <p className="text-[15px] font-semibold">{call.agent} · {call.title}</p>
          <p className="text-[13px] text-text-dim">{call.shows}</p>
        </div>
      </div>
      <ol className="space-y-2 p-5" aria-live="polite">
        {call.turns.map((t, i) => (
          <li key={i} className={`rounded-[10px] px-3 py-2 text-[13.5px] leading-relaxed transition-all duration-300 ${
            i === turn ? "bg-[var(--color-siri-2)]/15 text-text" : i < turn ? "text-text-dim" : "text-text-faint"}`}>
            <span className="font-medium">{t.role === "agent" ? call.agent : "Caller"}:</span> {t.text}
          </li>
        ))}
      </ol>
      <p className="border-t border-glass-border-soft px-5 py-3 text-[12px] text-text-faint">
        Fictional callers. The agent&apos;s lines are exactly what the product says in each situation.
      </p>
    </div>
  );
}
