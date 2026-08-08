/* ============================================================================
   dashboard.js — VoxGate Compliance Ops Console client
   ----------------------------------------------------------------------------
   Vanilla ES2020+ single-file dashboard. No frameworks, no build step, no
   external dependencies — raw fetch + DOM only. Driven against the FastAPI
   service (`/packs`, `/cases`, `/cases/{id}/events` WS) served at the page
   origin. It owns the board, KPI tiles, analytics charts, monitoring strip,
   the case detail drawer (overview / interview / reviewer-gate / pipeline /
   events tabs), live WebSocket subscription with reconnect, an events/min
   ring buffer + sparkline, toasts, and a graceful 2D-canvas voice orb.
   ========================================================================== */

"use strict";

const $ = (id) => document.getElementById(id);
const NS_SVG = "http://www.w3.org/2000/svg";

/* ---------------------------------------------------------------------------
 * DOM / util helpers
 * ------------------------------------------------------------------------- */

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function fmtP(p) {
  if (typeof p !== "number" || !isFinite(p)) return "--";
  return `${Math.round(p * 100)}%`;
}

function fmtC(c) {
  if (typeof c !== "number" || !isFinite(c)) return "--";
  return `${c >= 0 ? "+" : ""}${c.toFixed(2)}`;
}

function cap(s) { return String(s == null ? "" : s).charAt(0).toUpperCase() + String(s == null ? "" : s).slice(1); }
function statusLabel(s) { return String(s || "").replace(/_/g, " "); }
function countBy(arr, fn) { return arr.filter(fn).length; }
function timeLabel(t) { try { return new Date(t).toLocaleTimeString(); } catch (_) { return ""; } }

function toast(msg, type) {
  const region = $("toast-region");
  if (!region) return;
  const t = el("div", `toast ${type || "info"}`);
  t.appendChild(document.createTextNode(esc(msg)));
  region.appendChild(t);
  setTimeout(() => {
    t.classList.add("leaving");
    setTimeout(() => t.remove(), 280);
  }, 4000);
}

async function api(path, opts = {}) {
  const headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
  let res;
  try {
    res = await fetch(path, Object.assign({}, opts, { headers }));
  } catch (err) {
    const e = new Error("network error: " + ((err && err.message) || "unreachable"));
    e.status = 0;
    throw e;
  }
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const j = await res.json();
      if (j && j.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch (_) { /* non-JSON */ }
    const e = new Error(detail);
    e.status = res.status;
    throw e;
  }
  if (res.status === 204) return null;
  return res.json();
}

function setBtnEnabled(id, on) { const b = $(id); if (b) b.disabled = !on; }

/* ---------------------------------------------------------------------------
 * Pipecat protobuf wire codec
 * ---------------------------------------------------------------------------
 * Dependency-free encoder/decoder for pipecat's WebSocket binary protocol —
 * mirrors `src/voxgate/service/voice/protobuf.py`, which is conformance-tested
 * against pipecat's own ProtobufFrameSerializer (see tests/test_pipecat_protobuf.py).
 *
 * Schema (from `pipecat.frames.protobufs.frames_pb2`):
 *   Frame (oneof): text=1, audio=2, transcription=3, message=4, interruption=5
 *   AudioRawFrame: audio=3 (bytes, int16 LE), sample_rate=4 (u32), num_channels=5 (u32)
 *   TextFrame:     text=3 (string)
 * Only the `varint` (0) and `length-delimited` (2) wire types are used. */
const PB = (() => {
  const W_VARINT = 0, W_LEN = 2;

  function vbytes(n) {
    const out = [];
    n = n < 0 ? 0 : Math.floor(n);
    do {
      let b = n & 0x7f;
      n = Math.floor(n / 128);
      if (n > 0) b |= 0x80;
      out.push(b);
    } while (n > 0);
    return out;
  }

  function tag(field, wire) { return vbytes((field << 3) | wire); }

  function u8(parts) {
    let total = 0;
    for (const p of parts) total += typeof p === "number" ? 1 : p.length;
    const out = new Uint8Array(total);
    let o = 0;
    for (const p of parts) {
      if (typeof p === "number") { out[o++] = p; }
      else { out.set(p, o); o += p.length; }
    }
    return out;
  }

  function bytesOf(typed) { return new Uint8Array(typed.buffer || typed, typed.byteOffset || 0, typed.byteLength); }

  function encodeAudio(data, sampleRate, numChannels) {
    const pcm = bytesOf(data);
    const inner = u8([
      u8([0x1a, ...vbytes(pcm.length)]), pcm,
      u8([0x20, ...vbytes(sampleRate)]),
      u8([0x28, ...vbytes(numChannels)]),
    ]);
    return u8([u8([0x12, ...vbytes(inner.length)]), inner]);
  }

  function encodeText(text) {
    const data = new TextEncoder().encode(String(text == null ? "" : text));
    const inner = u8([u8([0x1a, ...vbytes(data.length)]), data]);
    return u8([u8([0x0a, ...vbytes(inner.length)]), inner]);
  }

  function decode(bytes) {
    const data = bytesOf(bytes);
    const out = {};
    let pos = 0;
    function rv() {
      let r = 0, shift = 0;
      while (pos < data.length) {
        const b = data[pos++];
        r |= (b & 0x7f) << shift;
        if (!(b & 0x80)) return r;
        shift += 7;
      }
      return r;
    }
    function stringAt(seg) { return new TextDecoder().decode(seg); }

    function parseInner(seg, want) {
      // Parse a nested message into {field: value}; varint or bytes.
      const m = {};
      let p = 0;
      function irv() {
        let r = 0, s = 0;
        while (p < seg.length) {
          const b = seg[p++];
          r |= (b & 0x7f) << s;
          if (!(b & 0x80)) return r;
          s += 7;
        }
        return r;
      }
      while (p < seg.length) {
        const t = irv();
        const f = t >> 3, w = t & 7;
        if (w === W_VARINT) m[f] = irv();
        else if (w === W_LEN) {
          const len = irv();
          m[f] = seg.slice(p, p + len);
          p += len;
        } else break;
      }
      return m;
    }

    while (pos < data.length) {
      const t = rv();
      const field = t >> 3, wire = t & 7;
      if (wire !== W_LEN) { if (wire === W_VARINT) rv(); continue; }
      const len = rv();
      const seg = data.slice(pos, pos + len);
      pos += len;
      if (field === 1) {        // text -> TextFrame.text = 3
        const m = parseInner(seg);
        out.text = m[3] ? stringAt(m[3]) : "";
      } else if (field === 2) { // audio -> AudioRawFrame
        const m = parseInner(seg);
        out.audio = {
          data: m[3] ? new Uint8Array(m[3]) : new Uint8Array(0),
          sampleRate: m[4] || 0,
          numChannels: m[5] || 1,
        };
      } else if (field === 3) { // transcription -> text = 3
        const m = parseInner(seg);
        out.transcription = m[3] ? stringAt(m[3]) : "";
      } else if (field === 4) { // message -> data = 1
        const m = parseInner(seg);
        out.message = m[1] ? stringAt(m[1]) : "";
      } else if (field === 5) {
        out.interruption = true;
      }
    }
    return out;
  }

  return { encodeAudio, encodeText, decode };
})();

/* ---------------------------------------------------------------------------
 * Application state
 * ------------------------------------------------------------------------- */
const state = {
  packById: {},
  cases: [],
  openId: null,
  openCase: null,
  activeTab: "overview",
  ws: null,
  wsBackoff: 1000,
  showAttention: false,
  evts: [],
  captions: [],
  liveFields: {},
  conf: {},
  lastKpi: null,
  reconnectT: null,
  currentEventFeed: null,
};

/* ------------------------ Voice interview session ------------------------- */
/* Browser voice agent: asks the pack's questions aloud (speechSynthesis),
 * listens for spoken answers (Web Speech API SpeechRecognition), interprets
 * each answer into a canonical field value via the server's /answer endpoint
 * (Groq brain; raw-transcript fallback), and submits the accumulated fields
 * to /interview-result (the LangGraph interview node). All transcript bubbles
 * are published to the case's caption stream so the orb + drawer animate. */
const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;

const voice = {
  active: false,
  busy: false,          // mid commit/submit — suppresses recognition restart
  done: false,
  mic: null,
  recog: null,
  speaking: false,
  listening: false,
  queue: [],            // [{field, hint}] remaining questions
  cur: null,            // {field, hint} being asked right now
  fields: {},           // canonical values collected so far
  confidence: {},
  attempts: {},         // per-field failed-interpretation count (clarification escalation)
  transcript: "",       // live (interim) recognized text
  idleT: null,          // silence-reprompt timer
  typedMode: false,     // speech recognition unavailable -> type answers instead
  lastCaptured: null,   // {field, value} just captured, for the agent to acknowledge
  voiceName: "",        // preferred TTS voice (persisted in localStorage)
  scenarioName: "kyc-interview", // Pipecat persona (see /voice/scenarios)
};

let ttsVoices = [];
function loadVoices() {
  if ("speechSynthesis" in window) {
    ttsVoices = speechSynthesis.getVoices() || [];
    refreshVoicePicker();
  }
}
if ("speechSynthesis" in window) {
  loadVoices();
  speechSynthesis.onvoiceschanged = loadVoices;
}

/* Highest-quality available English voice: prefer online neural (Aria/Jenny/
 * Guy/etc.), then Zira/David desktop, then Google US English, then any en. */
function pickBestVoice() {
  const en = ttsVoices.filter((v) => /^en/i.test(v.lang || ""));
  if (!en.length) return null;
  const neural = en.find((v) => /aria|jenny|guy|ana|michelle|natural|online|en-gb-|sonia|libby/i.test(v.name || ""));
  if (neural) return neural;
  const zira = en.find((v) => /zira|david/i.test(v.name || ""));
  if (zira) return zira;
  return en[0];
}

function currentVoice() {
  if (voice.voiceName) {
    const saved = ttsVoices.find((v) => v.name === voice.voiceName);
    if (saved) return saved;
  }
  return pickBestVoice();
}

function voiceSelect(name) {
  voice.voiceName = name || "";
  try { localStorage.setItem("voxgate_voice", voice.voiceName); } catch (_) {}
}

