"use client";

import { Lightning, Microphone, Play, ShieldCheck, SpeakerHigh, Stop } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ASSISTANT_EVENT, VoiceAssistant, narrate } from "@/components/voice-assistant";
import { type Pack, type Understanding, getPacks, understand } from "@/lib/api";
import { createRecognizer, speechSupported } from "@/lib/speech";
import { say, stopSpeaking } from "@/lib/voice";

const STEPS = [
  { title: "Pick or publish a pack", body: "Questions, checks, scoring and the agent's persona, in one folder. Nine ship today." },
  { title: "The applicant talks", body: "In the browser or on a call. Regulated questions are read word for word, never reworded." },
  { title: "Every answer understood", body: "The agent's own rules catch small talk, refusals and sensitive data instantly. Everything else is understood by AI and checked against what the pack allows." },
  { title: "Checks and an explainable score", body: "Sanctions, PEP and adverse media screening, plus a scorecard where every contribution is attributable." },
  { title: "A person decides", body: "Low risk is approved automatically. Everything else pauses for a reviewer, with transcript, summary and evidence." },
];

/** What Lucy says as each section comes into view. One or two sentences. */
const NARRATION: Record<string, string> = {
  pipeline: "Here's the whole journey in five steps. A pack defines the interview, the applicant talks, every answer is understood and checked, and a person makes the final call.",
  agents: "Each of these agents has its own name, voice and house rules. Press play on any card to hear them.",
  playground: "Now try to trip one up. Say something off topic, or read out a card number, and watch how the agent handles it.",
};

const VOICE_NAMES: Record<string, string> = {
  "2f251ac3-89a9-4a77-a452-704b474ccd01": "Lucy · British",
  "56e35e2d-6eb6-4226-ab8b-9776515a7094": "Kavita · Indian",
  "c894559e-d529-4d70-a6fb-3330ecf7ef6b": "Iris · American",
  "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4": "Skylar · American",
  "dc30854e-e398-4579-9dc8-16f6cb2c19b9": "Victoria · British",
};

const voiceName = (id?: string | null) => (id ? VOICE_NAMES[id] ?? "Custom voice" : "None");

/** One plain speed figure for visitors: "0.2 ms" or "0.6 s", nothing more. */
const formatSpeed = (ms: number) => (ms < 100 ? `${Math.max(ms, 0.1).toFixed(1)} ms` : `${(ms / 1000).toFixed(1)} s`);

