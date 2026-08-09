"use client";

import { motion, useInView, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";

/**
 * The real graph topology from src/voxgate/graph/build.py, drawn to scale and
 * continuously walked. Every node and edge exists in the compiled StateGraph.
 *
 * Three animation layers, each with a job:
 *   1. Travelling dots on every edge, always running. Shows the graph is a live
 *      system rather than a picture.
 *   2. A walk that lights nodes in execution order. Shows the checks genuinely
 *      fan out in parallel, and that the graph stops at the two interrupts.
 *   3. Hover. Lets a reader interrogate any node without waiting for the walk.
 *
 * Geometry note: box widths come from label length at 11.5px mono (~6.9px per
 * character) plus padding, plus 16px where a pause glyph sits inside. Edge
 * coordinates derive from those box edges, so a width change needs a matching
 * edge change.
 */

type Tone = "default" | "approved" | "review";

type Node = {
  id: string;
  label: string;
  x: number;
  cy: number;
  w: number;
  pause?: boolean;
  tone?: Tone;
  role: string;
};

const H = 34;

const NODES: Node[] = [
  { id: "intake", label: "intake", x: 8, cy: 149, w: 76, role: "Opens the case and sets the initial status." },
  { id: "interview", label: "interview", x: 118, cy: 149, w: 108, pause: true, role: "Interrupts. Waits for the applicant's answers, however long that takes." },
  { id: "validate", label: "extract + validate", x: 260, cy: 149, w: 150, role: "Validates answers against the pack schema. Failures route back to a re-ask, capped at two." },
  { id: "sanctions", label: "sanctions", x: 444, cy: 73, w: 116, role: "Screens the name against sanctions lists, handling romanization variants." },
  { id: "pep", label: "PEP", x: 444, cy: 149, w: 116, role: "Screens against politically exposed person lists." },
  { id: "media", label: "adverse media", x: 444, cy: 225, w: 116, role: "Screens against adverse media records." },
  { id: "score", label: "score", x: 604, cy: 149, w: 84, role: "Additive log-odds scorecard. Every contribution is attributable." },
  { id: "route", label: "route", x: 722, cy: 149, w: 80, role: "Routes on risk band and whether any check returned a hit." },
  { id: "approve", label: "auto approve", x: 836, cy: 73, w: 130, tone: "approved", role: "Low risk and no hits. Approved without a human." },
  { id: "reask", label: "re-ask", x: 836, cy: 149, w: 130, role: "Medium risk. Asks one more targeted question, then re-scores." },
  { id: "gate", label: "reviewer gate", x: 836, cy: 225, w: 130, pause: true, tone: "review", role: "Interrupts. A compliance officer decides, with the evidence already assembled." },
];

type Edge = { id: string; from: string; to: string; d: string };

const EDGES: Edge[] = [
  { id: "e1", from: "intake", to: "interview", d: "M 84 149 L 118 149" },
  { id: "e2", from: "interview", to: "validate", d: "M 226 149 L 260 149" },
  { id: "e3", from: "validate", to: "sanctions", d: "M 410 149 C 427 149 427 73 444 73" },
  { id: "e4", from: "validate", to: "pep", d: "M 410 149 L 444 149" },
  { id: "e5", from: "validate", to: "media", d: "M 410 149 C 427 149 427 225 444 225" },
  { id: "e6", from: "sanctions", to: "score", d: "M 560 73 C 582 73 582 149 604 149" },
  { id: "e7", from: "pep", to: "score", d: "M 560 149 L 604 149" },
  { id: "e8", from: "media", to: "score", d: "M 560 225 C 582 225 582 149 604 149" },
  { id: "e9", from: "score", to: "route", d: "M 688 149 L 722 149" },
  { id: "e10", from: "route", to: "approve", d: "M 802 149 C 819 149 819 73 836 73" },
  { id: "e11", from: "route", to: "reask", d: "M 802 149 L 836 149" },
  { id: "e12", from: "route", to: "gate", d: "M 802 149 C 819 149 819 225 836 225" },
];

type Step = { active: string[]; ms: number; caption: string; waiting?: boolean };

const WALK: Step[] = [
  { active: ["intake"], ms: 800, caption: "Case opened" },
  { active: ["interview"], ms: 2600, caption: "Waiting for the applicant to answer", waiting: true },
  { active: ["validate"], ms: 1000, caption: "Answers validated against the pack schema" },
  { active: ["sanctions", "pep", "media"], ms: 1600, caption: "Three screening checks running in parallel" },
  { active: ["score"], ms: 1000, caption: "Risk scored, every contribution attributable" },
  { active: ["route"], ms: 800, caption: "Routing on band and screening hits" },
  { active: ["gate"], ms: 3000, caption: "Waiting for a compliance officer", waiting: true },
];

const ACCENT = "#c6f24e"; // active node, matching the LangGraph visual language

function toneColor(tone: Tone | undefined) {
  if (tone === "approved") return "var(--color-risk-low)";
  if (tone === "review") return "var(--color-status-awaiting-review)";
  return "#7debff";
}

export function PipelineDiagram() {
  const reduce = useReducedMotion();
  const wrapRef = useRef<HTMLElement>(null);
  const inView = useInView(wrapRef, { amount: 0.3 });
  const [step, setStep] = useState(0);
  const [hovered, setHovered] = useState<Node | null>(null);

  useEffect(() => {
    if (reduce || !inView) return;
    const timer = setTimeout(() => setStep((s) => (s + 1) % WALK.length), WALK[step].ms);
    return () => clearTimeout(timer);
  }, [step, inView, reduce]);

  const current = reduce ? WALK[WALK.length - 1] : WALK[step];
  const visited = new Set<string>();
  const upto = reduce ? WALK.length : step + 1;
  for (let i = 0; i < upto; i++) for (const id of WALK[i].active) visited.add(id);

  const activeSet = new Set(current.active);
  const detail = hovered ?? null;

  return (
    <figure ref={wrapRef} className="w-full">
      <div className="overflow-x-auto">
        <svg
          viewBox="0 0 990 274"
          className="w-full min-w-[760px]"
          role="img"
          aria-label="VoxGate case pipeline. Intake, then a voice interview that pauses for the applicant, then field validation, then sanctions, PEP and adverse media screening running in parallel, then risk scoring, then routing to auto approval, a re-ask, or a reviewer gate that pauses for a human decision."
        >
          <defs>
            {/*
              userSpaceOnUse is required, not cosmetic. Default objectBoundingBox
              units make a gradient fail to paint on any perfectly horizontal
              path, because such a path has a zero-height bounding box. Half the
              edges here are horizontal.
            */}
            <linearGradient id="edgeGradient" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="990" y2="0">
              <stop offset="0%" stopColor="#7debff" />
              <stop offset="52%" stopColor="#6c7dff" />
              <stop offset="100%" stopColor="#c87bff" />
            </linearGradient>
            <filter id="neonGlow" x="-70%" y="-70%" width="240%" height="240%">
              <feGaussianBlur stdDeviation="4" result="b" />
              <feMerge>
                <feMergeNode in="b" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
            <filter id="haloGlow" x="-80%" y="-80%" width="260%" height="260%">
              <feGaussianBlur stdDeviation="9" />
            </filter>
            {EDGES.map((e) => (
              <path key={`def-${e.id}`} id={`path-${e.id}`} d={e.d} />
            ))}
          </defs>

          {/* Edges. */}
          {EDGES.map((e) => {
            const done = visited.has(e.from) && visited.has(e.to);
            return (
              <use
                key={e.id}
                href={`#path-${e.id}`}
                fill="none"
                stroke="url(#edgeGradient)"
                strokeWidth={done ? 1.5 : 1.2}
                strokeLinecap="round"
                opacity={done ? 0.8 : 0.2}
                style={{ transition: "opacity 380ms ease" }}
              />
            );
          })}

          {/* Travelling dots. Always running, so the graph never looks parked. */}
          {!reduce &&
            EDGES.map((e, i) => {
              const done = visited.has(e.from) && visited.has(e.to);
              return (
                <circle key={`dot-${e.id}`} r={done ? 3.2 : 2} fill="#e8fbff" opacity={done ? 0.95 : 0.35}>
                  <animateMotion dur={`${2.4 + (i % 4) * 0.35}s`} repeatCount="indefinite" begin={`${i * 0.18}s`}>
                    <mpath href={`#path-${e.id}`} />
                  </animateMotion>
                </circle>
              );
            })}

          {NODES.map((node) => {
            const y = node.cy - H / 2;
            const isActive = activeSet.has(node.id);
            const isHover = hovered?.id === node.id;
            const isVisited = visited.has(node.id);
            const stroke = isActive ? ACCENT : toneColor(node.tone);
            const labelOffset = node.pause ? 14 : 0;

            return (
              <g
                key={node.id}
                onMouseEnter={() => setHovered(node)}
                onMouseLeave={() => setHovered(null)}
                onFocus={() => setHovered(node)}
                onBlur={() => setHovered(null)}
                tabIndex={0}
                role="button"
                aria-label={`${node.label}. ${node.role}`}
                style={{ cursor: "pointer", outline: "none" }}
              >
                {isActive || isHover ? (
                  <rect
                    x={node.x}
                    y={y}
                    width={node.w}
                    height={H}
                    rx={9}
                    fill={stroke}
                    opacity={isActive ? 0.42 : 0.22}
                    filter="url(#haloGlow)"
                  />
                ) : null}

                <rect
                  x={node.x}
                  y={y}
                  width={node.w}
                  height={H}
                  rx={9}
                  fill={isActive ? "rgba(198,242,78,0.10)" : "rgba(125,214,255,0.045)"}
                  stroke={stroke}
                  strokeOpacity={isActive ? 1 : isHover ? 0.9 : isVisited ? 0.55 : 0.26}
                  strokeWidth={isActive ? 1.7 : 1.1}
                  filter={isActive || isHover ? "url(#neonGlow)" : undefined}
                  style={{ transition: "stroke-opacity 300ms ease, fill 300ms ease" }}
                />

                {/* Expanding ring only while parked at an interrupt. */}
                {isActive && current.waiting && !reduce ? (
                  <circle cx={node.x + node.w / 2} cy={node.cy} r={4} fill="none" stroke={ACCENT} strokeWidth={1.3}>
                    <animate attributeName="r" from="8" to="52" dur="1.9s" repeatCount="indefinite" />
                    <animate attributeName="opacity" from="0.6" to="0" dur="1.9s" repeatCount="indefinite" />
                  </circle>
                ) : null}

                {node.pause ? (
                  <g transform={`translate(${node.x + 11}, ${node.cy - 5})`}>
                    <rect width={2} height={10} rx={1} fill="var(--color-status-awaiting-interview)" />
                    <rect x={4} width={2} height={10} rx={1} fill="var(--color-status-awaiting-interview)" />
                  </g>
                ) : null}

                <text
                  x={node.x + labelOffset + (node.w - labelOffset) / 2}
                  y={node.cy + 4}
                  textAnchor="middle"
                  fill={isActive ? ACCENT : isVisited ? "#eef1fa" : "#6b7290"}
                  style={{
                    fontSize: 11.5,
                    fontFamily: "var(--font-geist-mono), monospace",
                    transition: "fill 300ms ease",
                    pointerEvents: "none",
                  }}
                >
                  {node.label}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      {/* Narration. Hovering a node overrides the walk so a reader can stop and
          interrogate any step. aria-live keeps it available non-visually. */}
      <div className="mt-7 min-h-[46px]">
        <div className="flex items-start gap-3">
          <span
            aria-hidden="true"
            className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full"
            style={{
              background: detail
                ? "#7dd6ff"
                : current.waiting
                  ? "var(--color-status-awaiting-interview)"
                  : ACCENT,
            }}
          />
          <motion.p
            key={detail ? `hover-${detail.id}` : `walk-${current.caption}`}
            initial={reduce ? false : { opacity: 0, y: 3 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25 }}
            className="max-w-[76ch] text-[13.5px] leading-relaxed text-text-dim"
            aria-live="polite"
          >
            {detail ? (
              <>
                <span
                  className="text-text"
                  style={{ fontFamily: "var(--font-geist-mono), monospace" }}
                >
                  {detail.label}
                </span>
                {": "}
                {detail.role}
              </>
            ) : (
              current.caption
            )}
          </motion.p>
        </div>
      </div>

      <figcaption className="mt-4 flex flex-wrap items-center gap-x-8 gap-y-2 text-[12.5px] text-text-faint">
        <span className="flex items-center gap-2.5">
          <span className="inline-flex gap-[3px]" aria-hidden="true">
            <span className="block h-3 w-[2px] rounded-full bg-[var(--color-status-awaiting-interview)]" />
            <span className="block h-3 w-[2px] rounded-full bg-[var(--color-status-awaiting-interview)]" />
          </span>
          Pauses for a human. Survives a process restart.
        </span>
        <span>Hover any node. This is the compiled graph, not a simplification.</span>
      </figcaption>
    </figure>
  );
}
