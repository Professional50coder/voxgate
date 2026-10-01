"use client";

import {
  Microphone, PaperPlaneRight, PhoneDisconnect, Sparkle, SpeakerHigh, SpeakerSlash, X,
} from "@phosphor-icons/react";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { VoiceOrb, type OrbState } from "@/components/voice-orb";
import { type AssistantAction, ApiUnreachable, askAssistant } from "@/lib/api";
import { createRecognizer, speechSupported, type Recognizer } from "@/lib/speech";
import { agentAnalyser, say, stopSpeaking } from "@/lib/voice";

type Turn = { role: "user" | "assistant"; text: string };

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

/** What Lucy says when she opens herself, per page. Short: it is unprompted. */
const GREETINGS: Record<string, string> = {
  "how-it-works": "Hi, I'm Lucy. I'll walk you through how VoxGate works as you scroll. Tap to talk and ask me anything.",
  home: "Hi, I'm Lucy. I can tell you what VoxGate does for your business, or start a demo interview. Tap to talk anytime.",
  console: "Hi, I'm Lucy. Ask me what needs your attention in the queue.",
  agents: "Hi, I'm Lucy. Tell me your use case and I'll help you design the agent.",
};

/** Fired for actions the page itself should perform, e.g. highlighting a step. */
export const ASSISTANT_EVENT = "voxgate:assistant-action";
/** Fired by a page to have Lucy say something, e.g. when a section scrolls in. */
export const NARRATE_EVENT = "voxgate:narrate";

/** Ask Lucy to say a line, if she is free and the visitor has not muted her. */
export function narrate(text: string) {
  window.dispatchEvent(new CustomEvent(NARRATE_EVENT, { detail: text }));
}

const MUTE_KEY = "voxgate.assistant.muted";
const GREETED_KEY = "voxgate.assistant.greeted";
// Scrolled this far, the visitor is reading, not bouncing: a good moment to say hi.
const GREET_AFTER_PX = 240;
// Silent listens in a row before a hands-free conversation ends by itself.
const MAX_SILENT_LISTENS = 2;

function readStore(storage: "local" | "session", key: string): string | null {
  try {
    return (storage === "local" ? localStorage : sessionStorage).getItem(key);
  } catch {
    return null;
  }
}

function writeStore(storage: "local" | "session", key: string, value: string) {
  try {
    (storage === "local" ? localStorage : sessionStorage).setItem(key, value);
  } catch {
    // Private mode or blocked storage: the preference lasts for this page only.
  }
}