function refreshVoicePicker() {
  const sel = $("voice-picker");
  if (!sel) return;
  const current = voice.voiceName || (pickBestVoice() || {}).name || "";
  sel.innerHTML = "";
  const en = ttsVoices.filter((v) => /^en/i.test(v.lang || ""));
  if (!en.length) {
    const o = document.createElement("option");
    o.value = "";
    o.textContent = "No voices loaded";
    sel.appendChild(o);
    return;
  }
  for (const v of en) {
    const o = document.createElement("option");
    o.value = v.name;
    o.textContent = `${v.name}${/natural|online|neural/i.test(v.name) ? " ★" : ""}`;
    sel.appendChild(o);
  }
  sel.value = current;
}

function ttsSupported() { return "speechSynthesis" in window; }
function sttSupported() {
  return !!SpeechRec && !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
}

function publishCaption(role, text) {
  api(`/cases/${state.openId}/captions`, {
    method: "POST",
    body: JSON.stringify({ role, text }),
  }).catch(() => {});
}

/* ----------------------- Pipecat realtime voice session ------------------- */
/* Full-duplex Pipecat client: streams the mic (16k mono PCM, wrapped in a
 * `Frame.audio` protobuf) up the case's `/voice` WebSocket, and plays the
 * agent's returned `Frame.audio` back on the shared AudioContext. Captions and
 * orb state come from the server's caption observer over the `/events` bus
 * (agent LLM -> TTS lines and user STT transcriptions).
 *
 * Falling back to the classic browser Web-Speech flow (typed boxes / forward
 * speech synthesis) happens in voiceStart() when Web Audio or the WS is
 * unavailable. */
const pc = {
  ws: null,
  ctx: null,
  stream: null,
  worklet: null,
  sourceNode: null,
  running: false,
  speaking: false,
  speakT: null,
  playback: [],
};

function pcSupported() {
  return !!(window.AudioContext || window.webkitAudioContext)
    && !!(window.AudioWorkletNode)
    && !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
}

function pcResetStatus() {
  voice.listening = pc.ws && pc.ws.readyState === WebSocket.OPEN;
  voice.speaking = pc.speaking;
  pcSync();
  syncVoiceUI();
}

function pcSync() {
  const status = $("voice-status");
  if (!status) return;
  if (pc.speaking) status.textContent = "VoxGate is speaking…";
  else if (voice.active && pc.ws && pc.ws.readyState === WebSocket.OPEN) status.textContent = "Listening — speak freely…";
}

function pcVoiceUrl() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const scenario = (voice.scenarioName || "kyc-interview");
  return `${proto}://${location.host}/cases/${state.openId}/voice?scenario=${encodeURIComponent(scenario)}`;
}

function pcStopPlayback() {
  for (const s of pc.playback) { try { s.stop(); s.disconnect(); } catch (_) {} }
  pc.playback = [];
  if (pc.speakT) { clearTimeout(pc.speakT); pc.speakT = null; }
  pc.speaking = false;
  pcSync();
}

function pcPlay(frame) {
  if (!pc.ctx || !frame || !frame.data || !frame.data.length) return;
  const numChannels = frame.numChannels || 1;
  const frames = Math.floor(frame.data.length / 2);
  if (!frames) return;
  const sampleRate = frame.sampleRate || pc.ctx.sampleRate;
  const buffer = pc.ctx.createBuffer(numChannels, frames, sampleRate);
  const pcm = new Int16Array(frame.data.buffer, frame.data.byteOffset || 0, frames);
  for (let c = 0; c < numChannels; c++) {
    const ch = buffer.getChannelData(c);
    for (let i = 0; i < frames; i++) {
      const v = pcm[i];
      ch[i] = v < 0 ? v / 0x8000 : v / 0x7fff;
    }
  }
  const src = pc.ctx.createBufferSource();
  src.buffer = buffer;
  src.connect(pc.ctx.destination);
  src.onended = () => {
    const i = pc.playback.indexOf(src);
    if (i >= 0) pc.playback.splice(i, 1);
    if (!pc.playback.length && !pc.speakT) pcEndSpeaking();
  };
  pc.playback.push(src);
  src.start();
  pc.speaking = true;
  pcArmSpeakingEnd(Math.round((frames / sampleRate) * 1000) + 200);
  pcSync();
  syncVoiceUI();
}

function pcArmSpeakingEnd(ms) {
  if (pc.speakT) clearTimeout(pc.speakT);
  pc.speakT = setTimeout(() => {
    if (!pc.playback.length) { pc.speaking = false; pcSync(); syncVoiceUI(); }
    pc.speakT = null;
  }, ms);
}

function pcEndSpeaking() {
  if (pc.speakT) { clearTimeout(pc.speakT); pc.speakT = null; }
}

function pcHandleFrame(frame) {
  if (!frame) return;
  if (frame.interruption) { pcStopPlayback(); return; }
  if (frame.audio) { pcPlay(frame.audio); return; }
  // message (RTVI/transport) and text branches are unused by the raw client.
}

function pcOnMessage(ev) {
  const data = ev.data;
  if (typeof data === "string") return;
  if (!(data instanceof ArrayBuffer)) return;
  let frame;
  try { frame = PB.decode(new Uint8Array(data)); } catch (_) { return; }
  pcHandleFrame(frame);
}

function pcOpen() {
  return new Promise((resolve, reject) => {
    if (pc.ws && (pc.ws.readyState === WebSocket.OPEN || pc.ws.readyState === WebSocket.CONNECTING)) return resolve(pc.ws);
    let ws;
    try { ws = new WebSocket(pcVoiceUrl()); } catch (err) { return reject(err); }
    ws.binaryType = "arraybuffer";
    pc.ws = ws;
    ws.onopen = () => resolve(ws);
    ws.onerror = () => reject(new Error("voice socket error"));
    ws.onmessage = pcOnMessage;
    ws.onclose = () => {
      if (pc.ws === ws) pc.ws = null;
      pcDisconnected();
    };
  });
}

async function pcStart() {
  const caseId = state.openId;
  await pcOpen(caseId);
  await pcInitAudio();
  pc.running = true;
  voice.active = true;
  voice.done = false;
  voice.busy = false;
  pcResetStatus();
  toast("Live voice session (Pipecat) started.", "success");
}

async function pcInitAudio() {
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!pc.ctx) pc.ctx = new AC();
  if (pc.ctx.state === "suspended") { try { await pc.ctx.resume(); } catch (err) {} }
  if (!pc.worklet) {
    await pc.ctx.audioWorklet.addModule("/static/voice-worklet.js");
    const node = new AudioWorkletNode(pc.ctx, "voice-resampler");
    pc.worklet = node;
    node.port.onmessage = (e) => {
      if (voice.active && pc.ws && pc.ws.readyState === WebSocket.OPEN) {
        try { pc.ws.send(PB.encodeAudio(e.data, 16000, 1)); } catch (_) {}
      }
    };
  }
  if (!pc.sourceNode || !pc.stream) {
    pc.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    pc.sourceNode = pc.ctx.createMediaStreamSource(pc.stream);
  }
  pc.sourceNode.connect(pc.worklet);
  voice.listening = true;
  pcSync();
  syncVoiceUI();
}

function pcSendText(text) {
  if (!pc.ws || pc.ws.readyState !== WebSocket.OPEN) return false;
  try { pc.ws.send(PB.encodeText(text)); return true; } catch (_) { return false; }
}

function pcDisconnected() {
  const wasRunning = pc.running;
  pc.ws = null;
  pcStopPlayback();
  pcEndSpeaking();
  if (wasRunning && voice.active) voiceEnd(false);
}

async function pcTeardown() {
  pc.running = false;
  if (pc.ws) { try { pc.ws.close(1000); } catch (_) {} pc.ws = null; }
  if (pc.stream) { pc.stream.getTracks().forEach((t) => t.stop()); pc.stream = null; }
  if (pc.sourceNode) { try { pc.sourceNode.disconnect(); } catch (_) {} pc.sourceNode = null; }
  if (pc.worklet) { try { pc.worklet.disconnect(); } catch (_) {} pc.worklet = null; }
  pc.worklet = null;
  if (pc.ctx) { try { pc.ctx.close(); } catch (_) {} pc.ctx = null; }
  pc.speaking = false;
  pcEndSpeaking();
}

/* ----------------------------- Connection -------------------------------- */

function setConn(cls, label) {
  const b = $("conn-badge");
  if (!b) return;
  b.classList.remove("live", "connecting", "down");
  if (cls) b.classList.add(cls);
  const t = b.querySelector(".conn-label");
  if (t) t.textContent = label;
}

/* ------------------------------ Packs + boot ----------------------------- */
async function loadPacks() {
  const packs = await api("/packs");
  state.packById = {};
  for (const p of packs) state.packById[p.pack_id] = p;
  const sel = $("pack-select");
  if (sel) {
    sel.innerHTML = "";
    for (const p of packs) {
      const o = el("option", null, p.display_name);
      o.value = p.pack_id;
      sel.appendChild(o);
    }
  }
  const on = packs.length > 0;
  setBtnEnabled("btn-new-case", on);
  setBtnEnabled("btn-new-case-empty", on);
}

function packName(pid) { const p = state.packById[pid]; return p ? p.display_name : (pid || "unknown"); }
function packGate(pid) { const p = state.packById[pid]; return p ? p.gate_role : "—"; }
function packFields(pid) { const p = state.packById[pid]; return p ? p.fields : []; }

async function boot() {
  state.captions = [];
  setConn("connecting", "Connecting");
  try {
    await loadPacks();
  } catch (err) {
    setConn("down", "Down");
    toast("Failed to load packs: " + err.message, "error");
  }
  try {
    await refreshAll();
    setConn("live", "Live");
  } catch (err) {
    setConn("down", "Down");
    toast("Failed to load board: " + err.message, "error");
  } finally {
    schedulePoll();
  }
  console.info("VoxGate dashboard initialized");
}

