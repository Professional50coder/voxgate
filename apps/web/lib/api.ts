/**
 * Same-origin by default. `/api/*` is rewritten to the real backend by
 * next.config.ts, using a server-side env var read at start rather than baked
 * in at build time.
 *
 * Do not reintroduce a NEXT_PUBLIC_ default pointing at localhost. That value
 * is inlined into the client bundle at build time, so a deploy that sets it
 * afterwards still ships a bundle telling every visitor's browser to call
 * their own machine.
 *
 * The escape hatch exists only for the case where the frontend is served by
 * something that cannot rewrite (a static CDN, say). Setting it reintroduces
 * cross-origin requests, so the backend's VOXGATE_CORS_ORIGINS must then list
 * this frontend's origin.
 */
export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api";

export type Pack = {
  pack_id: string;
  display_name: string;
  gate_role: string;
  fields: string[];
  /** The pack's own question phrasings, keyed by field. Source of truth for /apply. */
  reask_hints?: Record<string, string>;
};

export type CaseInterrupt = {
  type: "interview" | "review";
  reask_fields?: string[];
  reask_hints?: Record<string, string>;
  fields_so_far?: Record<string, unknown>;
  attempt?: number;
  max_attempts?: number;
};

export type AuditEntry = {
  seq: number;
  node: string;
  status_before: string | null;
  status_after: string | null;
  summary: string;
  duration_ms: number;
  actor?: string;
};

export type Case = {
  case_id: string;
  pack_id: string;
  status: string;
  seq: number;
  fields: Record<string, unknown>;
  score: { probability: number | null; band: string } | null;
  decision: { action: string; by: string; note?: string } | null;
  check_results: { check_name: string; status: string }[];
  audit: AuditEntry[];
  interrupt: CaseInterrupt | null;
  error?: string;
};

export class ApiUnreachable extends Error {
  constructor() {
    super("backend unreachable");
    this.name = "ApiUnreachable";
  }
}

/** Thrown for 401/402. The caller shows the key prompt rather than an error. */
export class NotAuthorized extends Error {
  constructor(readonly status: number) {
    super(status === 401 ? "operator key required" : "operator key rejected");
    this.name = "NotAuthorized";
  }
}

const KEY_STORAGE = "voxgate.operator-key";

/**
 * The operator key, held in localStorage.
 *
 * localStorage and not a cookie, deliberately. A cookie would be attached by
 * the browser to every same-origin request automatically, including ones
 * triggered by another page — which is what CSRF is. This key is only ever
 * added by code that means to, so a cross-site form post carries no
 * credentials and there is nothing for a CSRF token to defend.
 *
 * It is readable by any script on this origin, so it is exactly as strong as
 * the origin itself. That is the right trade for an operator console and would
 * not be for an end-user session.
 */
export function getOperatorKey(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(KEY_STORAGE) ?? "";
}

