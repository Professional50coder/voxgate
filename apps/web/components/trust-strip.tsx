import {
  CreditCard, Database, FileText, Scales, ShieldCheck, UserCheck,
} from "@phosphor-icons/react/dist/ssr";

/**
 * Directly under the hero, where every serious competitor puts its proof.
 * Only claims the product can back today: no certification badge is shown
 * until it has actually been earned, because a compliance buyer checks.
 */
const ITEMS = [
  { icon: UserCheck, label: "A person makes every judgment call" },
  { icon: FileText, label: "Full audit trail on every case" },
  { icon: Scales, label: "Explainable, factor-by-factor risk score" },
  { icon: CreditCard, label: "Card numbers and PINs are refused, never recorded" },
  { icon: Database, label: "Self-host in your own cloud" },
  { icon: ShieldCheck, label: "Demo runs on synthetic data" },
];

export function TrustStrip() {
  return (
    <section aria-label="How VoxGate handles data and decisions" className="border-y border-glass-border-soft bg-[var(--color-bg-1)]/60">
      <ul className="mx-auto grid max-w-[1200px] grid-cols-1 gap-x-6 gap-y-3 px-6 py-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        {ITEMS.map(({ icon: Icon, label }) => (
          <li key={label} className="flex items-center gap-2.5 text-[12.5px] leading-snug text-text-dim">
            <Icon size={18} weight="duotone" className="shrink-0 text-[var(--color-siri-1)]" />
            {label}
          </li>
        ))}
      </ul>
    </section>
  );
}