/* ----------------------------- Refresh ----------------------------------- */
async function refreshAll() {
  const t0 = performance.now();
  let cases;
  try {
    cases = await api("/cases");
  } catch (err) {
    setConn("down", "Down");
    throw err;
  }
  const ms = $("mon-poll-latency");
  if (ms) ms.textContent = Math.round(performance.now() - t0) + " ms";
  if (!Array.isArray(cases)) cases = state.cases;
  state.cases = cases.slice().sort((a, b) => (b.seq || 0) - (a.seq || 0));

  renderBoard();
  renderKpis();
  renderAnalytics();
  renderAttention();
  updateMonitorOpen();

  if (state.openId) {
    const fresh = state.cases.find((x) => x.case_id === state.openId);
    if (fresh && caseSignature(fresh) !== caseSignature(state.openCase)) {
      state.openCase = fresh;
      renderDrawer();
    }
  }
}

function caseSignature(c) {
  const s = c && c.score;
  return [
    c ? c.status : "", c ? c.seq : 0,
    s && s.probability != null ? s.probability : null,
    (c && c.decision && c.decision.action) || "",
  ].join("|");
}

function schedulePoll() {
  setTimeout(async () => {
    try { await refreshAll(); } catch (_) {}
    schedulePoll();
  }, 5000);
}

/* ----------------------------- Board ------------------------------------- */
function renderBoard() {
  const list = $("case-list");
  if (!list) return;
  [...list.querySelectorAll(".case-row")].forEach((r) => r.remove());
  const empty = $("board-empty");
  if (!state.cases.length) {
    if (empty) empty.classList.remove("hidden");
    setBtnEnabled("btn-new-case-empty", Object.keys(state.packById).length > 0);
    const meta = $("board-meta");
    if (meta) meta.textContent = "0 cases";
    return;
  }
  if (empty) empty.classList.add("hidden");
  setBtnEnabled("btn-new-case-empty", true);
  for (const c of state.cases) list.appendChild(renderCaseRow(c));
  const meta = $("board-meta");
  if (meta) meta.textContent = `${state.cases.length} cases · ${packName(state.cases[0].pack_id)}`;
}

function renderCaseRow(c) {
  const row = el("div", "case-row");
  row.dataset.id = c.case_id;
  if (state.openId === c.case_id) row.classList.add("selected");

  row.appendChild(el("span", "case-id", String(c.case_id || "").slice(0, 8)));

  const main = el("div", "case-main");
  main.appendChild(el("div", "case-pack", packName(c.pack_id)));
  const sub = el("div", "case-sub", `${packGate(c.pack_id)} · seq ${c.seq || 0}`);
  if (c.status === "needs_attention" && c.error) {
    const m = el("span", "case-sub");
    m.textContent = " · " + c.error;
    sub.appendChild(m);
  }
  main.appendChild(sub);

  const score = el("div", "case-score");
  if (c.score && c.score.probability != null) {
    const num = document.createElement("span");
    num.textContent = c.score.probability.toFixed(2);
    score.appendChild(num);
    if (c.score.band) {
      score.appendChild(document.createTextNode(" · "));
      score.appendChild(el("span", `band-${c.score.band}`, c.score.band));
    }
  } else {
    score.textContent = "—";
  }

  const chip = el("span", `chip status-${c.status}`, statusLabel(c.status));
  row.append(main, score, chip);
  row.addEventListener("click", () => openCase(c.case_id));
  return row;
}

function flashRow(id) {
  const row = document.querySelector(`.case-row[data-id="${CSS.escape(id)}"]`);
  if (row) { row.classList.add("flash"); setTimeout(() => row.classList.remove("flash"), 950); }
}

/* ------------------------------ KPI -------------------------------------- */
const KPI_TILES = [
  { key: "total", label: "Total cases" },
  { key: "await", label: "Awaiting review" },
  { key: "attention", label: "Needs attention" },
  { key: "approval", label: "Approval rate" },
];

function computeKpis() {
  const c = state.cases;
  const total = c.length;
  const awaitRev = c.filter((x) => x.status === "awaiting_review").length;
  const attention = c.filter((x) => x.status === "needs_attention").length;
  const approved = c.filter((x) => (x.decision && x.decision.action) === "approve" || x.status === "approved").length;
  const rejected = c.filter((x) => (x.decision && x.decision.action) === "reject" || x.status === "rejected").length;
  const approval = (approved + rejected) ? Math.round((approved / (approved + rejected)) * 100) + "%" : "—";
  return { total: String(total), await: String(awaitRev), attention: String(attention), approval };
}

function renderKpis() {
  const row = $("kpi-row");
  if (!row) return;
  const k = computeKpis();
  const changed = state.lastKpi ? Object.keys(k).find((key) => k[key] !== state.lastKpi[key]) : null;
  [...row.querySelectorAll(".kpi-tile")].forEach((x) => x.remove());
  for (const meta of KPI_TILES) {
    const tile = el("div", "kpi-tile");
    tile.appendChild(el("span", "kpi-label", meta.label));
    const value = el("span", "kpi-value", k[meta.key]);
    if (changed === meta.key) {
      tile.classList.add("kpi-live");
      value.classList.add("updated");
      setTimeout(() => { value.classList.remove("updated"); tile.classList.remove("kpi-live"); }, 600);
    }
    tile.appendChild(value);
    row.appendChild(tile);
  }
  state.lastKpi = k;
}

/* --------------------------- Analytics ---------------------------------- */
function renderAnalytics() {
  renderRiskband();
  renderFunnel();
  renderFeatures();
  renderChecks();
}

function renderRiskband() {
  const host = $("chart-riskband");
  if (!host) return;
  host.innerHTML = "";
  const scored = state.cases.filter((c) => c.score && c.score.band);
  if (!scored.length) { host.appendChild(el("div", "chart-empty", "No scored cases yet.")); return; }
  const buckets = { low: 0, medium: 0, high: 0 };
  scored.forEach((c) => { if (buckets[c.score.band] != null) buckets[c.score.band]++; });
  const total = Math.max(1, scored.length);

  const bar = el("div", "dist-bar");
  for (const band of ["low", "medium", "high"]) {
    const seg = el("div", `dist-seg ${band}`);
    seg.style.width = ((buckets[band] / total) * 100).toFixed(1) + "%";
    bar.appendChild(seg);
  }
  host.appendChild(bar);

  const legend = el("div", "dist-legend");
  for (const band of ["low", "medium", "high"]) {
    const s = el("div", band);
    const dot = el("i");
    s.appendChild(dot);
    s.appendChild(document.createTextNode(`${cap(band)} ${buckets[band]}`));
    legend.appendChild(s);
  }
  host.appendChild(legend);
}

function renderFunnel() {
  const host = $("chart-funnel");
  if (!host) return;
  host.innerHTML = "";
  if (!state.cases.length) { host.appendChild(el("div", "chart-empty", "No cases yet.")); return; }
  const order = ["awaiting_interview", "processing", "awaiting_review", "approved", "rejected", "needs_attention"];
  const counts = {};
  order.forEach((s) => counts[s] = 0);
  state.cases.forEach((c) => { if (counts[c.status] != null) counts[c.status]++; });
  const max = Math.max(1, ...Object.values(counts));
  const funnel = el("div", "funnel");
  for (const s of order) {
    const r = el("div", "funnel-row");
    r.appendChild(el("div", "funnel-label", statusLabel(s)));
    const track = el("div", "funnel-track");
    const fill = el("div", "funnel-fill");
    fill.style.width = ((counts[s] / max) * 100).toFixed(1) + "%";
    track.appendChild(fill);
    r.appendChild(track);
    r.appendChild(el("div", "funnel-count", String(counts[s])));
    funnel.appendChild(r);
  }
  host.appendChild(funnel);
}

function renderFeatures() {
  const host = $("chart-topfeatures");
  if (!host) return;
  host.innerHTML = "";
  const agg = {};
  state.cases.forEach((c) => {
    const contribs = c.score && c.score.contributions;
    if (!contribs) return;
    contribs.forEach((x) => {
      if (!agg[x.feature]) agg[x.feature] = { sum: 0, abs: 0 };
      agg[x.feature].sum += x.contribution;
      agg[x.feature].abs += Math.abs(x.contribution);
    });
  });
  const feats = Object.keys(agg).sort((a, b) => agg[b].abs - agg[a].abs).slice(0, 5);
  if (!feats.length) { host.appendChild(el("div", "chart-empty", "No contribution data yet.")); return; }
  const maxAbs = Math.max(1, ...feats.map((f) => agg[f].abs));
  const list = el("div", "hbar-list");
  for (const f of feats) {
    const row = el("div", "hbar-row");
    row.appendChild(el("div", "hbar-feat", f));
    const track = el("div", "hbar-track");
    track.appendChild(el("div", "hbar-axis"));
    const pos = agg[f].sum >= 0;
    const fill = el("div", `hbar-fill ${pos ? "pos" : "neg"}`);
    const pct = Math.min(48, Number((agg[f].abs / maxAbs * 50).toFixed(1)));
    fill.style.width = pct + "%";
    fill.style.left = (pos ? 50 : 50 - pct) + "%";
    track.appendChild(fill);
    row.appendChild(track);
    row.appendChild(el("div", "hbar-val", fmtC(agg[f].sum)));
    list.appendChild(row);
  }
  host.appendChild(list);
}

function renderChecks() {
  const host = $("chart-checks");
  if (!host) return;
  host.innerHTML = "";
  const byName = {};
  state.cases.forEach((c) => {
    (c.check_results || []).forEach((r) => {
      if (!byName[r.check_name]) byName[r.check_name] = { clear: 0, review: 0, hit: 0 };
      if (byName[r.check_name][r.status] != null) byName[r.check_name][r.status]++;
    });
  });
  const names = Object.keys(byName);
  if (!names.length) { host.appendChild(el("div", "chart-empty", "No check results yet.")); return; }
  for (const name of names) {
    const row = el("div", "check-row");
    row.appendChild(el("div", "check-name", name));
    const stack = el("div", "check-stack");
    const b = byName[name];
    const total = Math.max(1, b.clear + b.review + b.hit);
    for (const status of ["clear", "review", "hit"]) {
      if (!b[status]) continue;
      const seg = el("div", `check-seg ${status}`);
      seg.style.width = ((b[status] / total) * 100).toFixed(1) + "%";
      stack.appendChild(seg);
    }
    row.appendChild(stack);
    host.appendChild(row);
  }
}