export function HowItWorks() {
  const [step, setStep] = useState(0);
  const [packs, setPacks] = useState<Pack[]>([]);

  useEffect(() => {
    getPacks().then(setPacks).catch(() => setPacks([]));
  }, []);

  // Lucy narrates each section once, the first time it is mostly on screen.
  useEffect(() => {
    const said = new Set<string>();
    const io = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        const id = entry.target.id;
        if (entry.isIntersecting && NARRATION[id] && !said.has(id)) {
          said.add(id);
          narrate(NARRATION[id]);
        }
      }
    }, { threshold: 0.45 });
    for (const id of Object.keys(NARRATION)) {
      const el = document.getElementById(id);
      if (el) io.observe(el);
    }
    return () => io.disconnect();
  }, [packs.length]);

  // The assistant drives the page: "next step" advances the pipeline, "show
  // packs" jumps to the agents, without the page knowing anything about it.
  useEffect(() => {
    const onAction = (e: Event) => {
      const action = (e as CustomEvent<string>).detail;
      if (action === "next_step") setStep((s) => Math.min(s + 1, STEPS.length - 1));
      if (action === "show_pipeline" || action === "next_step") {
        document.getElementById("pipeline")?.scrollIntoView({ behavior: "smooth", block: "center" });
      }
      if (action === "show_packs") document.getElementById("agents")?.scrollIntoView({ behavior: "smooth" });
    };
    window.addEventListener(ASSISTANT_EVENT, onAction);
    return () => window.removeEventListener(ASSISTANT_EVENT, onAction);
  }, []);

  return (
    <div className="mx-auto max-w-[1200px] px-6 pb-32">
      <section className="grid items-center gap-10 pt-14 md:grid-cols-[1.05fr_1fr] md:pt-20">
        <div>
          <p className="text-[12px] uppercase tracking-[0.18em] text-text-faint">How it works</p>
          <h1 className="mt-4 text-4xl font-semibold leading-[1.05] tracking-tight md:text-[56px]">
            Don&apos;t read about it. <span className="gradient-text">Ask her.</span>
          </h1>
          <p className="mt-6 max-w-[48ch] text-[16px] leading-relaxed text-text-dim">
            Lucy is a VoxGate voice agent. Talk to her and she will walk you through how it works,
            answer your questions in her own voice, and take you wherever you need to go.
          </p>
          <ul className="mt-8 space-y-3 text-[14px] text-text-dim">
            <li className="flex gap-3"><Microphone size={18} className="mt-0.5 shrink-0 text-[var(--color-siri-1)]" />Press the mic and just talk. Talk over her to interrupt.</li>
            <li className="flex gap-3"><Lightning size={18} className="mt-0.5 shrink-0 text-[var(--color-siri-2)]" />She replies in a fraction of a second, like a real conversation.</li>
            <li className="flex gap-3"><ShieldCheck size={18} className="mt-0.5 shrink-0 text-[var(--color-siri-3)]" />She only talks about VoxGate, and never asks for personal data.</li>
          </ul>
        </div>
        <VoiceAssistant inline page="how-it-works" />
      </section>

      <section id="pipeline" className="scroll-mt-24 pt-28">
        <h2 className="text-3xl font-semibold tracking-tight md:text-4xl">Five steps, one conversation</h2>
        <p className="mt-3 max-w-[60ch] text-text-dim">Click a step, or ask Lucy for the next one.</p>
        <ol className="relative mt-10 grid gap-4 md:grid-cols-5">
          <svg aria-hidden="true" className="pointer-events-none absolute left-0 right-0 top-[26px] hidden h-2 w-full md:block" preserveAspectRatio="none" viewBox="0 0 100 2">
            <line x1="2" y1="1" x2="98" y2="1" stroke="url(#flow)" strokeWidth="0.4" className="flow-edge" />
            <defs>
              <linearGradient id="flow" x1="0" x2="1">
                <stop offset="0" stopColor="#7debff" /><stop offset="0.5" stopColor="#6c7dff" /><stop offset="1" stopColor="#c87bff" />
              </linearGradient>
            </defs>
          </svg>
          {STEPS.map((s, i) => (
            <li key={s.title}>
              <button onClick={() => setStep(i)} aria-pressed={step === i}
                className={`relative h-full w-full rounded-[var(--r-card)] border p-5 text-left transition-all duration-300 ${
                  step === i ? "border-[var(--color-siri-2)] bg-[var(--color-siri-2)]/10 shadow-[0_24px_60px_-28px_rgba(108,125,255,0.7)]"
                    : "border-glass-border-soft bg-[var(--color-surface-2)] hover:border-glass-border"}`}>
                <span className={`grid h-9 w-9 place-items-center rounded-full text-[13px] font-semibold ${
                  step >= i ? "text-[#0a0a12]" : "border border-glass-border text-text-dim"}`}
                  style={step >= i ? { background: "var(--siri-gradient)" } : undefined}>{i + 1}</span>
                <h3 className="mt-4 text-[15px] font-semibold">{s.title}</h3>
                <p className="mt-2 text-[13px] leading-relaxed text-text-dim">{s.body}</p>
              </button>
            </li>
          ))}
        </ol>
      </section>

      <section id="agents" className="scroll-mt-24 pt-28">
        <h2 className="text-3xl font-semibold tracking-tight md:text-4xl">Every agent has its own personality</h2>
        <p className="mt-3 max-w-[64ch] text-text-dim">
          Each pack declares its agent: name, voice with an automatic fallback, greeting, topics it refuses,
          extra sensitive data and its own answers. Same engine, different agent, no platform code.
        </p>
        <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {packs.map((p) => <AgentCard key={p.pack_id} pack={p} />)}
          {packs.length === 0 ? <p className="text-text-faint">Loading agents…</p> : null}
        </div>
      </section>

      <section id="playground" className="scroll-mt-24 pt-28">
        <h2 className="text-3xl font-semibold tracking-tight md:text-4xl">Try to trip one up</h2>
        <p className="mt-3 max-w-[64ch] text-text-dim">
          Say anything to an agent. You will see what it decided you did, whether its own rule or the
          platform caught it, what it says back, and exactly how long that took.
        </p>
        {packs.length ? <Playground packs={packs} /> : null}
      </section>
    </div>
  );
}

