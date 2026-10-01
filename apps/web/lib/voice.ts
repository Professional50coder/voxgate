/**
 * The agent's voice in the browser.
 *
 * Plays the pack agent's Cartesia voice by pointing an <audio> element at the
 * streamed /tts URL, so sound starts on the first chunk. If the API answers 503
 * (no key, or both of the agent's voices down) or the audio fails to start, the
 * browser's own voice reads the line instead: speech degrades, never stops.
 *
 * The element is routed through one AudioContext analyser, so the orb can move
 * with the agent's voice as well as the user's.
 */
import { voiceUrl } from "@/lib/api";
import { speak as browserSpeak } from "@/lib/speech";

export type Spoken = {
  /** "agent" when the agent's own voice played, "browser" on fallback. */
  via: "agent" | "browser";
  /** Request to first sound, measured in the page. */
  firstAudioMs: number | null;
};

let ctx: AudioContext | null = null;
let analyser: AnalyserNode | null = null;
let current: HTMLAudioElement | null = null;

/** The analyser carrying the agent's voice, created on first use. */
export function agentAnalyser(): AnalyserNode | null {
  return analyser;
}

function ensureGraph(el: HTMLAudioElement) {
  try {
    ctx ??= new AudioContext();
    if (!analyser) {
      analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      analyser.smoothingTimeConstant = 0.72;
      analyser.connect(ctx.destination);
    }
    ctx.createMediaElementSource(el).connect(analyser);
    if (ctx.state === "suspended") void ctx.resume();
  } catch {
    // Analysis is decoration. If the graph cannot be built, the element still
    // plays through its default output.
  }
}

/** Stop whatever the agent is saying. Used when the user starts talking. */
export function stopSpeaking() {
  if (current) {
    current.pause();
    current.src = "";
    current = null;
  }
  if (typeof window !== "undefined") window.speechSynthesis?.cancel();
}

/** Say a line in this pack agent's voice. Resolves when it has finished. */
export function say(text: string, packId?: string): Promise<Spoken> {
  stopSpeaking();
  if (typeof window === "undefined" || !text.trim()) {
    return Promise.resolve({ via: "browser", firstAudioMs: null });
  }
  const started = performance.now();
  const el = new Audio();
  el.crossOrigin = "anonymous";
  el.preload = "auto";
  current = el;
  ensureGraph(el);

  return new Promise((resolve) => {
    let firstAudioMs: number | null = null;
    let settled = false;
    const finish = (r: Spoken) => {
      if (settled) return;
      settled = true;
      resolve(r);
    };
    const fallback = async () => {
      if (settled || current !== el) return finish({ via: "browser", firstAudioMs: null });
      current = null;
      await browserSpeak(text);
      finish({ via: "browser", firstAudioMs: null });
    };
    el.addEventListener("playing", () => {
      firstAudioMs ??= Math.round(performance.now() - started);
    }, { once: true });
    el.addEventListener("ended", () => finish({ via: "agent", firstAudioMs }));
    el.addEventListener("error", () => void fallback());
    // Interrupted by stopSpeaking(): resolve rather than hang the caller.
    el.addEventListener("emptied", () => finish({ via: "agent", firstAudioMs }));
    el.src = voiceUrl(text, packId);
    el.play().catch(() => void fallback());
  });
}