/* --------------------------- Attention ---------------------------------- */
function renderAttention() {
  const na = state.cases.find((c) => c.status === "needs_attention");
  const banner = $("attention-banner");
  if (!banner) return;
  if (na && state.showAttention) {
    const t = $("attention-text");
    if (t) t.textContent = `Case ${String(na.case_id).slice(0, 8)} needs attention: ${na.error || "unknown error"}`;
    banner.classList.add("show");
  } else {
    banner.classList.remove("show");
  }
}
function hideAttention() { state.showAttention = false; renderAttention(); }

/* ------------------------------ Drawer ----------------------------------- */
function updateMonitorOpen() {
  const b = $("mon-open-case");
  if (b) b.textContent = state.openId ? String(state.openId).slice(0, 8) : "none";
}

function openCase(id) {
  const c = state.cases.find((x) => x.case_id === id) || state.openCase;
  if (!c) return;
  if (voice.active || voice.busy) voiceEnd(false);
  state.openId = id;
  state.openCase = c;
  state.showAttention = true;
  state.captions = [];
  state.liveFields = {};
  state.activeTab = "overview";
  const drawer = $("case-drawer");
  if (drawer) { drawer.classList.add("open"); drawer.setAttribute("aria-hidden", "false"); }
  const cid = $("drawer-caseid");
  if (cid) cid.textContent = c.case_id;
  setActiveTab("overview");
  updateMonitorOpen();
  renderDrawer();
  watchCase(c.case_id);
  renderBoard();
  renderCaptions();
}

function closeDrawer() {
  unwatch();
  if (voice.active || voice.busy) voiceEnd(false);
  state.openId = null;
  state.openCase = null;
  const drawer = $("case-drawer");
  if (drawer) { drawer.classList.remove("open"); drawer.setAttribute("aria-hidden", "true"); }
  updateMonitorOpen();
  renderBoard();
}

function setActiveTab(tab) {
  const tabs = $("drawer-tabs");
  if (tabs) [...tabs.querySelectorAll(".drawer-tab")].forEach((t) => t.classList.toggle("active", t.dataset.tab === tab));
}

function renderDrawer() {
  const c = state.openCase;
  const body = $("drawer-body");
  if (!c || !body) return;
  renderChips(c);
  body.innerHTML = "";
  switch (state.activeTab) {
    case "overview": renderOverview(body, c); break;
    case "interview": renderInterview(body, c); break;
    case "review": renderReview(body, c); break;
    case "pipeline": renderPipeline(body, c); break;
    case "events": renderEvents(body, c); break;
    default: renderOverview(body, c);
  }
}

function renderChips(c) {
  const host = $("drawer-chips");
  if (!host) return;
  host.innerHTML = "";
  host.appendChild(el("span", `chip chip-sm status-${c.status}`, statusLabel(c.status)));
  host.appendChild(el("span", "chip chip-sm", packName(c.pack_id)));
  host.appendChild(el("span", "chip chip-sm", packGate(c.pack_id)));
  if (c.score && c.score.band) host.appendChild(el("span", `chip chip-sm band-${c.score.band}`, c.score.band));
}

/* ---------------------------- Score waterfall ---------------------------- */
function scoreWaterfall(score) {
  const s = el("div", "drawer-section");
  const wf = el("div", "waterfall");
  if (score && score.probability != null) {
    const prob = el("div", "wf-prob");
    prob.appendChild(el("span", "prob-num", fmtP(score.probability)));
    prob.appendChild(el("span", `chip chip-sm band-${score.band || "medium"}`, score.band || "—"));
    wf.appendChild(prob);
  }
  const contribs = (score && score.contributions ? score.contributions.slice() : [])
    .sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution));
  const maxAbs = Math.max(1, ...contribs.map((x) => Math.abs(x.contribution)));
  if (!contribs.length) wf.appendChild(el("div", "chart-empty", "No contribution data."));
  for (const x of contribs) {
    const row = el("div", "wf-row");
    row.appendChild(el("div", "wf-feat", x.feature));
    const track = el("div", "wf-track");
    track.appendChild(el("div", "wf-axis"));
    const fill = el("div", `wf-fill ${x.contribution >= 0 ? "pos" : "neg"}`);
    fill.style.width = Math.max(2, Number((Math.abs(x.contribution) / maxAbs * 46).toFixed(1))) + "%";
    track.appendChild(fill);
    row.appendChild(track);
    row.appendChild(el("div", "wf-val", fmtC(x.contribution)));
    wf.appendChild(row);
  }
  s.appendChild(wf);
  return s;
}

/* ------------------------------ Overview --------------------------------- */
function renderOverview(body, c) {
  const vp = el("div", "voice-pane");
  const orbWrap = el("div", "orb-wrap");
  vp.appendChild(orbWrap);
  const label = el("div", "orb-state-label", orbLabel(c));
  vp.appendChild(label);
  vp.appendChild(buildVoicePanel(c));
  vp.appendChild(buildCaptions());
  body.appendChild(vp);
  requestAnimationFrame(() => renderOrb(orbWrap));

  const fields = el("div", "drawer-section");
  fields.appendChild(el("h4", null, "Captured fields"));
  const keys = Object.keys(c.fields || {});
  if (!keys.length) fields.appendChild(el("div", "chart-empty", "No fields captured yet."));
  const grid = el("div", "field-grid");
  for (const key of keys) {
    const item = el("div", "field-item");
    item.appendChild(el("span", "fk", key));
    item.appendChild(el("span", "fv", String(c.fields[key] == null ? "" : c.fields[key])));
    grid.appendChild(item);
  }
  fields.appendChild(grid);
  body.appendChild(fields);

  if (c.score) {
    const s = el("div", "drawer-section");
    s.appendChild(el("h4", null, "Risk assessment"));
    s.appendChild(scoreWaterfall(c.score));
    body.appendChild(s);
  }

  if (c.decision) {
    const d = el("div", "drawer-section");
    d.appendChild(el("h4", null, "Decision"));
    d.appendChild(el("p", null, `${statusLabel(c.decision.action)}${c.decision.note ? " — " + c.decision.note : ""} · by ${(c.decision.by || "system")}`));
    body.appendChild(d);
  }

  const a = el("div", "drawer-section");
  a.appendChild(el("h4", null, "Audit"));
  const audit = c.audit || [];
  a.appendChild(el("p", null, `${audit.length} node steps · last: ${audit.length ? audit[audit.length - 1].node : "—"}`));
  body.appendChild(a);
}

function orbLabel(c) {
  if (c.interrupt && c.interrupt.type === "interview") return "Interviewing…";
  if (c.interrupt && c.interrupt.type === "review") return "Awaiting review";
  if (c.status === "processing") return "Processing";
  if (c.status === "approved") return "Approved";
  if (c.status === "rejected") return "Rejected";
  return "Ready";
}

/* ---------------- Premium voice energy visualization -----------------------
   Layered procedural "silk" wave curves + a glowing energy orb, driven by the
   agent state (speaking / listening / thinking / idle). Pure canvas, 2D,
   additive blending — no external deps. */