function AgentCard({ pack }: { pack: Pack }) {
  const a = pack.agent;
  const [playing, setPlaying] = useState(false);
  if (!a) return null;
  const custom = a.blocked_topics.length + a.sensitive_terms.length + Object.keys(a.process_answers).length;
  const line = a.greeting ?? `Hi, I'm ${a.name}. I'll ask a few short questions for your ${pack.display_name.toLowerCase()}.`;

  async function hear() {
    if (playing) { stopSpeaking(); setPlaying(false); return; }
    setPlaying(true);
    await say(line, pack.pack_id);
    setPlaying(false);
  }

  return (
    <article className="flex flex-col rounded-[var(--r-card)] border border-glass-border-soft bg-[var(--color-surface-2)] p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[17px] font-semibold">{a.name}</p>
          <p className="text-[12.5px] text-text-faint">{pack.display_name}</p>
        </div>
        <button onClick={() => void hear()} aria-label={playing ? `Stop ${a.name}` : `Hear ${a.name}`}
          className="grid h-10 w-10 shrink-0 place-items-center rounded-full text-[#0a0a12] transition-transform active:scale-95"
          style={{ background: "var(--siri-gradient)" }}>
          {playing ? <Stop size={15} weight="fill" /> : <Play size={15} weight="fill" />}
        </button>
      </div>
      <dl className="mt-4 space-y-1.5 text-[12.5px]">
        <div className="flex justify-between gap-3"><dt className="text-text-faint">Voice</dt><dd>{voiceName(a.voice.primary)}</dd></div>
        <div className="flex justify-between gap-3"><dt className="text-text-faint">Fallback</dt><dd>{voiceName(a.voice.fallback)}</dd></div>
        <div className="flex justify-between gap-3"><dt className="text-text-faint">Small talk allowed</dt><dd>{a.max_smalltalk}</dd></div>
        <div className="flex justify-between gap-3"><dt className="text-text-faint">Own rules</dt><dd>{custom || "platform defaults"}</dd></div>
      </dl>
      {a.blocked_topics.length ? (
        <div className="mt-4 flex flex-wrap gap-1.5">
          {a.blocked_topics.map((t) => (
            <span key={t} className="rounded-[var(--r-pill)] border border-[var(--color-status-rejected)]/30 px-2.5 py-0.5 text-[11.5px] text-[var(--color-status-rejected)]">refuses: {t}</span>
          ))}
        </div>
      ) : null}
    </article>
  );
}

const INTENT_COLOR: Record<string, string> = {
  answer: "var(--color-status-approved)",
  sensitive: "var(--color-status-rejected)",
  off_topic: "var(--color-status-needs-attention)",
  process: "var(--color-siri-1)",
  smalltalk: "var(--color-siri-3)",
};