/**
 * VoxGate's voice assistant. One brain (/assistant), a persona per page, the
 * agent's human voice (/tts) and a closed set of actions it can take on the
 * site.
 *
 * "Tap to talk" starts a hands-free conversation: Lucy listens, answers, and
 * listens again until the visitor ends it or goes quiet. Talking over her
 * stops her, the way a person would. She opens herself when a visitor starts
 * reading, and can narrate a page as it scrolls, but only speaks aloud after
 * the visitor's first click or key press (browsers block sound before that)
 * and never once they have muted her.
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
  const [turns, setTurns] = useState<Turn[]>(() =>
    inline ? [{ role: "assistant", text: GREETINGS[page] ?? GREETINGS.home }] : []);
  const [caption, setCaption] = useState("");
  const [input, setInput] = useState("");
  const [suggestions, setSuggestions] = useState<string[]>([OPENERS[page] ?? OPENERS.home]);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState(false);
  const [muted, setMuted] = useState(false);

  const recRef = useRef<Recognizer | null>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const turnsRef = useRef<Turn[]>([]);
  const liveRef = useRef(false);
  const mutedRef = useRef(false);
  const busyRef = useRef(false);
  const unlockedRef = useRef(false);
  const pendingRef = useRef<string | null>(null);
  const silentRef = useRef(0);
  const startListeningRef = useRef<() => void>(() => {});

  useEffect(() => {
    turnsRef.current = turns;
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [turns]);

  useEffect(() => {
    liveRef.current = live;
  }, [live]);

  // Restore the visitor's mute choice after hydration; storage is client-only.
  useEffect(() => {
    const stored = readStore("local", MUTE_KEY) === "1";
    mutedRef.current = stored;
    if (stored) queueMicrotask(() => setMuted(true));
  }, []);

  useEffect(() => () => {
    recRef.current?.abort();
    stopSpeaking();
  }, []);

  /** Speak aloud if allowed; otherwise hold the line for the first gesture. */
  const speakOut = useCallback(async (text: string) => {
    if (mutedRef.current) return;
    if (!unlockedRef.current) {
      pendingRef.current = text;
      return;
    }
    setOrb("speaking");
    await say(text);
    setOrb((o) => (o === "speaking" ? "idle" : o));
  }, []);

  // Browsers allow sound only after a click, tap or key press. The first one
  // anywhere on the page unlocks Lucy and plays whatever she was waiting to say.
  useEffect(() => {
    const unlock = () => {
      if (unlockedRef.current) return;
      unlockedRef.current = true;
      const pending = pendingRef.current;
      pendingRef.current = null;
      if (pending && !busyRef.current && !liveRef.current) void speakOut(pending);
    };
    const opts = { capture: true, passive: true } as const;
    window.addEventListener("pointerdown", unlock, opts);
    window.addEventListener("keydown", unlock, opts);
    return () => {
      window.removeEventListener("pointerdown", unlock, opts);
      window.removeEventListener("keydown", unlock, opts);
    };
  }, [speakOut]);

  const greet = useCallback(() => {
    const line = GREETINGS[page] ?? GREETINGS.home;
    setTurns((t) => (t.length ? t : [{ role: "assistant", text: line }]));
    void speakOut(line);
  }, [page, speakOut]);

  // Embedded on a page: the greeting is already in the log (initial state);
  // queue it to be spoken at the visitor's first click or key press.
  useEffect(() => {
    if (inline && !mutedRef.current) pendingRef.current = GREETINGS[page] ?? GREETINGS.home;
  }, [inline, page]);

  // Floating: open and say hello once the visitor starts reading, once per
  // session, and never again after they have closed her.
  useEffect(() => {
    if (inline || readStore("session", GREETED_KEY)) return;
    const onScroll = () => {
      if (window.scrollY < GREET_AFTER_PX) return;
      window.removeEventListener("scroll", onScroll);
      writeStore("session", GREETED_KEY, "1");
      setOpen(true);
      greet();
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [inline, greet]);

  // Pages narrate sections through an event. Skipped while a conversation is
  // under way: interrupting the visitor to describe the page would be rude.
  useEffect(() => {
    const onNarrate = (e: Event) => {
      const text = (e as CustomEvent<string>).detail;
      if (!text || busyRef.current || liveRef.current) return;
      setTurns((t) => [...t, { role: "assistant", text }]);
      void speakOut(text);
    };
    window.addEventListener(NARRATE_EVENT, onNarrate);
    return () => window.removeEventListener(NARRATE_EVENT, onNarrate);
  }, [speakOut]);

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
    busyRef.current = true;
    setError(null);
    setInput("");
    setCaption("");
    const history = turnsRef.current;
    setTurns([...history, { role: "user", text: message }]);
    setOrb("thinking");
    try {
      const r = await askAssistant(message, page, history, context);
      setTurns((t) => [...t, { role: "assistant", text: r.reply }]);
      setSuggestions(r.suggestions.length ? r.suggestions : []);
      // Act as she starts talking, not after: "taking you there" should move.
      act(r.action);
      await speakOut(r.reply);
    } catch (err) {
      setError(err instanceof ApiUnreachable ? "Lucy is offline right now." : "Something went wrong. Try again.");
      setLive(false);
    } finally {
      busyRef.current = false;
      setOrb("idle");
    }
    // Hands-free: her turn is over, so it is the visitor's again.
    if (liveRef.current) startListeningRef.current();
  }, [act, context, page, speakOut]);

  const startListening = useCallback(() => {
    stopSpeaking(); // talking over Lucy interrupts her
    const rec = createRecognizer();
    if (!rec) {
      setError("Voice needs Chrome or Edge. You can type instead.");
      setLive(false);
      return;
    }
    recRef.current?.abort();
    recRef.current = rec;
    let finalText = "";
    // Unfinalised words still count: anything said gets an answer.
    let lastInterim = "";
    rec.onresult = (e) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i];
        if (res.isFinal) finalText += res[0].transcript;
        else interim += res[0].transcript;
      }
      lastInterim = interim;
      setCaption(finalText || interim);
    };
    rec.onend = () => {
      if (recRef.current !== rec) return;
      setOrb((o) => (o === "listening" ? "idle" : o));
      const said = (finalText || lastInterim).trim();
      if (said) {
        silentRef.current = 0;
        void send(said);
      } else if (liveRef.current) {
        silentRef.current += 1;
        if (silentRef.current >= MAX_SILENT_LISTENS) setLive(false);
        else startListeningRef.current();
      }
    };
    rec.onerror = (e) => {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        setError("Allow the microphone to talk to Lucy, or type below.");
        setLive(false);
      }
    };
    setOrb("listening");
    rec.start();
  }, [send]);

  useEffect(() => {
    startListeningRef.current = startListening;
  }, [startListening]);

  function startConversation() {
    unlockedRef.current = true;
    pendingRef.current = null;
    silentRef.current = 0;
    setError(null);
    setLive(true);
    liveRef.current = true;
    startListening();
  }

  function endConversation() {
    setLive(false);
    liveRef.current = false;
    recRef.current?.abort();
    recRef.current = null;
    stopSpeaking();
    setCaption("");
    setOrb("idle");
  }

  function toggleMute() {
    const next = !mutedRef.current;
    mutedRef.current = next;
    setMuted(next);
    writeStore("local", MUTE_KEY, next ? "1" : "0");
    if (next) stopSpeaking();
  }

  function close() {
    endConversation();
    writeStore("session", GREETED_KEY, "1");
    setOpen(false);
  }

  if (!inline && !open) {
    return (
      <button
        onClick={() => setOpen(true)}
        aria-label="Talk to Lucy, the VoxGate assistant"
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

  const status = live
    ? orb === "listening" ? "Listening… just talk" : orb === "thinking" ? "Thinking" : orb === "speaking" ? "Speaking · talk to interrupt" : "In conversation"
    : orb === "thinking" ? "Thinking" : orb === "speaking" ? "Speaking" : "";

  const panel = (
    <div
      className={`glass flex flex-col overflow-hidden rounded-[var(--r-card)] ${
        inline ? "h-[580px] w-full" : "h-[min(620px,calc(100dvh-40px))] w-[min(400px,calc(100vw-32px))]"
      }`}
      role="region"
      aria-label="Lucy, the VoxGate voice assistant"
    >
      <div className="flex items-center justify-between border-b border-glass-border-soft px-4 py-3">
        <div className="flex items-center gap-2.5">
          <span className="relative flex h-2.5 w-2.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[var(--color-status-approved)] opacity-60 motion-reduce:hidden" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-[var(--color-status-approved)]" />
          </span>
          <span className="text-[13.5px] font-semibold">Lucy</span>
          <span className="text-[12px] text-text-faint">VoxGate assistant</span>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={toggleMute} aria-pressed={muted} aria-label={muted ? "Unmute Lucy" : "Mute Lucy"}
            title={muted ? "Unmute" : "Mute"}
            className="grid h-8 w-8 place-items-center rounded-full text-text-dim hover:bg-white/[0.06] hover:text-text">
            {muted ? <SpeakerSlash size={16} /> : <SpeakerHigh size={16} />}
          </button>
          {!inline ? (
            <button onClick={close} aria-label="Close assistant"
              className="grid h-8 w-8 place-items-center rounded-full text-text-dim hover:bg-white/[0.06] hover:text-text">
              <X size={16} />
            </button>
          ) : null}
        </div>
      </div>

      <div className="flex justify-center pt-3">
        <div className={inline ? "" : "scale-[0.62] -my-7"}>
          <VoiceOrb state={orb} analyser={agentAnalyser()} />
        </div>
      </div>
      <p className="h-5 text-center text-[11.5px] uppercase tracking-[0.16em] text-text-faint" aria-live="polite">
        {status}
      </p>

      <div ref={logRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-3" role="log" aria-live="polite">
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

      {suggestions.length && !live ? (
        <div className="flex flex-wrap gap-1.5 px-4 pb-2">
          {suggestions.map((s) => (
            <button key={s} onClick={() => void send(s)} disabled={orb === "thinking"}
              className="rounded-[var(--r-pill)] border border-glass-border px-3 py-1 text-[12px] text-text-dim transition-colors hover:border-white/25 hover:text-text disabled:opacity-40">
              {s}
            </button>
          ))}
        </div>
      ) : null}

      <div className="border-t border-glass-border-soft p-3">
        {live ? (
          <button onClick={endConversation}
            className="flex h-12 w-full items-center justify-center gap-2 rounded-[var(--r-pill)] bg-[var(--color-status-rejected)]/20 text-[14px] font-semibold text-text transition-colors hover:bg-[var(--color-status-rejected)]/30">
            <PhoneDisconnect size={18} weight="fill" /> End conversation
          </button>
        ) : (
          <button onClick={startConversation} disabled={!speechSupported()}
            title={speechSupported() ? "Talk to Lucy hands-free" : "Voice needs Chrome or Edge"}
            className="flex h-12 w-full items-center justify-center gap-2 rounded-[var(--r-pill)] text-[14px] font-semibold text-[#0a0a12] transition-transform active:scale-[0.98] disabled:opacity-40"
            style={{ background: "var(--siri-gradient)" }}>
            <Microphone size={18} weight="fill" /> Tap to talk
          </button>
        )}
        <div className="mt-2 flex items-center gap-2">
          <input value={input} onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void send(input); }}
            placeholder="Or type a question…" aria-label="Message Lucy"
            className="h-9 w-full min-w-0 rounded-[var(--r-pill)] border border-glass-border-soft bg-transparent px-3.5 text-[13.5px] text-text outline-none placeholder:text-text-faint focus:border-[var(--color-siri-2)]" />
          <button onClick={() => void send(input)} disabled={!input.trim() || orb === "thinking"} aria-label="Send"
            className="grid h-9 w-9 shrink-0 place-items-center rounded-full border border-glass-border text-text-dim hover:text-text disabled:opacity-25">
            <PaperPlaneRight size={15} weight="fill" />
          </button>
        </div>
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