function renderOrb(host) {
  const W = 320, H = 200;
  const dpr = (window.devicePixelRatio || 1);
  const canvas = el("canvas");
  canvas.id = "orb-canvas";
  canvas.width = W * dpr; canvas.height = H * dpr;
  canvas.style.width = W + "px"; canvas.style.height = H + "px";
  host.innerHTML = "";
  host.appendChild(canvas);
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);

  const sim = { t: 0, amp: 0.08 };

  function targetAmp() {
    if (voice.speaking) return 0.80;
    if (voice.listening) return 0.30;
    if (voice.busy) return 0.22;
    return 0.09;
  }
  function targetSpeed() { return voice.busy ? 0.55 : 1.0; }

  function noise(x, t) {
    return 0.50 * Math.sin(x * 0.9 + t * 0.5)
         + 0.28 * Math.sin(x * 2.3 - t * 0.35 + 1.3)
         + 0.16 * Math.sin(x * 5.1 + t * 1.1 + 2.6)
         + 0.08 * Math.sin(x * 11.0 - t * 0.7 + 0.4);
  }

  const groups = [
    { rgb: "126,235,255", a: 0.16, base: 14, step: 1.1, mul: 1.00, sp: 1.00, ph: 0.0 },
    { rgb: "126,235,255", a: 0.14, base: 27, step: 1.0, mul: 0.90, sp: 1.15, ph: 1.4 },
    { rgb: "57,208,255",  a: 0.15, base: 41, step: 1.0, mul: 0.80, sp: 0.90, ph: 2.8 },
    { rgb: "36,126,255",  a: 0.13, base: 55, step: 1.0, mul: 0.72, sp: 1.30, ph: 0.7 },
    { rgb: "0,207,255",   a: 0.12, base: 71, step: 1.0, mul: 0.60, sp: 1.50, ph: 3.6 },
    { rgb: "255,255,255", a: 0.30, base: 12, step: 0.9, mul: 0.35, sp: 1.70, ph: 5.2, hi: true },
  ];
  const CURVES = 38;

  const particles = Array.from({ length: 100 }, () => ({
    x: Math.random() * W, y: Math.random() * H * 0.7,
    vx: (Math.random() - 0.5) * 0.18, vy: -0.03 - Math.random() * 0.10,
    r: Math.random() * 1.2 + 0.4, a: 0.05 + Math.random() * 0.10,
    ph: Math.random() * Math.PI * 2,
  }));

  let prev = performance.now();
  function frame(ts) {
    if (!host.isConnected) return;
    const dt = Math.min(0.05, (ts - prev) / 1000); prev = ts;
    sim.amp += (targetAmp() - sim.amp) * (1 - Math.pow(0.0005, dt));
    const A = sim.amp;
    sim.t += dt * targetSpeed();

    // deep navy vertical gradient scene
    const bg = ctx.createLinearGradient(0, 0, 0, H);
    bg.addColorStop(0, "#0D355A");
    bg.addColorStop(1, "#0B2947");
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, W, H);

    // imperceptible camera drift + breathing zoom
    ctx.save();
    ctx.translate(W / 2, H / 2);
    ctx.scale(1.008, 1.008);
    ctx.translate(-W / 2, -H / 2 + Math.sin(sim.t * 0.1) * 1.5);

    // ambient under-glow
    const g = ctx.createRadialGradient(W / 2, H + 6, 8, W / 2, H + 6, W * 0.7);
    g.addColorStop(0, `rgba(0,207,255,${0.10 + 0.10 * A})`);
    g.addColorStop(1, "rgba(0,207,255,0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, H);

    // dense silk wave layers (hundreds of thin curves, additive)
    ctx.globalCompositeOperation = "lighter";
    const stretch = 1 + A * 0.4;
    for (const L of groups) {
      const amp = A * 34 * L.mul;
      for (let k = 0; k < CURVES; k++) {
        const fade = 1 - (k / CURVES) * 0.75;
        const yBase = L.base + k * L.step;
        ctx.strokeStyle = `rgba(${L.rgb},${(L.a * fade).toFixed(3)})`;
        ctx.lineWidth = 1; ctx.lineCap = "round";
        ctx.beginPath();
        for (let x = 0; x <= W; x += 3) {
          const tx = x / W;
          const n = noise(tx * 0.6 * stretch, sim.t * 0.5 + L.ph + k * 0.05);
          const peak = 7 * Math.sin(tx * 6 + sim.t * 0.9 + L.ph + k * 0.3) * A * 1.5 * L.mul;
          const micro = (L.hi ? Math.sin(sim.t * 4 + L.ph + k) * 1.5 : 0);
          const yy = yBase + amp * n + peak + micro + tx * 10;
          if (x === 0) ctx.moveTo(x, yy); else ctx.lineTo(x, yy);
        }
        ctx.stroke();
      }
    }
    ctx.globalCompositeOperation = "source-over";

    // floating particles
    for (const p of particles) {
      p.x += p.vx; p.y += p.vy + Math.sin(sim.t * 0.5 + p.ph) * 0.02;
      if (p.y < -2) { p.y = H * 0.7; p.x = Math.random() * W; }
      ctx.fillStyle = `rgba(200,235,255,${p.a + A * 0.06})`;
      ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2); ctx.fill();
    }

    // central energy orb (anchors the lower portion)
    const ox = W / 2, oy = H - 30 + Math.sin(sim.t * 0.7) * 2;
    const or = 13 + A * 18;
    const glow = 50 + A * 110;
    const orb = ctx.createRadialGradient(ox, oy, 1, ox, oy, or + glow);
    orb.addColorStop(0, `rgba(255,255,255,${0.30 + 0.5 * A})`);
    orb.addColorStop(0.25, `rgba(0,207,255,${0.30 + 0.3 * A})`);
    orb.addColorStop(0.6, `rgba(57,208,255,${0.12 + 0.12 * A})`);
    orb.addColorStop(1, "rgba(0,207,255,0)");
    ctx.fillStyle = orb;
    ctx.beginPath(); ctx.arc(ox, oy, or + glow, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = `rgba(255,255,255,${0.55 + 0.45 * A})`;
    ctx.beginPath(); ctx.arc(ox, oy, or * 0.72, 0, Math.PI * 2); ctx.fill();

    ctx.restore();
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

/* ------------------------------ Captions --------------------------------- */
function buildCaptions() {
  const box = el("div", "captions");
  box.id = "drawer-captions";
  return box;
}

function renderCaptions() {
  const host = $("drawer-captions");
  if (!host) return;
  host.innerHTML = "";
  if (!state.captions.length) {
    host.appendChild(el("div", "caption-empty", "Listening… no captions yet."));
    return;
  }
  for (const cap of state.captions) {
    const bubble = el("div", `caption-bubble ${cap.kind === "agent" ? "agent" : "applicant"}`);
    bubble.appendChild(el("span", "caption-role", cap.kind === "agent" ? "VoxGate" : "Applicant"));
    if (cap.text) {
      const txt = el("span");
      const interim = cap.interim;
      txt.appendChild(el("span", interim ? "caption-word interim" : "", cap.text));
      if (interim) txt.appendChild(el("span", "caption-cursor"));
      bubble.appendChild(txt);
    }
    host.appendChild(bubble);
  }
}

/* ------------------------ Voice session internals ------------------------- */
function buildVoicePanel(c) {
  const panel = el("div", "voice-session");
  const interviewing = !!(c.interrupt && c.interrupt.type === "interview");
  const status = el("div", "voice-status");
  status.id = "voice-status";
  status.textContent = interviewing ? "Interview pending" : "No live interview";
  panel.appendChild(status);

  const question = el("div", "voice-question");
  question.id = "voice-question";
  question.textContent = "Press Start Interview to begin.";
  panel.appendChild(question);

  const heard = el("div", "voice-heard");
  heard.id = "voice-heard";
  panel.appendChild(heard);

  const voiceRow = el("div", "voice-voice");
  const vlabel = el("label", "voice-voice-label", "Agent voice");
  vlabel.htmlFor = "voice-picker";
  const vsel = document.createElement("select");
  vsel.id = "voice-picker";
  vsel.className = "voice-voice-select";
  vsel.addEventListener("change", (e) => voiceSelect(e.target.value));
  voiceRow.appendChild(vlabel);
  voiceRow.appendChild(vsel);
  panel.appendChild(voiceRow);

  const controls = el("div", "voice-controls");
  const start = el("button", "btn voice-start", "Start Interview");
  start.id = "voice-start";
  start.type = "button";
  start.addEventListener("click", voiceStart);
  const end = el("button", "btn voice-end", "End");
  end.id = "voice-end";
  end.type = "button";
  end.disabled = true;
  end.addEventListener("click", () => voiceEnd(false));
  controls.appendChild(start);
  controls.appendChild(end);
  panel.appendChild(controls);

  const scenarioRow = el("div", "voice-voice");
  const slabel = el("label", "voice-voice-label", "Scenario");
  slabel.htmlFor = "voice-scenario";
  const ssel = document.createElement("select");
  ssel.id = "voice-scenario";
  ssel.className = "voice-voice-select";
  ssel.appendChild(el("option", null, "kyc-interview"));
  ssel.addEventListener("change", (e) => { voice.scenarioName = e.target.value || "kyc-interview"; });
  api("/voice/scenarios").then((list) => {
    if (!Array.isArray(list) || !list.length) return;
    ssel.innerHTML = "";
    for (const s of list) { const o = el("option", null, s.display_name); o.value = s.id; ssel.appendChild(o); }
    if (voice.scenarioName) ssel.value = voice.scenarioName;
  }).catch(() => {});
  scenarioRow.appendChild(slabel);
  scenarioRow.appendChild(ssel);
  panel.appendChild(scenarioRow);

  const typed = el("div", "voice-typed");
  typed.id = "voice-typed";
  const tin = el("input", "voice-typed-input send-input");
  tin.id = "voice-typed-input";
  tin.type = "text";
  tin.placeholder = "Type your answer and press Enter…";
  tin.autocomplete = "off";
  const tinSend = el("button", "btn voice-typed-send", "Send");
  tinSend.type = "button";
  const tinSubmit = () => {
    const v = tin.value.trim();
    if (!v || !voice.active) return;
    tin.value = "";
    if (pc.running) { pcSendText(v); publishCaption("applicant", v); return; }
    if (voice.cur) commitAnswer(v);
  };
  tinSend.addEventListener("click", tinSubmit);
  tin.addEventListener("keydown", (e) => {
    if (e.key === "Enter") tinSubmit();
    if (e.key === "Escape") { tin.value = ""; tin.blur(); }
  });
  typed.appendChild(tin);
  typed.appendChild(tinSend);
  panel.appendChild(typed);

  const progress = el("div", "voice-progress");
  progress.id = "voice-progress";
  panel.appendChild(progress);

  refreshVoicePicker();
  syncVoiceUI();
  return panel;
}

function voiceStatusText() {
  if (voice.done) return "Interview complete";
  if (!voice.active) return "Interview pending";
  if (voice.typedMode) return "Type your answers below…";
  if (voice.busy) return "Thinking…";
  if (voice.speaking) return "VoxGate is speaking…";
  if (voice.listening) return "Listening — please answer…";
  return "Interview in progress";
}

function syncVoiceUI() {
  const start = $("voice-start");
  const end = $("voice-end");
  const status = $("voice-status");
  const question = $("voice-question");
  const heard = $("voice-heard");
  const progress = $("voice-progress");
  const typed = $("voice-typed");
  const tin = $("voice-typed-input");

  if (start) { start.disabled = voice.active || voice.done; }
  if (end) end.disabled = !voice.active;

  const c = state.openCase;
  const interviewing = !!c && !!(c.interrupt && c.interrupt.type === "interview");
  if (status) status.textContent = voiceStatusText();
  if (question) {
    if (voice.cur) question.textContent = voice.cur.hint;
    else if (voice.active && !voice.done) question.textContent = "Preparing next question…";
    else question.textContent = interviewing ? "Press Start Interview to begin." : "No live interview";
  }
  if (heard) {
    heard.innerHTML = "";
    if (voice.transcript) heard.appendChild(el("span", "voice-heard-text", "You: " + voice.transcript));
  }
  if (progress) {
    const total = voice.queue.length + Object.keys(voice.fields).length + (voice.cur ? 1 : 0);
    const n = Object.keys(voice.fields).length + (voice.cur ? 1 : 0);
    progress.textContent = voice.active && total ? `Question ${n} of ${total}` : "";
  }
  if (typed) typed.classList.toggle("hidden", !(voice.active && !voice.done && (voice.typedMode || pc.running)));
  if (tin) tin.disabled = !(voice.active && (voice.cur || pc.running));
  if (tin && voice.typedMode && voice.active && !voice.done && voice.cur && document.activeElement !== tin) {
    tin.focus();
  }
}

function voiceBuildQueue(c) {
  const pack = state.packById[c.pack_id] || {};
  const hints = pack.reask_hints || {};
  const fields = pack.fields || [];
  const interrupt = (c.interrupt && c.interrupt.type === "interview") ? c.interrupt : null;
  const reask = interrupt ? (interrupt.reask_fields || []) : [];
  const have = Object.keys(voice.fields);
  const mk = (field) => ({ field, hint: (interrupt && interrupt.reask_hints && interrupt.reask_hints[field]) ||
                                     hints[field] || `Please tell me your ${field.replace(/_/g, " ")}.` });
  let list;
  if (reask.length) list = reask.filter((f) => !have.includes(f)).map(mk);
  else list = fields.filter((f) => !have.includes(f)).map(mk);
  voice.queue = list;
}

function speak(text) {
  return new Promise((resolve) => {
    const u = new SpeechSynthesisUtterance(String(text || ""));
    u.rate = 0.95;
    u.pitch = 1.0;
    u.volume = 1.0;
    u.voice = currentVoice();
    u.onstart = () => { voice.speaking = true; syncVoiceUI(); };
    u.onend = u.onerror = () => { voice.speaking = false; syncVoiceUI(); resolve(); };
    speechSynthesis.cancel();
    speechSynthesis.speak(u);
  });
}

async function voiceStart() {
  if (voice.active || voice.done) return;
  const c = state.openCase;
  if (!c || !(c.interrupt && c.interrupt.type === "interview")) {
    toast("Open a case that is awaiting interview to start.", "error");
    return;
  }

  // Preferred path: full-duplex Pipecat voice (server STT -> LLM -> TTS).
  // Mirrors its wiring in agent.py; captions/status arrive via the /events bus.
  if (pcSupported()) {
    try {
      await pcStart();
      return;
    } catch (err) {
      await pcTeardown().catch(() => {});
      toast("Pipecat voice unavailable (" + (err && err.message ? err.message : "unsupported") + "). Falling back…", "warning");
      voice.listening = false;
      voice.speaking = false;
    }
  }

  // ---- Fallback: browser Web-Speech flow (forward TTS + SpeechRecognition). ----
  if (!ttsSupported()) {
    toast("This browser has no speech synthesis, so the agent cannot speak.", "error");
    return;
  }
  voice.busy = true;
  voice.typedMode = !sttSupported();
  if (!voice.voiceName) {
    try { voice.voiceName = localStorage.getItem("voxgate_voice") || ""; } catch (_) {}
  }
  loadVoices();
  syncVoiceUI();
  if (!voice.typedMode) {
    try {
      voice.mic = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (_) {
      voice.typedMode = true;                       // fall back to typing answers
      toast("Microphone unavailable — you can still type your answers.", "warning");
    }
  } else {
    toast("Speech recognition unavailable — please type your answers.", "warning");
  }
  voice.active = true;
  voice.done = false;
  voice.fields = {};
  voice.confidence = {};
  voice.attempts = {};
  voiceBuildQueue(c);
  voice.busy = false;
  toast("Interview started.", "info");
  await voiceAskNext();
}

function clearVoiceIdle() { if (voice.idleT) { clearTimeout(voice.idleT); voice.idleT = null; } }

async function onVoiceIdle() {
  // User hasn't spoken in ~20s of listening — gently prompt for clarification.
  if (!voice.active || voice.done || voice.busy || !voice.listening) return;
  voice.listening = false;
  if (voice.recog) { try { voice.recog.stop(); } catch (_) {} }
  await speak("I didn't hear a response. Could you say that again, please?");
  if (voice.active && !voice.done) voiceListen();
}

function voiceListen() {
  if (!voice.active || voice.done || voice.busy) return;
  if (voice.typedMode) { syncVoiceUI(); return; }
  if (!voice.recog) {
    voice.recog = new SpeechRec();
    voice.recog.continuous = true;
    voice.recog.interimResults = true;
    voice.recog.lang = "en-US";
    voice.recog.onresult = (e) => {
      let interim = "";
      let final = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) final += r[0].transcript; else interim += r[0].transcript;
      }
      // Any speech activity pushes back the silence nudge.
      clearVoiceIdle();
      voice.idleT = setTimeout(onVoiceIdle, 15000);
      voice.errTally = 0;
      voice.transcript = (final + interim).trim();
      syncVoiceUI();
      if (final.trim()) {
        voice.busy = true;
        voice.wantListen = false;
        try { voice.recog.stop(); } catch (_) {}
        commitAnswer(final.trim());
      }
    };
    voice.recog.onend = () => {
      // Unconditional auto-restart while we still need to hear a reply.
      if (voice.active && !voice.done && !voice.busy && voice.wantListen) {
        setTimeout(() => {
          if (voice.active && !voice.done && !voice.busy && voice.wantListen) {
            try { voice.recog.start(); } catch (_) {}
          }
        }, 120);
      }
    };
    voice.recog.onerror = (e) => recogError(e.error);
  }
  clearVoiceIdle();
  voice.idleT = setTimeout(onVoiceIdle, 15000);
  voice.transcript = "";
  voice.wantListen = true;
  voice.listening = true;
  voice.errTally = 0;
  syncVoiceUI();
  try { voice.recog.start(); } catch (_) {}
}