function Playground({ packs }: { packs: Pack[] }) {
  const [packId, setPackId] = useState(packs.find((p) => p.pack_id === "kyc-uae")?.pack_id ?? packs[0].pack_id);
  const pack = packs.find((p) => p.pack_id === packId)!;
  const field = pack.fields[0];
  const [text, setText] = useState("");
  const [counters, setCounters] = useState({ smalltalk_used: 0, off_topic_strikes: 0 });
  const [results, setResults] = useState<(Understanding & { said: string; rtt: number })[]>([]);
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);

  const examples = useMemo(() => {
    const a = pack.agent;
    return [
      "hello there!",
      "how long will this take?",
      a?.blocked_topics[0] ? `any ${a.blocked_topics[0]}?` : "what's the weather like?",
      a?.sensitive_terms[0] ? `my ${a.sensitive_terms[0]} is 12345678` : "my card number is 4111 1111 1111 1111",
      "erm, my brother handles all that",
      "um, it's Fatima Al Mansoori",
    ];
  }, [pack]);

  const run = useCallback(async (said: string) => {
    if (!said.trim()) return;
    setBusy(true);
    try {
      const t0 = performance.now();
      const r = await understand(packId, field, said, 0, counters);
      const rtt = Math.round(performance.now() - t0);
      setCounters(r.counters);
      setResults((xs) => [{ ...r, said, rtt }, ...xs].slice(0, 6));
      setText("");
      const reply = r.prompt ?? (r.value ? `Thank you. I have that as ${r.value}.` : null);
      if (reply) void say(reply, packId);
    } finally {
      setBusy(false);
    }
  }, [counters, field, packId]);

  function mic() {
    const rec = createRecognizer();
    if (!rec) return;
    stopSpeaking();
    let final = "";
    rec.onresult = (e) => {
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) final += e.results[i][0].transcript;
        else setText(e.results[i][0].transcript);
      }
      if (final) setText(final);
    };
    rec.onend = () => { setListening(false); if (final.trim()) void run(final); };
    setListening(true);
    rec.start();
  }

  return (
    <div className="mt-10 grid gap-6 lg:grid-cols-[360px_1fr]">
      <div className="rounded-[var(--r-card)] border border-glass-border-soft bg-[var(--color-surface-2)] p-5">
        <label className="text-[12px] uppercase tracking-[0.14em] text-text-faint" htmlFor="agent-pick">Agent</label>
        <select id="agent-pick" value={packId}
          onChange={(e) => { setPackId(e.target.value); setResults([]); setCounters({ smalltalk_used: 0, off_topic_strikes: 0 }); }}
          className="mt-2 w-full rounded-[var(--r-input)] border border-glass-border bg-[var(--color-bg-1)] px-3 py-2.5 text-[14px] outline-none focus:border-[var(--color-siri-2)]">
          {packs.map((p) => <option key={p.pack_id} value={p.pack_id}>{p.agent?.name ?? "Agent"} · {p.display_name}</option>)}
        </select>
        <p className="mt-4 text-[12.5px] text-text-faint">It is asking:</p>
        <p className="mt-1 text-[14px] leading-relaxed">&ldquo;{pack.reask_hints?.[field] ?? field}&rdquo;</p>
        <div className="mt-5 flex items-center gap-2 rounded-[var(--r-pill)] border border-glass-border p-1.5 focus-within:border-[var(--color-siri-2)]">
          <button onClick={mic} disabled={!speechSupported() || listening} aria-label="Say it"
            className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-text-dim hover:bg-white/[0.06] hover:text-text disabled:opacity-30">
            <Microphone size={17} weight="fill" />
          </button>
          <input value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") void run(text); }}
            placeholder={listening ? "Listening…" : "Say or type anything"} aria-label="What you say to the agent"
            className="h-9 w-full min-w-0 bg-transparent text-[14px] outline-none placeholder:text-text-faint" />
        </div>
        <div className="mt-4 flex flex-wrap gap-1.5">
          {examples.map((ex) => (
            <button key={ex} onClick={() => void run(ex)} disabled={busy}
              className="rounded-[var(--r-pill)] border border-glass-border px-2.5 py-1 text-[12px] text-text-dim hover:border-white/25 hover:text-text disabled:opacity-40">{ex}</button>
          ))}
        </div>
      </div>

      <div className="space-y-3" aria-live="polite">
        {results.length === 0 ? (
          <div className="grid h-full min-h-[240px] place-items-center rounded-[var(--r-card)] border border-dashed border-glass-border-soft text-[14px] text-text-faint">
            Pick an example or say something.
          </div>
        ) : null}
        {results.map((r, i) => (
          <div key={`${r.said}-${i}`} className="rounded-[var(--r-card)] border border-glass-border-soft bg-[var(--color-surface-2)] p-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-[var(--r-pill)] px-2.5 py-0.5 text-[11.5px] font-semibold text-[#0a0a12]"
                style={{ background: INTENT_COLOR[r.intent] ?? "var(--color-text-dim)" }}>{r.intent.replace("_", " ")}</span>
              <span className="rounded-[var(--r-pill)] border border-glass-border px-2.5 py-0.5 text-[11.5px] text-text-dim">
                {r.rule === "agent" ? `${pack.agent?.name}'s own rule` : "standard rule"}
              </span>
              <span className="ml-auto text-[12px] text-text-faint">
                Understood in {formatSpeed(r.timing_ms.total)}
              </span>
            </div>
            <p className="mt-3 text-[13.5px] text-text-dim">You: &ldquo;{r.said}&rdquo;</p>
            {r.value ? <p className="mt-1 text-[13.5px]">Captured: <span className="font-semibold">{r.value}</span> <span className="text-text-faint">({Math.round(r.confidence * 100)}%)</span></p> : null}
            {r.prompt ? (
              <p className="mt-2 flex gap-2 text-[14px] leading-relaxed">
                <SpeakerHigh size={16} className="mt-1 shrink-0 text-[var(--color-siri-1)]" />{r.prompt}
              </p>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}
