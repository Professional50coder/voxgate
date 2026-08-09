"use client";

import { Key } from "@phosphor-icons/react";
import { useState } from "react";

import { setOperatorKey } from "@/lib/api";

/**
 * Shown when an operator page gets a 401 or 403.
 *
 * Rendered in place of the page's content rather than as a modal over it: the
 * data behind it did not load, so a dialog floating over an empty board implies
 * there is something underneath to go back to. There is not.
 *
 * It does not verify the key itself. Saving it and re-running the page's own
 * fetch is the verification — a separate "check this key" endpoint would be one
 * more surface to secure and could disagree with the real request.
 */
export function OperatorKeyGate({
  status,
  onSaved,
}: {
  /** 401: no key sent. 403: a key was sent and rejected. Different advice. */
  status: number;
  onSaved: () => void;
}) {
  const [value, setValue] = useState("");

  function save(e: React.FormEvent) {
    e.preventDefault();
    if (!value.trim()) return;
    setOperatorKey(value);
    setValue("");
    onSaved();
  }

  return (
    <div className="mx-auto w-full max-w-[440px] rounded-[var(--r-card)] border border-glass-border-soft bg-[var(--color-surface-2)] p-8">
      <span
        aria-hidden="true"
        className="inline-flex h-11 w-11 items-center justify-center rounded-[11px] border border-glass-border-soft"
        style={{ background: "rgba(255,255,255,0.04)" }}
      >
        <Key size={20} weight="duotone" color="var(--color-siri-2)" />
      </span>

      <h1 className="mt-6 text-[19px] font-semibold tracking-tight">
        {status === 403 ? "That key was not accepted" : "Operator key required"}
      </h1>
      <p className="mt-3 text-[14px] leading-relaxed text-text-dim">
        {status === 403
          ? "The key stored in this browser is not one this deployment recognises. It may have been rotated."
          : "The case board and reviewer decisions are restricted. The applicant interview is not, and needs no key."}
      </p>

      <form onSubmit={save} className="mt-7">
        <label htmlFor="operator-key" className="text-[12.5px] text-text-faint">
          Key
        </label>
        <input
          id="operator-key"
          type="password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          autoComplete="off"
          placeholder="VOXGATE_API_KEYS value"
          className="mt-2 w-full rounded-[var(--r-input)] border border-glass-border-soft bg-[#05070e] px-4 py-3 text-[14px] text-text outline-none transition-colors focus:border-[var(--color-siri-2)]"
        />
        <button
          type="submit"
          disabled={!value.trim()}
          className="mt-4 w-full rounded-[var(--r-pill)] px-6 py-3 text-[14.5px] font-semibold text-[#0a0a12] transition-transform active:scale-[0.98] disabled:opacity-40"
          style={{ background: "var(--siri-gradient)" }}
        >
          Unlock
        </button>
      </form>

      <p className="mt-6 text-[12px] leading-relaxed text-text-faint">
        Stored in this browser only, and sent as an <code>X-API-Key</code> header.
        If the server has no <code>VOXGATE_API_KEYS</code> set, nothing is restricted
        and you will not see this again.
      </p>
    </div>
  );
}