function recogError(code) {
  if (!voice.active || voice.done) return;
  if (code === "not-allowed" || code === "service-not-allowed") {
    toast("Microphone access blocked — switch to typing your answers.", "error");
    voice.typedMode = true;
    voice.wantListen = false;
    syncVoiceUI();
    return;
  }
  // Recoverable glitches (no-speech, aborted, audio-capture, network…): retry,
  // and if speech keeps failing, fall back to typed answers automatically.
  voice.errTally = (voice.errTally || 0) + 1;
  if (voice.errTally >= 3) {
    toast("Speech keeps failing — switch to typing your answers instead.", "warning");
    voice.typedMode = true;
    voice.wantListen = false;
    clearVoiceIdle();
    syncVoiceUI();
    return;
  }
  voice.wantListen = false;
  clearVoiceIdle();
  setTimeout(() => {
    if (voice.active && !voice.done && !voice.busy) {
      voice.errTally = (voice.errTally || 0) + 1;
      voice.wantListen = true;
      voice.listening = true;
      syncVoiceUI();
      try { voice.recog.start(); } catch (_) {}
    }
  }, 400);
}

async function voiceAskNext() {
  if (!voice.active || voice.done) return;
  if (!voice.cur) voice.cur = voice.queue.shift() || null;
  if (!voice.cur) { await voiceSubmit(); return; }
  const q = voice.cur;
  voice.transcript = "";
  let line = q.hint;
  try {
    const r = await api(`/cases/${state.openId}/agent-line`, {
      method: "POST",
      body: JSON.stringify({
        field: q.field,
        hint: q.hint,
        last_captured: voice.lastCaptured,
        attempt: voice.attempts[q.field] || 0,
      }),
    });
    if (r && r.line) line = r.line;
  } catch (_) { /* fall back to the pack hint */ }
  voice.lastCaptured = null;
  publishCaption("agent", line);
  voice.wantListen = false;
  voice.listening = false;
  await speak(line);
  if (!voice.active || voice.done) return;
  voiceListen();
  syncVoiceUI();
}

async function commitAnswer(text) {
  const q = voice.cur;
  voice.listening = false;
  clearVoiceIdle();
  syncVoiceUI();
  publishCaption("applicant", text);
  if (!q) { voice.busy = false; return; }
  let val = { value: text, confidence: 0.5, source: "raw" };
  try {
    const r = await api(`/cases/${state.openId}/answer`, {
      method: "POST",
      body: JSON.stringify({ field: q.field, transcript: text }),
    });
    val = r || val;
  } catch (_) { /* fall back to raw */ }
  if (val.value == null || val.value === "") {
    // Couldn't make sense of the answer — ask for clarification (agent writes the line).
    voice.attempts[q.field] = (voice.attempts[q.field] || 0) + 1;
    toast(voice.attempts[q.field] > 1 ? "Still not clear — please try again." : "I didn't catch that — please try again.", "warning");
    let line = "Sorry, I didn't catch that. " + q.hint;
    try {
      const r = await api(`/cases/${state.openId}/agent-line`, {
        method: "POST",
        body: JSON.stringify({ field: q.field, hint: q.hint, transcript: text, attempt: voice.attempts[q.field] }),
      });
      if (r && r.line) line = r.line;
    } catch (_) {}
    await speak(line);
    voice.busy = false;
    if (voice.active && !voice.done) voiceAskNext();
    return;
  }
  voice.fields[q.field] = val.value;
  voice.confidence[q.field] = val.confidence || 0.5;
  delete voice.attempts[q.field];
  voice.lastCaptured = { field: q.field, value: val.value };
  voice.cur = null;
  voice.busy = false;
  syncVoiceUI();
  await voiceAskNext();
}

async function voiceSubmit() {
  voice.done = true;
  voice.busy = true;
  voice.listening = false;
  voice.queue = [];
  if (voice.recog) { try { voice.recog.stop(); } catch (_) {} }
  syncVoiceUI();
  toast("Submitting answers…", "info");
  try {
    const c = await api(`/cases/${state.openId}/interview-result`, {
      method: "POST",
      body: JSON.stringify({ fields: voice.fields, confidence: voice.confidence }),
    });
    const newInt = (c.interrupt && c.interrupt.type === "interview") ? c.interrupt : null;
    state.openCase = c;
    const i = state.cases.findIndex((x) => x.case_id === c.case_id);
    if (i >= 0) state.cases[i] = c;
    if (newInt && newInt.reask_fields && newInt.reask_fields.length) {
      toast("A few answers need clarification — please re-answer.", "warning");
      voice.done = false;
      voice.busy = false;
      voice.cur = null;
      voiceBuildQueue(c);
      await voiceAskNext();
      return;
    }
    const status = c.status === "approved" ? "approved" : c.status === "rejected" ? "rejected" : "sent for review";
    voiceEnd(true);
    speak(`Thank you. Your interview is complete and the case has been ${status.replace(/_/g, " ")}.`);
    toast("Interview complete.", "success");
    renderBoard(); renderKpis(); renderDrawer();
  } catch (err) {
    voice.done = false;
    voice.busy = false;
    toast("Submit failed: " + err.message, "error");
    syncVoiceUI();
  }
}

