"use client";

import { CheckCircle, Package, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";

import { AppNav } from "@/components/app-nav";
import { API_BASE, ApiUnreachable, NotAuthorized, type Case, type Pack, getPacks, listCases } from "@/lib/api";
import { OperatorKeyGate } from "@/components/operator-key-gate";

const MONO = { fontFamily: "var(--font-geist-mono), monospace" } as const;

/**
 * Platform administration. Tenancy is schema-ready but the auth boundary is
 * still stubbed, so this shows the single default tenant. It becomes a real
 * list once `current_tenant()` resolves an identity instead of a constant.
 * See docs/PRODUCT.md section 4.
 */
export default function Admin() {
  const [packs, setPacks] = useState<Pack[]>([]);
  const [cases, setCases] = useState<Case[]>([]);
  const [offline, setOffline] = useState(false);
  const [locked, setLocked] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([getPacks(), listCases()])
      .then(([p, c]) => {
        setPacks(p);
        setCases(c);
      })
      .catch((err) => {
        if (err instanceof ApiUnreachable) setOffline(true);
        else if (err instanceof NotAuthorized) setLocked(err.status);
      })
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="min-h-[100dvh]">
      <AppNav />
      <main className="mx-auto max-w-[1200px] px-6 py-10">
        <h1 className="text-2xl font-semibold tracking-tight">Administration</h1>
        <p className="mt-1.5 text-[14px] text-text-dim">
          Packs, tenants and platform health.
        </p>

        {loading ? (
          <div className="mt-8 h-40 animate-pulse rounded-[var(--r-card)] bg-[var(--color-surface-2)]" />
        ) : null}

        {locked !== null ? (
          <div className="py-10">
            <OperatorKeyGate
              status={locked}
              onSaved={() => {
                setLocked(null);
                // A full reload rather than re-running the fetch by hand: this
                // page loads several independent things at mount and there is
                // no single refresh to call.
                window.location.reload();
              }}
            />
          </div>
        ) : null}

        {!loading && locked === null ? (
          <>
            <section className="mt-8 grid gap-4 sm:grid-cols-3">
              <Health
                ok={!offline}
                label="API"
                value={offline ? "Unreachable" : "Healthy"}
                detail={API_BASE}
              />
              <Health ok={packs.length > 0} label="Packs loaded" value={String(packs.length)} />
              <Health ok label="Cases" value={String(cases.length)} detail="In the index" />
            </section>

            <section className="mt-6 rounded-[var(--r-card)] border border-glass-border-soft bg-[var(--color-surface-2)] p-7">
              <h2 className="text-[15px] font-semibold">Installed packs</h2>
              <p className="mt-2 max-w-[64ch] text-[13.5px] leading-relaxed text-text-dim">
                A pack is a directory on disk holding its own schema, checks, scoring model
                and question phrasings. Adding one requires no platform code, which is what
                the conformance suite enforces.
              </p>

              {packs.length === 0 ? (
                <p className="mt-6 text-[13.5px] text-text-dim">
                  No packs loaded. Check the packs directory.
                </p>
              ) : (
                <ul className="mt-6 space-y-4">
                  {packs.map((p) => (
                    <li
                      key={p.pack_id}
                      className="rounded-[var(--r-card)] border border-glass-border-soft p-5"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <span className="flex items-center gap-3">
                          <Package size={18} weight="duotone" color="var(--color-siri-2)" />
                          <span className="text-[14.5px] font-semibold" style={MONO}>
                            {p.pack_id}
                          </span>
                        </span>
                        <span className="text-[12.5px] text-text-faint">
                          gate: {p.gate_role}
                        </span>
                      </div>
                      <p className="mt-2.5 text-[13.5px] text-text-dim">{p.display_name}</p>
                      <ul className="mt-4 flex flex-wrap gap-2">
                        {p.fields.map((f) => (
                          <li
                            key={f}
                            className="rounded-[var(--r-pill)] border border-glass-border-soft px-2.5 py-1 text-[11.5px] text-text-dim"
                            style={MONO}
                          >
                            {f}
                          </li>
                        ))}
                      </ul>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="mt-6 rounded-[var(--r-card)] border border-glass-border-soft bg-[var(--color-surface-2)] p-7">
              <h2 className="text-[15px] font-semibold">Tenants</h2>
              <div className="mt-5 flex items-center justify-between rounded-[var(--r-card)] border border-glass-border-soft p-5">
                <div>
                  <p className="text-[14px] font-medium">Demo tenant</p>
                  <p className="mt-1 text-[12.5px] text-text-faint" style={MONO}>
                    default
                  </p>
                </div>
                <span className="text-[12.5px] text-text-dim">{cases.length} cases</span>
              </div>
              <p className="mt-5 rounded-[var(--r-input)] border border-[var(--color-status-awaiting-interview)]/30 px-4 py-3 text-[12.5px] leading-relaxed text-[var(--color-status-awaiting-interview)]">
                Authentication is not yet enforced. Every request currently resolves to this
                single tenant, and anyone who reaches the console can read every case. This
                is the blocking item before launch, tracked in docs/PRODUCT.md.
              </p>
            </section>
          </>
        ) : null}
      </main>
    </div>
  );
}

function Health({
  ok,
  label,
  value,
  detail,
}: {
  ok: boolean;
  label: string;
  value: string;
  detail?: string;
}) {
  return (
    <div className="rounded-[var(--r-card)] border border-glass-border-soft bg-[var(--color-surface-2)] p-6">
      <div className="flex items-center gap-2.5">
        {ok ? (
          <CheckCircle size={16} weight="fill" color="var(--color-risk-low)" />
        ) : (
          <WarningCircle size={16} weight="fill" color="var(--color-status-needs-attention)" />
        )}
        <span className="text-[12.5px] text-text-dim">{label}</span>
      </div>
      <p className="mt-3 text-[22px] font-semibold leading-none">{value}</p>
      {detail ? (
        <p className="mt-2 truncate text-[11.5px] text-text-faint" style={MONO}>
          {detail}
        </p>
      ) : null}
    </div>
  );
}
