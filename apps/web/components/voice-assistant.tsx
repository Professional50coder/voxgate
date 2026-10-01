"use client";

import { Microphone, PaperPlaneRight, Sparkle, Stop, X } from "@phosphor-icons/react";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { VoiceOrb, type OrbState } from "@/components/voice-orb";
import { type AssistantAction, ApiUnreachable, askAssistant } from "@/lib/api";
import { createRecognizer, speechSupported, type Recognizer } from "@/lib/speech";
import { agentAnalyser, say, stopSpeaking } from "@/lib/voice";

type Turn = { role: "user" | "assistant"; text: string };
type Latency = { brainMs: number | null; firstAudioMs: number | null; via: string; model: string | null };

const PAGE_FOR: [RegExp, string][] = [
  [/^\/how-it-works/, "how-it-works"],
  [/^\/apply/, "apply"],
  [/^\/console/, "console"],
  [/^\/agents/, "agents"],
];

const OPENERS: Record<string, string> = {
  "how-it-works": "Walk me through how VoxGate works.",
  home: "What can VoxGate do for my business?",
  console: "What should I look at first?",
  agents: "Help me design a voice agent.",
  apply: "What will the interview be like?",
};

/** Fired for actions the page itself should perform, e.g. highlighting a step. */
export const ASSISTANT_EVENT = "voxgate:assistant-action";

/**
 * VoxGate's voice assistant. One brain (/assistant), a persona per page, the
 * agent's human voice (/tts) and a closed set of actions it can take on the
 * site. Talk or type; talking over it stops it, the way a person would.
 */