function voiceEnd(complete) {
  if (pc.running) pcTeardown();
  voice.active = false;
  voice.listening = false;
  voice.done = !!complete;
  voice.busy = false;
  voice.cur = null;
  voice.queue = [];
  if (voice.recog) { try { voice.recog.stop(); } catch (_) {} voice.recog = null; }
  if (voice.mic) { voice.mic.getTracks().forEach((t) => t.stop()); voice.mic = null; }
  speechSynthesis.cancel();
  if (!complete) toast("Interview ended.", "info");
  syncVoiceUI();
  renderCaptions();
}

/* --------------------------- Interview tab -------------------------------- */
const debPipes = {};

function renderInterview(body, c) {
  const is = !!(c.interrupt && c.interrupt.type === "interview");
  const interrupt = c.interrupt && c.interrupt.type === "interview" ? c.interrupt : null;
  const fields = packFields(c.pack_id);

  body.appendChild(el("h4", null, "Interview"));
  if (!is) {
    body.appendChild(el("p", "note", "This case is not currently awaiting interview fields."));
  } else if (interrupt) {
    const info = el("p", "note");
    info.textContent = `Attempt ${interrupt.attempt || 0} / ${interrupt.max_attempts || 2} · re-ask: ${(interrupt.reask_fields || []).join(", ") || "none"}`;
    body.appendChild(info);
  }

  const reask = new Set((interrupt && interrupt.reask_fields) || []);
  const hints = (interrupt && interrupt.reask_hints) || {};
  const errors = (interrupt && interrupt.field_errors) || {};
  const values = Object.assign({}, c.fields || {}, (interrupt && interrupt.fields_so_far) || {});

  const form = el("div", "form-grid");
  for (const f of fields) {
    const fld = el("div", "form-field" + (f.length > 16 ? " full" : ""));
    const label = el("label");
    if (reask.has(f)) {
      const req = el("span", "required", "*");
      label.appendChild(req);
    }
    label.appendChild(document.createTextNode(cap(f)));
    fld.appendChild(label);

    const input = document.createElement("input");
    input.type = "text";
    input.className = "field-input" + (reask.has(f) ? " reask" : "");
    input.value = values[f] || "";
    input.dataset.field = f;
    if (!is) input.disabled = true;
    fld.appendChild(input);

    if (hints[f]) fld.appendChild(el("div", "reask-hint", "Hint: " + hints[f]));
    if (errors[f]) fld.appendChild(el("div", "reask-hint", "Validation: " + errors[f]));
    form.appendChild(fld);
  }
  body.appendChild(form);

  if (is) {
    form.addEventListener("input", (e) => {
      const input = e.target && e.target.closest ? e.target.closest(".field-input") : null;
      if (!input || !state.openCase) return;
      clearTimeout(debPipes[input.dataset.field]);
      const field = input.dataset.field;
      const value = input.value;
      debPipes[field] = setTimeout(async () => {
        try {
          await api(`/cases/${state.openCase.case_id}/fields`, {
            method: "PATCH", body: JSON.stringify({ fields: { [field]: value }, confidence: {} }),
          });
        } catch (_) { /* live-only feed */ }
      }, 400);
    });
  }

  const actions = el("div", "drawer-section");
  const submit = el("button", "btn btn-primary", "Submit interview");
  submit.type = "button";
  if (!is) submit.disabled = true;
  submit.addEventListener("click", async () => {
    const f = {};
    body.querySelectorAll(".field-input[data-field]").forEach((inp) => { f[inp.dataset.field] = inp.value; });
    try {
      const updated = await api(`/cases/${c.case_id}/interview-result`, {
        method: "POST", body: JSON.stringify({ fields: f, confidence: {} }),
      });
      toast("Interview submitted", "success");
      if (state.openId === c.case_id) state.openCase = updated;
      renderDrawer(); renderBoard(); renderKpis();
      renderCaptions();
    } catch (err) {
      toast("Interview: " + err.message, err.status === 409 ? "info" : "error");
      if (err.status === 409) refreshOne(c.case_id, true);
    }
  });
  actions.appendChild(submit);
  body.appendChild(actions);
}

async function refreshOne(caseId, keepOpen) {
  try {
    const c = await api(`/cases/${caseId}`);
    const i = state.cases.findIndex((x) => x.case_id === caseId);
    if (i >= 0) state.cases[i] = c;
    if (state.openId === caseId) state.openCase = c;
    renderBoard(); renderKpis(); renderAnalytics();
    if (state.openId === caseId) renderDrawer();
  } catch (_) {}
}

/* --------------------------- Review tab ----------------------------------- */
async function postDecision(caseId, action, note) {
  try {
    const updated = await api(`/cases/${caseId}/decision`, {
      method: "POST", body: JSON.stringify({ action, note: note || "" }),
    });
    toast("Decision: " + action.replace(/_/g, " "), "success");
    if (state.openId === caseId) state.openCase = updated;
    renderDrawer(); renderBoard(); renderKpis();
  } catch (err) {
    toast("Decision: " + err.message, err.status === 409 ? "info" : "error");
    if (err.status === 409) refreshOne(caseId, true);
  }
}

function renderReview(body, c) {
  const interrupt = c.interrupt && c.interrupt.type === "review" ? c.interrupt : null;
  body.appendChild(el("h4", null, "Reviewer gate"));
  if (!interrupt) {
    body.appendChild(el("p", "note", "This case is not currently awaiting a review decision."));
    return;
  }

  body.appendChild(el("p", null, `${interrupt.gate_role || "gate"} · reask count ${interrupt.reask_count || 0}${interrupt.force_review ? " · forced review" : ""}`));
  if (interrupt.score) {
    const s = el("div", "drawer-section");
    s.appendChild(el("h4", null, "Risk score"));
    s.appendChild(scoreWaterfall(interrupt.score));
    body.appendChild(s);
  }

  const flagged = interrupt.flagged_checks || [];
  if (flagged.length) {
    const s = el("div", "drawer-section");
    s.appendChild(el("h4", null, "Flagged checks"));
    const ev = el("div", "check-evidence");
    for (const chk of flagged) {
      const card = el("div", "check-card");
      const head = el("div", "check-card-head");
      head.appendChild(el("span", "check-card-name", chk.check_name));
      head.appendChild(el("span", "check-score", String(chk.score == null ? "" : chk.score)));
      card.appendChild(head);
      const details = chk.details || {};
      const cands = details.candidates || [];
      if (cands.length) {
        for (const cand of cands.slice(0, 4)) {
          card.appendChild(el("div", "candidate", `• ${cand.list_name} — ${cand.entry_name}`));
        }
      } else if (details.articles) {
        card.appendChild(el("div", "candidate", `${details.articles} article(s)`));
      }
      const status = el("div", "candidate");
      status.textContent = chk.status.charAt(0).toUpperCase() + chk.status.slice(1);
      card.appendChild(status);
      ev.appendChild(card);
    }
    s.appendChild(ev);
    body.appendChild(s);
  }

  const note = document.createElement("textarea");
  note.className = "decision-note";
  note.rows = 2;
  note.placeholder = "Note for the decision (optional)";
  body.appendChild(note);

  const actions = el("div", "decision-actions");
  for (const [action, cls, label] of [["approve", "btn-success", "Approve"], ["reject", "btn-danger", "Reject"], ["request_info", "btn-ghost", "Request more info"]]) {
    const btn = el("button", `btn ${cls}`, label);
    btn.type = "button";
    btn.addEventListener("click", () => postDecision(c.case_id, action, note.value));
    actions.appendChild(btn);
  }
  body.appendChild(actions);
}

/* ---------------------------- Pipeline tab -------------------------------- */
const PL_EDGES = [
  ["intake", "interview"],
  ["interview", "extract_validate"],
  ["extract_validate", "check_sanctions"],
  ["extract_validate", "check_pep"],
  ["extract_validate", "check_adverse_media"],
  ["check_sanctions", "score"],
  ["check_pep", "score"],
  ["check_adverse_media", "score"],
  ["score", "auto_approve"],
  ["score", "awaiting_review"],
  ["awaiting_review", "reviewer_gate"],
  ["auto_approve", "finalize"],
  ["reviewer_gate", "finalize"],
];

const PL_NODES = {
  intake: { label: "intake", x: 20, y: 95, w: 96, h: 30 },
  interview: { label: "interview", x: 140, y: 95, w: 110, h: 30 },
  extract_validate: { label: "extract·validate", x: 274, y: 95, w: 122, h: 30 },
  check_sanctions: { label: "sanctions", cx: 448, cy: 40, r: 22, circle: true },
  check_pep: { label: "pep", cx: 448, cy: 110, r: 22, circle: true },
  check_adverse_media: { label: "adverse media", cx: 448, cy: 185, r: 22, circle: true },
  score: { label: "score", x: 540, y: 95, w: 110, h: 30 },
  auto_approve: { label: "auto approve", x: 720, y: 30, w: 126, h: 30 },
  awaiting_review: { label: "awaiting review", x: 720, y: 96, w: 150, h: 30 },
  reviewer_gate: { label: "reviewer gate", x: 720, y: 156, w: 150, h: 30 },
  finalize: { label: "finalize", x: 880, y: 96, w: 96, h: 30 },
};

function nodeCenter(id) {
  const n = PL_NODES[id];
  if (!n) return null;
  if (n.circle) return { x: n.cx, y: n.cy };
  return { x: n.x + n.w / 2, y: n.y + n.h / 2 };
}

