"use client";

import {
  ArrowRight,
  Check,
  Microphone,
  MicrophoneSlash,
  SpinnerGap,
  WarningCircle,
} from "@phosphor-icons/react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

import { VoiceOrb, type OrbState } from "@/components/voice-orb";
import {
  ApiUnreachable,
  type Case,
  type Pack,
  createCase,
  getCase,
  getPacks,
  submitInterview,
} from "@/lib/api";
import { createRecognizer, normalize, speak, speechSupported, type Recognizer } from "@/lib/speech";

type Phase = "intro" | "interview" | "submitting" | "done" | "offline";

const OPENING =
  "Hello. I will ask you a few questions to open your account. Please answer out loud after each one.";

export function InterviewFlow({ caseId: invitedCaseId }: { caseId?: string }) {
  const [pack, setPack] = useState<Pack | null>(null);
  const [phase, setPhase] = useState<Phase>("intro");
  const [orb, setOrb] = useState<OrbState>("idle");
  const [fieldIndex, setFieldIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [transcript, setTranscript] = useState("");
  const [draft, setDraft] = useState("");
  const [question, setQuestion] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [result, setResult] = useState<Case | null>(null);
  const [caseId, setCaseId] = useState<string | null>(invitedCaseId ?? null);
  const [invalidInvite, setInvalidInvite] = useState(false);

  const analyserRef = useRef<AnalyserNode | null>(null);
  const [analyser, setAnalyser] = useState<AnalyserNode | null>(null);
  const recRef = useRef<Recognizer | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  // useMemo, because `pack?.fields ?? []` builds a new array every render and
  // every callback that depends on it is then rebuilt every render too.
  const fields = useMemo(() => pack?.fields ?? [], [pack]);
  const currentField = fields[fieldIndex];
  const isLastField = fieldIndex + 1 === fields.length;

  // Whether the browser can do speech at all is external, read-only state that
  // does not exist during SSR. useSyncExternalStore is the API for exactly
  // that: `() => true` is the server's answer, and React reconciles on hydrate
  // without the render-then-immediately-setState that an effect would cause.
  const supported = useSyncExternalStore(
    () => () => {},              // capability never changes within a page load
    speechSupported,
    () => true,
  );

  useEffect(() => {
    getPacks()
      .then((packs) => setPack(packs[0] ?? null))
      .catch((err) => {
        if (err instanceof ApiUnreachable) setPhase("offline");
      });
  }, []);

  // An invite link points at one specific case. Verify it before letting the
  // applicant start, so a stale or already-completed link fails clearly rather
  // than part-way through the conversation.
  //
  // Split out with `invitedCaseId` as a real dependency instead of being folded
  // into a mount-only effect with an incomplete dependency list. Merging them
  // meant a changed invite was silently never re-checked, and re-running the
  // merged effect would have torn down the microphone as a side effect.
  useEffect(() => {
    if (!invitedCaseId) return;
    let cancelled = false;
    getCase(invitedCaseId)
      .then((c) => {
        if (cancelled) return;
        if (c.status !== "awaiting_interview" && c.interrupt?.type !== "interview") {
          setResult(c);
          setPhase("done");
        }
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiUnreachable) setPhase("offline");
        else setInvalidInvite(true);
      });
    return () => {
      cancelled = true;
    };
  }, [invitedCaseId]);

  // Teardown only. Kept mount-scoped on purpose: the microphone and any speech
  // in progress must survive every re-render and stop exactly once, on unmount.
  useEffect(() => {
    return () => {
      recRef.current?.abort();
      streamRef.current?.getTracks().forEach((t) => t.stop());
      if (typeof window !== "undefined") window.speechSynthesis?.cancel();
    };
  }, []);

  /** Mic stream feeds the orb's amplitude. Not connected to destination, so no feedback. */
  const openMic = useCallback(async () => {
    if (analyserRef.current) return analyserRef.current;
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    streamRef.current = stream;
    const ctx = new AudioContext();
    const node = ctx.createAnalyser();
    node.fftSize = 512;
    node.smoothingTimeConstant = 0.72;
    ctx.createMediaStreamSource(stream).connect(node);
    analyserRef.current = node;
    setAnalyser(node);
    return node;
  }, []);

  const listen = useCallback((): Promise<string> => {
    return new Promise((resolve) => {
      const rec = createRecognizer();
      if (!rec) {
        resolve("");
        return;
      }
      recRef.current = rec;
      let finalText = "";
      rec.onresult = (event) => {
        let interim = "";
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const res = event.results[i];
          if (res.isFinal) finalText += res[0].transcript;
          else interim += res[0].transcript;
        }
        setTranscript(finalText || interim);
      };
      rec.onerror = () => resolve(finalText);
      rec.onend = () => resolve(finalText);
      rec.start();
    });
  }, []);

  const askField = useCallback(
    async (index: number) => {
      const field = fields[index];
      if (!field) return;
      const text = pack?.reask_hints?.[field] ?? `Please tell me your ${field.replace(/_/g, " ")}.`;
      setQuestion(text);
      setTranscript("");
      setDraft("");
      setNotice(null);

      setOrb("speaking");
      await speak(text);

      setOrb("listening");
      const heard = await listen();
      setOrb("thinking");
      setTranscript(heard);

      const value = normalize(field, heard);
      if (value === null) {
        setDraft(heard);
        setNotice(
          heard
            ? "I did not catch that clearly. Correct it below, or press the mic to answer again."
            : "I did not hear anything. Press the mic to try again, or type your answer.",
        );
        setOrb("idle");
        return;
      }
      setDraft(value);
      setOrb("idle");
    },
    [fields, pack, listen],
  );

  async function start() {
    if (!invitedCaseId) {
      try {
        const created = await createCase(pack?.pack_id ?? "kyc-uae");
        setCaseId(created.case_id);
      } catch (err) {
        if (err instanceof ApiUnreachable) {
          setPhase("offline");
          return;
        }
      }
    }
    setPhase("interview");
    await openMic().catch(() => null);
    setOrb("speaking");
    await speak(OPENING);
    await askField(0);
  }

  async function confirmAnswer() {
    if (!currentField || !draft.trim()) return;
    const value = normalize(currentField, draft) ?? draft.trim();
    const next = { ...answers, [currentField]: value };
    setAnswers(next);

    if (fieldIndex + 1 < fields.length) {
      setFieldIndex(fieldIndex + 1);
      await askField(fieldIndex + 1);
      return;
    }

    setPhase("submitting");
    setOrb("thinking");
    try {
      const updated = await submitInterview(caseId!, next);
      setResult(updated);
      setPhase("done");
      setOrb("speaking");
      await speak(closingLine(updated));
      setOrb("idle");
    } catch {
      setNotice("Could not submit the interview. The backend may have stopped.");
      setPhase("interview");
      setOrb("idle");
    }
  }

  async function retryField() {
    if (!currentField) return;
    setOrb("listening");
    setTranscript("");
    const heard = await listen();
    setOrb("thinking");
    setTranscript(heard);
    const value = normalize(currentField, heard);
    setDraft(value ?? heard);
    setNotice(value === null && heard ? "Still unclear. You can edit it below." : null);
    setOrb("idle");
  }

  if (invalidInvite) {
    return (
      <Centered>
        <WarningCircle size={26} weight="duotone" color="var(--color-status-needs-attention)" />
        <h1 className="mt-5 text-2xl font-semibold">This invite is not valid</h1>
        <p className="mt-3 max-w-[46ch] text-[14px] leading-relaxed text-text-dim">
          The link may have expired, or the case it pointed to no longer exists. Ask
          whoever sent it for a fresh one.
        </p>
      </Centered>
    );
  }

  if (phase === "offline") {
    return (
      <Centered>
        <WarningCircle size={26} weight="duotone" color="var(--color-status-needs-attention)" />
        <h1 className="mt-5 text-2xl font-semibold">Backend is not running</h1>
        <p className="mt-3 max-w-[46ch] text-[14px] leading-relaxed text-text-dim">
          The interview needs the VoxGate API. Start it from the repo root and reload.
        </p>
        <pre
          className="mt-6 rounded-[var(--r-input)] border border-glass-border-soft bg-[#05070e] px-4 py-3 text-[12.5px] text-text-dim"
          style={{ fontFamily: "var(--font-geist-mono), monospace" }}
        >
          uv run uvicorn voxgate.service.app:app
        </pre>
      </Centered>
    );
  }

  return (
    <div className="min-h-[100dvh]">
      <header className="flex h-16 items-center justify-between px-6">
        <Link href="/" className="flex items-center gap-2.5">
          <span
            aria-hidden="true"
            className="h-5 w-5 rounded-full"
            style={{ background: "var(--siri-gradient)" }}
          />
          <span className="text-[15px] font-semibold tracking-tight">VoxGate</span>
        </Link>
        {phase === "interview" ? (
          <span className="text-[13px] text-text-faint">
            {fieldIndex + 1} of {fields.length}
          </span>
        ) : null}
      </header>

      <main className="mx-auto flex max-w-[640px] flex-col items-center px-6 pb-24 pt-10 text-center">
        <VoiceOrb state={orb} analyser={analyser} />

        <p className="mt-5 h-5 text-[13px] uppercase tracking-[0.16em] text-text-faint" aria-live="polite">
          {orb === "listening" ? "Listening" : orb === "speaking" ? "Speaking" : orb === "thinking" ? "Thinking" : ""}
        </p>

        {phase === "intro" ? (
          <>
            <h1 className="mt-6 text-3xl font-semibold leading-tight tracking-tight md:text-4xl">
              Open your account by talking.
            </h1>
            <p className="mt-5 max-w-[46ch] text-[15px] leading-relaxed text-text-dim">
              {pack
                ? `${pack.display_name}. ${pack.fields.length} questions, about two minutes.`
                : "Loading the compliance pack."}
            </p>

            {!supported ? (
              <p className="mt-6 max-w-[48ch] rounded-[var(--r-input)] border border-[var(--color-status-awaiting-interview)]/30 px-4 py-3 text-[13px] leading-relaxed text-[var(--color-status-awaiting-interview)]">
                This browser does not support speech recognition. Chrome or Edge will let
                you answer out loud. You can still type every answer here.
              </p>
            ) : null}

            <button
              onClick={() => void start()}
              disabled={!pack}
              className="mt-9 rounded-[var(--r-pill)] px-8 py-3.5 text-[15px] font-semibold text-[#0a0a12] transition-transform active:scale-[0.98] disabled:opacity-40"
              style={{ background: "var(--siri-gradient)" }}
            >
              Start the interview
            </button>
            <p className="mt-4 text-[12.5px] text-text-faint">
              Your microphone is used only while a question is open.
            </p>
          </>
        ) : null}

        {phase === "interview" || phase === "submitting" ? (
          <>
            <h1 className="mt-6 text-2xl font-semibold leading-snug tracking-tight md:text-[28px]">
              {question}
            </h1>

            <p className="mt-6 min-h-[28px] text-[15px] italic text-text-dim" aria-live="polite">
              {transcript ? `"${transcript}"` : ""}
            </p>

            {notice ? (
              <p className="mt-3 max-w-[46ch] text-[13px] leading-relaxed text-[var(--color-status-awaiting-interview)]">
                {notice}
              </p>
            ) : null}

            {/*
              One control, not two. The submit button used to float on its own
              row below the input, which read as dated for a reason worth naming:
              the action was detached from the thing it acted on, so the eye had
              to travel to find it and the Enter key was the undocumented fast
              path everyone actually used. Mic, field and send now sit in a
              single rounded surface that lights up as a whole on focus, which
              is how every modern compose control behaves.
            */}
            <div
              className="group mt-7 flex w-full max-w-[520px] items-center gap-2 rounded-[var(--r-pill)] border border-glass-border bg-[var(--color-surface-2)] p-1.5 transition-colors focus-within:border-[var(--color-siri-2)]"
            >
              <button
                onClick={() => void retryField()}
                disabled={orb === "listening" || orb === "speaking" || !supported}
                aria-label="Answer again by voice"
                title={supported ? "Answer by voice" : "Voice input is unavailable in this browser"}
                className="grid h-11 w-11 shrink-0 place-items-center rounded-full text-text-dim transition-colors hover:bg-white/[0.06] hover:text-text active:scale-[0.96] disabled:opacity-30"
              >
                {supported ? <Microphone size={19} weight="fill" /> : <MicrophoneSlash size={19} />}
              </button>

              <input
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void confirmAnswer();
                }}
                placeholder={isLastField ? "Your final answer" : "Type your answer, or use the mic"}
                aria-label={`Answer for ${currentField ?? "question"}`}
                className="h-11 w-full min-w-0 bg-transparent px-1 text-[15px] text-text outline-none placeholder:text-text-faint"
              />

              <button
                onClick={() => void confirmAnswer()}
                disabled={!draft.trim() || phase === "submitting"}
                aria-label={isLastField ? "Finish the interview" : "Next question"}
                title={isLastField ? "Finish" : "Next question"}
                className="grid h-11 w-11 shrink-0 place-items-center rounded-full text-[#0a0a12] transition-[transform,opacity] duration-200 active:scale-[0.94] disabled:opacity-25 motion-reduce:transition-none"
                style={{ background: "var(--siri-gradient)" }}
              >
                {phase === "submitting" ? (
                  // A real spinner. "Submitting" as static text gave no signal
                  // that anything was happening, on the one action in the flow
                  // that waits on a graph run.
                  <SpinnerGap size={19} weight="bold" className="animate-spin" />
                ) : isLastField ? (
                  <Check size={19} weight="bold" />
                ) : (
                  <ArrowRight size={19} weight="bold" />
                )}
              </button>
            </div>

            <p className="mt-3 h-4 text-[12.5px] text-text-faint">
              {phase === "submitting"
                ? "Screening your answers"
                : draft.trim()
                  ? isLastField
                    ? "Press Enter to finish"
                    : "Press Enter to continue"
                  : ""}
            </p>
          </>
        ) : null}

        {phase === "done" && result ? (
          <>
            <h1 className="mt-6 text-3xl font-semibold tracking-tight">
              {result.status === "approved" ? "You are approved." : "Thank you."}
            </h1>
            <p className="mt-5 max-w-[46ch] text-[15px] leading-relaxed text-text-dim">
              {closingLine(result)}
            </p>
            <dl className="mt-9 w-full max-w-[420px] space-y-3 text-left">
              {Object.entries(answers).map(([k, v]) => (
                <div
                  key={k}
                  className="flex justify-between gap-4 border-b border-glass-border-soft pb-2.5"
                >
                  <dt className="text-[13px] text-text-faint">{k.replace(/_/g, " ")}</dt>
                  <dd className="text-[13.5px]">{v}</dd>
                </div>
              ))}
            </dl>
            <Link
              href="/console"
              className="mt-9 rounded-[var(--r-pill)] border border-glass-border px-6 py-3 text-[14px] font-medium text-text transition-all hover:border-white/25"
            >
              See it in the reviewer console
            </Link>
          </>
        ) : null}
      </main>
    </div>
  );
}

function closingLine(c: Case): string {
  if (c.status === "approved") {
    return "Your application passed our checks and your account is open.";
  }
  if (c.status === "awaiting_review") {
    return "Your application needs a short review by a compliance officer. We will be in touch.";
  }
  if (c.status === "rejected") {
    return "We are not able to open an account at this time.";
  }
  return "Your application has been recorded.";
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-[100dvh] place-items-center px-6">
      <div className="flex flex-col items-center text-center">{children}</div>
    </div>
  );
}
