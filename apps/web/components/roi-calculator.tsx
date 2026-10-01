"use client";

import { useState } from "react";

/**
 * Savings from the visitor's own numbers, not ours. Every assumption is an
 * input they can see and change, which is the only honest way to show ROI
 * before there are customer case studies to quote.
 */
const FIELDS = [
  { key: "interviews", label: "Interviews per month", min: 10, max: 20000, step: 10, suffix: "" },
  { key: "minutes", label: "Minutes per interview today", min: 3, max: 90, step: 1, suffix: " min" },
  { key: "cost", label: "Staff cost per hour", min: 5, max: 200, step: 1, suffix: "", prefix: "$" },
  { key: "flagged", label: "Cases a person still reviews", min: 0, max: 100, step: 5, suffix: "%" },
] as const;

type Key = (typeof FIELDS)[number]["key"];

// A flagged case still takes a reviewer this long, with the evidence laid out.
const REVIEW_MINUTES = 5;

export function RoiCalculator() {
  const [v, setV] = useState<Record<Key, number>>({ interviews: 500, minutes: 20, cost: 35, flagged: 25 });

  const manualHours = (v.interviews * v.minutes) / 60;
  const reviewHours = (v.interviews * (v.flagged / 100) * REVIEW_MINUTES) / 60;
  const savedHours = Math.max(0, manualHours - reviewHours);
  const savedMoney = savedHours * v.cost;
  const fmt = (n: number) => Math.round(n).toLocaleString();

  return (
    <div className="glass grid gap-8 rounded-[var(--r-card)] p-6 md:grid-cols-2 md:p-8">
      <div className="space-y-5">
        {FIELDS.map((f) => (
          <label key={f.key} className="block">
            <span className="flex justify-between text-[13.5px]">
              <span className="text-text-dim">{f.label}</span>
              <span className="font-semibold">{"prefix" in f ? f.prefix : ""}{fmt(v[f.key])}{f.suffix}</span>
            </span>
            <input type="range" min={f.min} max={f.max} step={f.step} value={v[f.key]}
              onChange={(e) => setV((s) => ({ ...s, [f.key]: Number(e.target.value) }))}
              className="mt-2 w-full accent-[var(--color-siri-2)]" />
          </label>
        ))}
      </div>
      <div className="flex flex-col justify-center rounded-[12px] bg-[var(--color-surface-2)] p-6">
        <p className="text-[13px] text-text-dim">Staff time saved each month</p>
        <p className="mt-1 text-4xl font-semibold tracking-tight">{fmt(savedHours)} hours</p>
        <p className="mt-5 text-[13px] text-text-dim">Worth about</p>
        <p className="gradient-text mt-1 text-4xl font-semibold tracking-tight">${fmt(savedMoney)}<span className="text-xl"> / month</span></p>
        <p className="mt-6 text-[12px] leading-relaxed text-text-faint">
          Today: {fmt(manualHours)} hours of interviews. With VoxGate: {fmt(reviewHours)} hours reviewing the
          {" "}{v.flagged}% of cases that need a person, at about {REVIEW_MINUTES} minutes each. Your numbers,
          your assumptions.
        </p>
      </div>
    </div>
  );
}