function renderPipeline(body, c) {
  const entry = c.audit && c.audit.length ? c.audit[c.audit.length - 1] : null;
  const current = entry ? entry.node : null;
  const visited = new Set((c.audit || []).map((a) => a.node));

  const wrap = el("div", "pipeline-wrap");
  const svg = document.createElementNS(NS_SVG, "svg");
  svg.setAttribute("class", "pipeline-svg");
  svg.setAttribute("viewBox", "0 0 1000 220");
  svg.setAttribute("width", "100%");

  for (const [from, to] of PL_EDGES) {
    const a = nodeCenter(from), b = nodeCenter(to);
    if (!a || !b) continue;
    const path = document.createElementNS(NS_SVG, "path");
    const dx = Math.max(20, (b.x - a.x) / 2);
    path.setAttribute("d", `M ${a.x} ${a.y} C ${a.x + dx} ${a.y} ${b.x - dx} ${b.y} ${b.x} ${b.y}`);
    path.setAttribute("class", "pl-edge" + (current === to ? " active" : ""));
    svg.appendChild(path);
  }

  for (const id of Object.keys(PL_NODES)) {
    const n = PL_NODES[id];
    const g = document.createElementNS(NS_SVG, "g");
    g.setAttribute("class", "pl-node" + (visited.has(id) ? " visited" : "") + (current === id ? " current" : ""));
    let cx, cy;
    if (n.circle) {
      const circle = document.createElementNS(NS_SVG, "circle");
      circle.setAttribute("cx", n.cx); circle.setAttribute("cy", n.cy); circle.setAttribute("r", n.r);
      g.appendChild(circle);
      cx = n.cx; cy = n.cy;
    } else {
      const rect = document.createElementNS(NS_SVG, "rect");
      rect.setAttribute("x", n.x); rect.setAttribute("y", n.y);
      rect.setAttribute("width", n.w); rect.setAttribute("height", n.h); rect.setAttribute("rx", 6);
      g.appendChild(rect);
      cx = n.x + n.w / 2; cy = n.y + n.h / 2;
    }
    const label = document.createElementNS(NS_SVG, "text");
    label.setAttribute("x", cx); label.setAttribute("y", cy + 3);
    label.setAttribute("text-anchor", "middle");
    label.textContent = n.label;
    g.appendChild(label);
    if (current === id) {
      const pulse = document.createElementNS(NS_SVG, "circle");
      pulse.setAttribute("class", "pl-pulse");
      pulse.setAttribute("cx", cx); pulse.setAttribute("cy", cy);
      g.appendChild(pulse);
    }
    svg.appendChild(g);
  }
  wrap.appendChild(svg);
  body.appendChild(wrap);
}

/* ----------------------------- Events tab --------------------------------- */
function renderEvents(body, c) {
  body.appendChild(el("h4", null, "Live events"));
  const feed = el("div", "event-feed");
  feed.dataset.feed = c.case_id;
  const arr = state.evts && state.evts.length ? recentEvents(c.case_id) : [];
  arr.slice().reverse().forEach((ev) => feed.appendChild(eventRow(ev)));
  body.appendChild(feed);
}

function recentEvents(caseId) {
  // persisted per-case in EVENTS history map
  return (EVENT_LOG[caseId] || []);
}

const EVENT_LOG = {};

function pushEvent(caseId, ev) {
  const arr = (EVENT_LOG[caseId] || (EVENT_LOG[caseId] = []));
  arr.push(Object.assign({}, ev, { t: Date.now() }));
  if (arr.length > 200) arr.shift();
  recordEvent();
}

function eventSummary(ev) {
  if (ev.kind === "state") return ev.case && ev.case.status ? "status → " + ev.case.status : "state update";
  if (ev.kind === "fields") return "live fields updated";
  if (ev.kind === "caption") return `${ev.role || "agent"}${ev.interim ? " (interim)" : ""}: ${String(ev.text || "").slice(0, 60)}`;
  return String(ev.kind || "");
}

function eventRow(ev) {
  const row = el("div", "event-row");
  row.appendChild(el("span", "event-dot"));
  row.appendChild(el("span", "event-kind", ev.kind));
  row.appendChild(el("span", null, eventSummary(ev)));
  row.appendChild(el("span", "event-time", timeLabel(ev.t)));
  return row;
}

/* ------------------------------ WebSocket --------------------------------- */
function wsUrl(caseId) {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}/cases/${caseId}/events`;
}

function watchCase(caseId) {
  unwatch();
  let ws;
  try { ws = new WebSocket(wsUrl(caseId)); } catch (err) { return; }
  state.ws = ws;
  state.wsBackoff = 1000;
  setWs("connecting");
  ws.onopen = () => { state.wsBackoff = 1000; setWs("live"); };
  ws.onmessage = (msg) => {
    let ev;
    try { ev = JSON.parse(msg.data); } catch (_) { return; }
    pushEvent(caseId, ev);
    handleWSEvent(caseId, ev);
  };
  ws.onclose = () => { setWs("down"); scheduleReconnect(caseId); };
  ws.onerror = () => { setWs("connecting"); };
}

function unwatch() {
  if (state.ws) { try { state.ws.close(); } catch (_) {} state.ws = null; }
  if (state.reconnectT) { clearTimeout(state.reconnectT); state.reconnectT = null; }
}

function scheduleReconnect(caseId) {
  if (state.ws || state.openId !== caseId) return;
  const delay = state.wsBackoff;
  state.wsBackoff = Math.min(state.wsBackoff * 1.6, 8000);
  state.reconnectT = setTimeout(() => {
    if (state.openId === caseId && !state.ws) watchCase(caseId);
  }, delay);
}

function setWs(label) {
  const b = $("mon-ws-state");
  if (b) b.textContent = label;
  if (label === "live") setConn("live", "Live · WS");
  else if (label === "connecting") setConn("connecting", "Connecting");
  else setConn("down", "WS down");
}

function handleWSEvent(caseId, ev) {
  if (ev.kind === "state") {
    if (ev.case) {
      const i = state.cases.findIndex((x) => x.case_id === ev.case.case_id);
      if (i >= 0) state.cases[i] = ev.case;
      if (state.openId === ev.case.case_id) state.openCase = ev.case;
    }
    renderBoard(); renderKpis(); renderAnalytics(); renderAttention();
    flashRow(caseId);
    if (state.openId === caseId) renderDrawer();
  } else if (ev.kind === "fields") {
    if (state.openId === caseId) {
      state.liveFields = ev.fields || {};
      state.conf = ev.confidence || {};
      if (ev.fields && Object.keys(ev.fields).length) {
        const parts = Object.entries(ev.fields).map(([k, v]) => `${k}=${v}`);
        state.captions.push({ kind: "applicant", text: "Captured: " + parts.join(", ") });
        renderCaptions();
      }
    }
  } else if (ev.kind === "caption") {
    if (state.openId === caseId) {
      state.captions.push({ kind: ev.role === "agent" ? "agent" : "applicant", text: ev.text || "", interim: ev.interim || false });
      renderCaptions();
    }
  }
}

/* ----------------------- Events rate + sparkline -------------------------- */
function recordEvent() {
  state.evts.push(Date.now());
  if (state.evts.length > 2000) state.evts = state.evts.slice(-2000);
  const cutoff = Date.now() - 60000;
  while (state.evts.length && state.evts[0] < cutoff) state.evts.shift();
  const b = $("mon-events-rate");
  if (b) b.textContent = String(state.evts.length);
  drawSparkline();
}

function drawSparkline() {
  const line = document.querySelector("#sparkline polyline.spark-line");
  const fill = document.querySelector("#sparkline polygon.spark-fill");
  if (!line || !fill) return;
  const now = Date.now();
  const BUCKET = 3000, N = 40;
  const counts = new Array(N).fill(0);
  for (const t of state.evts) {
    const idx = Math.floor((now - t) / BUCKET);
    if (idx >= 0 && idx < N) counts[idx]++;
  }
  const max = Math.max(1, ...counts);
  // render oldest (idx N) at left, newest at right
  const pts = [];
  for (let i = 0; i < N; i++) {
    const x = ((N - 1 - i) / (N - 1)) * 240;
    const y = 44 - (counts[i] / max) * 40;
    pts.push(`${x.toFixed(1)},${y.toFixed(1)}`);
  }
  line.setAttribute("points", pts.join(" "));
  fill.setAttribute("points", [...pts, "240,44", "0,44"].join(" "));
}

/* ------------------------------ Actions ----------------------------------- */
async function newCase() {
  const sel = $("pack-select");
  const pid = sel && sel.value ? sel.value : (Object.keys(state.packById)[0]);
  if (!pid) { toast("No pack selected", "error"); return; }
  try {
    const c = await api("/cases", { method: "POST", body: JSON.stringify({ pack_id: pid }) });
    toast("New case created", "success");
    await refreshAll();
    openCase(c.case_id);
  } catch (err) {
    toast("New case: " + err.message, "error");
  }
}

async function seedDemo() {
  try {
    const res = await api("/dashboard/demo-seed", { method: "POST" });
    const n = (res && res.cases && res.cases.length) || (res && res.seeded) || 0;
    toast(`Seeded ${n} demo case${n === 1 ? "" : "s"}`, "success");
    await refreshAll();
  } catch (err) {
    toast("Seed: " + err.message, "error");
  }
}

/* ------------------------------ UI wiring --------------------------------- */
function wireUI() {
  const tabs = $("drawer-tabs");
  if (tabs) tabs.addEventListener("click", (e) => {
    const tab = e.target.closest ? e.target.closest(".drawer-tab") : null;
    if (!tab) return;
    state.activeTab = tab.dataset.tab;
    setActiveTab(state.activeTab);
    renderDrawer();
  });

  const closeBtn = $("drawer-close");
  if (closeBtn) closeBtn.addEventListener("click", closeDrawer);
  const scrim = $("drawer-scrim");
  if (scrim) scrim.addEventListener("click", closeDrawer);

  const nb = $("btn-new-case");
  if (nb) nb.addEventListener("click", newCase);
  const nbe = $("btn-new-case-empty");
  if (nbe) nbe.addEventListener("click", newCase);
  const sd = $("btn-seed-demo");
  if (sd) sd.addEventListener("click", seedDemo);
  const sde = $("btn-seed-demo-empty");
  if (sde) sde.addEventListener("click", seedDemo);

  const av = $("attention-view");
  if (av) av.addEventListener("click", () => {
    const na = state.cases.find((x) => x.status === "needs_attention");
    if (na) openCase(na.case_id);
  });
  const ad = $("attention-dismiss");
  if (ad) ad.addEventListener("click", hideAttention);
}

document.addEventListener("DOMContentLoaded", () => {
  try {
    wireUI();
    boot();
  } catch (err) {
    toast("Init failed: " + ((err && err.message) || err), "error");
    setConn("down", "Down");
  }
});