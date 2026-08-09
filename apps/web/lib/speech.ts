/**
 * Browser Web Speech API wrappers.
 *
 * IMPORTANT, and it must not be lost: in Chrome, SpeechRecognition streams
 * audio to Google's servers for transcription. For a KYC interview that is real
 * PII leaving the machine. This layer exists to prove the conversational flow
 * today, with zero downloads. The Pipecat voice layer replaces it with local
 * faster-whisper so nothing leaves the process. See
 * docs/research/2026-08-07-pipecat-integration.md.
 */

type SpeechRecognitionAlternative = { transcript: string; confidence: number };
type SpeechRecognitionResult = {
  isFinal: boolean;
  0: SpeechRecognitionAlternative;
  length: number;
};
type SpeechRecognitionEventLike = {
  resultIndex: number;
  results: { length: number; [i: number]: SpeechRecognitionResult };
};

export type Recognizer = {
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((e: SpeechRecognitionEventLike) => void) | null;
  onend: (() => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  continuous: boolean;
  interimResults: boolean;
  lang: string;
};

type SpeechWindow = Window & {
  SpeechRecognition?: new () => Recognizer;
  webkitSpeechRecognition?: new () => Recognizer;
};

export function speechSupported(): boolean {
  if (typeof window === "undefined") return false;
  const w = window as SpeechWindow;
  return Boolean(
    (w.SpeechRecognition || w.webkitSpeechRecognition) && window.speechSynthesis,
  );
}

export function createRecognizer(lang = "en-US"): Recognizer | null {
  if (typeof window === "undefined") return null;
  const w = window as SpeechWindow;
  const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
  if (!Ctor) return null;
  const rec = new Ctor();
  rec.continuous = false;
  rec.interimResults = true;
  rec.lang = lang;
  return rec;
}

/** Speak text and resolve when the utterance finishes or fails. */
export function speak(text: string): Promise<void> {
  return new Promise((resolve) => {
    if (typeof window === "undefined" || !window.speechSynthesis) {
      resolve();
      return;
    }
    window.speechSynthesis.cancel();
    const utter = new SpeechSynthesisUtterance(text);
    utter.rate = 1.02;
    utter.pitch = 1.0;
    const voices = window.speechSynthesis.getVoices();
    const preferred =
      voices.find((v) => /Google UK English Female|Samantha|Aria/i.test(v.name)) ??
      voices.find((v) => v.lang.startsWith("en"));
    if (preferred) utter.voice = preferred;
    utter.onend = () => resolve();
    utter.onerror = () => resolve();
    window.speechSynthesis.speak(utter);
  });
}

/**
 * Map a spoken answer onto the value the pack schema expects.
 * Free-text fields pass through; constrained fields are keyword matched, and
 * return null when nothing matches so the caller can re-ask rather than guess.
 */
const MONTHS: Record<string, string> = {
  january: "01", february: "02", march: "03", april: "04",
  may: "05", june: "06", july: "07", august: "08",
  september: "09", october: "10", november: "11", december: "12",
};

const NATIONALITY: Record<string, string> = {
  india: "IN", indian: "IN", uae: "AE", emirati: "AE", emirates: "AE",
  syria: "SY", syrian: "SY", pakistan: "PK", pakistani: "PK",
  britain: "GB", british: "GB", uk: "GB", america: "US", american: "US",
  usa: "US", egypt: "EG", egyptian: "EG", philippines: "PH", filipino: "PH",
};

export function normalize(field: string, raw: string): string | null {
  const text = raw.trim().toLowerCase();
  if (!text) return null;

  switch (field) {
    case "full_name":
      // Keep the applicant's own capitalisation intent, require two parts.
      return raw.trim().split(/\s+/).length >= 2 ? titleCase(raw.trim()) : null;

    case "dob":
      return parseDob(text);

    case "nationality": {
      for (const [word, code] of Object.entries(NATIONALITY)) {
        if (text.includes(word)) return code;
      }
      const alpha2 = raw.trim().toUpperCase();
      return /^[A-Z]{2}$/.test(alpha2) ? alpha2 : null;
    }

    case "residency_status":
      if (/non.?resident|abroad|outside|overseas/.test(text)) return "non_resident";
      if (/resident|uae|local|here/.test(text)) return "uae_resident";
      return null;

    case "source_of_funds":
      if (/salary|wage|employ|job|work/.test(text)) return "salary";
      if (/business|company|trading company|revenue/.test(text)) return "business_income";
      if (/invest|portfolio|stock|dividend/.test(text)) return "investments";
      if (/inherit|estate|family money/.test(text)) return "inheritance";
      if (/crypto|bitcoin|digital asset/.test(text)) return "crypto_trading";
      if (/other|something else/.test(text)) return "other";
      return null;

    case "product":
      if (/spot/.test(text)) return "spot_trading";
      if (/derivative|futures|option|margin/.test(text)) return "derivatives";
      if (/custody|hold|storage|vault/.test(text)) return "custody";
      return null;

    default:
      return raw.trim();
  }
}

function titleCase(s: string): string {
  return s.replace(/\S+/g, (w) => w[0].toUpperCase() + w.slice(1).toLowerCase());
}

/** Accepts "15 April 1992", "April 15 1992", "1992-04-15", "15/04/1992". */
function parseDob(text: string): string | null {
  const iso = text.match(/(\d{4})[-/](\d{1,2})[-/](\d{1,2})/);
  if (iso) return `${iso[1]}-${pad(iso[2])}-${pad(iso[3])}`;

  const dmy = text.match(/(\d{1,2})[-/](\d{1,2})[-/](\d{4})/);
  if (dmy) return `${dmy[3]}-${pad(dmy[2])}-${pad(dmy[1])}`;

  const monthName = Object.keys(MONTHS).find((m) => text.includes(m));
  if (monthName) {
    const year = text.match(/\b(19|20)\d{2}\b/);
    const day = text.match(/\b(\d{1,2})(?:st|nd|rd|th)?\b/);
    if (year && day) return `${year[0]}-${MONTHS[monthName]}-${pad(day[1])}`;
  }
  return null;
}

function pad(n: string): string {
  return n.padStart(2, "0");
}