export function setOperatorKey(key: string): void {
  if (typeof window === "undefined") return;
  const trimmed = key.trim();
  if (trimmed) window.localStorage.setItem(KEY_STORAGE, trimmed);
  else window.localStorage.removeItem(KEY_STORAGE);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // The key is attached to every request rather than only the operator ones.
  // Sending it where it is not needed is harmless — the applicant routes ignore
  // it — and the alternative is a per-endpoint list that drifts out of sync
  // with the server's own list the first time a route changes sides.
  const key = getOperatorKey();
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        ...(key ? { "X-API-Key": key } : {}),
        ...(init?.headers ?? {}),
      },
    });
  } catch {
    throw new ApiUnreachable();
  }
  if (res.status === 401 || res.status === 403) {
    // Distinct from a generic failure: the UI can ask for a key instead of
    // showing "GET /cases failed: 401", which tells an operator nothing.
    throw new NotAuthorized(res.status);
  }
  if (!res.ok) {
    throw new Error(`${init?.method ?? "GET"} ${path} failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const getPacks = () => request<Pack[]>("/packs");
export const listCases = () => request<Case[]>("/cases");
export const getCase = (id: string) => request<Case>(`/cases/${id}`);

export const createCase = (packId: string) =>
  request<Case>("/cases", {
    method: "POST",
    body: JSON.stringify({ pack_id: packId }),
  });

export const submitInterview = (
  id: string,
  fields: Record<string, unknown>,
  confidence: Record<string, number> = {},
) =>
  request<Case>(`/cases/${id}/interview-result`, {
    method: "POST",
    body: JSON.stringify({ fields, confidence }),
  });

export const submitDecision = (id: string, action: string, note = "") =>
  request<Case>(`/cases/${id}/decision`, {
    method: "POST",
    body: JSON.stringify({ action, note }),
  });

/**
 * Draft a pack from a plain-English description. Operator-only.
 *
 * Routed through `request` rather than a bare `fetch`, which is the whole
 * reason this exists: the composer called `fetch` directly and therefore sent
 * no operator key, so it broke the moment /packs/draft was protected. Anything
 * that talks to the API goes through one function, so a change to how requests
 * are authenticated cannot miss a call site.
 */
export const draftPack = (description: string) =>
  request<PackDraft>("/packs/draft", {
    method: "POST",
    body: JSON.stringify({ description }),
  });

export const publishPack = (spec: unknown, overwrite = true) =>
  request<{ pack_id: string; display_name: string }>("/packs/publish", {
    method: "POST",
    body: JSON.stringify({ spec, overwrite }),
  });

export type PackDraft = {
  pack_id: string;
  display_name: string;
  gate_role: string;
  persona: string;
  gate_reason: string;
  fields: { name: string; type: string; question: string; values?: Record<string, number> }[];
  checks: { name: string; field: string }[];
  warnings: string[];
  spec: unknown;
};

/**
 * Seeds for "Surprise me".
 *
 * Written out rather than generated, and that is the point. The button's job is
 * to show someone who does not yet know what to type that the system handles
 * more than banking, so the value is in the SPREAD — regulated and unregulated,
 * high stakes and low, consumer and trade. A random-word generator would
 * produce novelty without range, and an LLM asked to invent the prompt as well
 * as the pack would mostly reinvent the same two or three industries.
 *
 * Each one is a real description a real operator might write: what the business
 * does, what the agent should find out, and what should stop for a human.
 */
export const SURPRISE_SEEDS: string[] = [
  "We run a mobile veterinary clinic. Before a home visit we need the pet's species, age, what is wrong, whether it is an emergency, and whether the animal has bitten anyone before. Anything the owner describes as bleeding or collapsed should go straight to the on-call vet.",
  "We are a commercial kitchen equipment leasing company. Screen applicants for what they are leasing, how long the restaurant has traded, their monthly covers, and whether they have defaulted on a lease before. Anything under a year trading needs a credit manager.",
  "We are a youth sports academy taking new enrolments. Collect the child's age group, the parent's contact, any medical conditions, prior injuries, and consent for photography. Any disclosed head injury history must reach the head coach.",
  "We run a boutique freight forwarding firm. Before quoting we need the origin and destination, commodity type, whether it is hazardous, declared value, and required delivery window. Hazardous or high-value goods route to a compliance officer.",
  "We are a film production company hiring background extras. Screen for availability, whether they have a work permit, guild membership, wardrobe sizes, and any speaking-role experience. Anyone without the right to work stops for the production coordinator.",
  "We manage short-term holiday rentals. Screen guests for party size, purpose of stay, whether they are local to the area, and pet plans. A local booking for a one-night stay should be flagged to the property manager.",
  "We are a specialty coffee roaster onboarding wholesale accounts. Find out their monthly volume, brewing method, whether they have an existing supplier, and payment terms they expect. Anything over a tonne a month goes to the head of wholesale.",
  "We run a community solar installer. Qualify homeowners on roof age, orientation, current electricity spend, whether they own the property, and planning restrictions. Listed buildings or conservation areas need a surveyor before quoting.",
  "We are an equipment hire firm for construction sites. Collect the site address, which machinery, the operator's certification, insurance cover, and hire duration. An uncertified operator must never be auto-approved.",
  "We are a private tutoring agency matching tutors to families. Screen for subject, exam board, the student's year group, previous tutoring, and safeguarding checks on the tutor. Any missing background check stops for the safeguarding lead.",
  "We are an artisan bakery taking wedding cake commissions. Find out the date, guest count, dietary requirements, delivery venue, and budget range. Any severe allergy disclosure must reach the head baker directly.",
  "We run a marine survey business. Before booking we need the vessel type, length, year built, the survey's purpose, and mooring location. Anything pre-1980 or with a reported hull breach needs the senior surveyor.",
];