export function VoiceAssistant({
  inline = false,
  page: pageProp,
  context,
}: {
  inline?: boolean;
  page?: string;
  context?: string;
}) {
  const pathname = usePathname() ?? "/";
  const router = useRouter();
  const page = pageProp ?? PAGE_FOR.find(([re]) => re.test(pathname))?.[1] ?? "home";

  const [open, setOpen] = useState(inline);
  const [orb, setOrb] = useState<OrbState>("idle");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [caption, setCaption] = useState("");
  const [input, setInput] = useState("");
  const [suggestions, setSuggestions] = useState<string[]>([OPENERS[page] ?? OPENERS.home]);
  const [latency, setLatency] = useState<Latency | null>(null);
  const [error, setError] = useState<string | null>(null);
  const recRef = useRef<Recognizer | null>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const turnsRef = useRef<Turn[]>([]);

  useEffect(() => {
    turnsRef.current = turns;
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [turns]);

  useEffect(() => () => {
    recRef.current?.abort();
    stopSpeaking();
  }, []);

  const act = useCallback((action: AssistantAction) => {
    if (action === "none") return;
    window.dispatchEvent(new CustomEvent(ASSISTANT_EVENT, { detail: action }));
    if (action === "start_interview") router.push("/apply");
    else if (action === "open_console") router.push("/console");
    else if (action === "open_agent_builder") router.push("/agents");
    else if ((action === "show_pipeline" || action === "show_packs" || action === "next_step")
      && page !== "how-it-works") {
      router.push(action === "show_packs" ? "/how-it-works#agents" : "/how-it-works#pipeline");
    }
  }, [page, router]);

  const send = useCallback(async (text: string) => {
    const message = text.trim();
    if (!message) return;
    setError(null);
    setInput("");
    setCaption("");
    const history = turnsRef.current;
    setTurns([...history, { role: "user", text: message }]);
    setOrb("thinking");
    try {
      const t0 = performance.now();
      const r = await askAssistant(message, page, history, context);
      const brainMs = Math.round(performance.now() - t0);
      setTurns((t) => [...t, { role: "assistant", text: r.reply }]);
      setSuggestions(r.suggestions.length ? r.suggestions : []);
      setLatency({ brainMs, firstAudioMs: null, via: "…", model: r.model });
      setOrb("speaking");
      // Act as it starts talking, not after: "taking you there" should move.
      act(r.action);
      const spoken = await say(r.reply);
      setLatency({ brainMs, firstAudioMs: spoken.firstAudioMs, via: spoken.via, model: r.model });
    } catch (err) {
      setError(err instanceof ApiUnreachable ? "The assistant is offline right now." : "Something went wrong. Try again.");
    } finally {
      setOrb("idle");
    }
  }, [act, context, page]);

  const listen = useCallback(() => {
    if (orb === "listening") {
      recRef.current?.stop();
      return;
    }
    stopSpeaking(); // talking over the agent interrupts it
    const rec = createRecognizer();
    if (!rec) {
      setError("Voice input needs Chrome or Edge. You can type instead.");
      return;
    }
    recRef.current = rec;
    let finalText = "";
    rec.onresult = (e) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i];
        if (res.isFinal) finalText += res[0].transcript;
        else interim += res[0].transcript;
      }
      setCaption(finalText || interim);
    };
    rec.onend = () => {
      setOrb("idle");
      if (finalText.trim()) void send(finalText);
    };
    rec.onerror = () => setOrb("idle");
    setOrb("listening");
    rec.start();
  }, [orb, send]);

  if (!inline && !open) {
    return (
      <button
        onClick={() => setOpen(true)}
        aria-label="Talk to the VoxGate assistant"
        className="fixed bottom-5 right-5 z-[70] flex items-center gap-2.5 rounded-[var(--r-pill)] py-2.5 pl-3 pr-4 text-[13.5px] font-semibold text-[#0a0a12] shadow-[0_18px_50px_-12px_rgba(200,123,255,0.55)] transition-transform hover:scale-[1.03] active:scale-[0.98]"
        style={{ background: "var(--siri-gradient)" }}
      >
        <span className="relative grid h-6 w-6 place-items-center rounded-full bg-[#0a0a12]/15">
          <Sparkle size={14} weight="fill" />
          <span className="absolute inset-0 animate-ping rounded-full bg-white/30 motion-reduce:hidden" />
        </span>
        Ask Lucy
      </button>
    );
  }

  const panel = (
    <div
      className={`glass flex flex-col overflow-hidden rounded-[var(--r-card)] ${
        inline ? "h-[560px] w-full" : "h-[min(600px,calc(100dvh-40px))] w-[min(400px,calc(100vw-32px))]"
      }`}
      role="region"
      aria-label="VoxGate voice assistant"
    >
      <div className="flex items-center justify-between border-b border-glass-border-soft px-4 py-3">
        <div className="flex items-center gap-2.5">
          <span className="relative flex h-2.5 w-2.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[var(--color-status-approved)] opacity-60 motion-reduce:hidden" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-[var(--color-status-approved)]" />
          </span>
          <span className="text-[13.5px] font-semibold">Lucy</span>
          <span className="text-[12px] text-text-faint">VoxGate voice assistant</span>
        </div>
        {!inline ? (
          <button onClick={() => { stopSpeaking(); setOpen(false); }} aria-label="Close assistant"
            className="grid h-8 w-8 place-items-center rounded-full text-text-dim hover:bg-white/[0.06] hover:text-text">
            <X size={16} />
          </button>
        ) : null}
      </div>

      <div className="flex justify-center pt-3">
        <div className={inline ? "" : "scale-[0.62] -my-7"}>
          <VoiceOrb state={orb} analyser={agentAnalyser()} />
        </div>
      </div>
      <p className="h-5 text-center text-[11.5px] uppercase tracking-[0.16em] text-text-faint" aria-live="polite">
        {orb === "listening" ? "Listening" : orb === "thinking" ? "Thinking" : orb === "speaking" ? "Speaking" : ""}
      </p>

      <div ref={logRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-3" role="log" aria-live="polite">
        {turns.length === 0 ? (
          <p className="text-[13.5px] leading-relaxed text-text-dim">
            Hi, I&apos;m Lucy. Ask me anything about VoxGate, out loud or by typing. I can also take you
            where you need to go.
          </p>
        ) : null}
        {turns.map((t, i) => (
          <div key={i} className={t.role === "user" ? "flex justify-end" : ""}>
            <p className={`max-w-[88%] rounded-[12px] px-3 py-2 text-[13.5px] leading-relaxed ${
              t.role === "user" ? "bg-[var(--color-siri-2)]/25 text-text" : "bg-[var(--color-surface-2)] text-text"
            }`}>
              {t.text}
            </p>
          </div>
        ))}
        {caption ? <p className="text-right text-[13px] italic text-text-dim">&ldquo;{caption}&rdquo;</p> : null}
        {error ? <p className="text-[12.5px] text-[var(--color-status-needs-attention)]">{error}</p> : null}
      </div>

      {suggestions.length ? (
        <div className="flex flex-wrap gap-1.5 px-4 pb-2">
          {suggestions.map((s) => (
            <button key={s} onClick={() => void send(s)} disabled={orb === "thinking"}
              className="rounded-[var(--r-pill)] border border-glass-border px-3 py-1 text-[12px] text-text-dim transition-colors hover:border-white/25 hover:text-text disabled:opacity-40">
              {s}
            </button>
          ))}
        </div>
      ) : null}

      <div className="flex items-center gap-2 border-t border-glass-border-soft p-2">
        <button onClick={listen} disabled={orb === "thinking" || !speechSupported()}
          aria-label={orb === "listening" ? "Stop listening" : "Talk to Lucy"}
          className={`grid h-10 w-10 shrink-0 place-items-center rounded-full transition-colors disabled:opacity-30 ${
            orb === "listening" ? "bg-[var(--color-status-rejected)]/25 text-text" : "text-text-dim hover:bg-white/[0.06] hover:text-text"
          }`}>
          {orb === "listening" ? <Stop size={17} weight="fill" /> : <Microphone size={18} weight="fill" />}
        </button>
        <input value={input} onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") void send(input); }}
          placeholder="Ask about VoxGate…" aria-label="Message the assistant"
          className="h-10 w-full min-w-0 bg-transparent px-1 text-[14px] text-text outline-none placeholder:text-text-faint" />
        <button onClick={() => void send(input)} disabled={!input.trim() || orb === "thinking"} aria-label="Send"
          className="grid h-10 w-10 shrink-0 place-items-center rounded-full text-[#0a0a12] disabled:opacity-25"
          style={{ background: "var(--siri-gradient)" }}>
          <PaperPlaneRight size={16} weight="fill" />
        </button>
      </div>

      <div className="flex justify-between border-t border-glass-border-soft px-4 py-1.5 font-mono text-[10.5px] text-text-faint"
        style={{ fontFamily: "var(--font-geist-mono), monospace" }}>
        <span>brain {latency?.brainMs ?? "–"} ms{latency?.model ? ` · ${latency.model.split("/").pop()}` : ""}</span>
        <span>voice {latency?.firstAudioMs ?? "–"} ms · {latency?.via ?? "–"}</span>
      </div>
    </div>
  );

  return inline ? panel : <div className="fixed bottom-5 right-5 z-[70]">{panel}</div>;
}

/** The floating assistant for every page except where a page embeds its own. */
export function FloatingAssistant() {
  const pathname = usePathname() ?? "/";
  // The interview owns the microphone on /apply, and How it works embeds the
  // assistant inline, so a second floating one would only compete.
  if (/^\/(apply|how-it-works)/.test(pathname)) return null;
  return <VoiceAssistant />;
}
