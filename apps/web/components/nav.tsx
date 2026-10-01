import Link from "next/link";

const LINKS = [
  { href: "/#problem", label: "Why" },
  { href: "/how-it-works", label: "How it works" },
  { href: "/agents", label: "Agent library" },
  { href: "/#trust", label: "Compliance" },
];

export function Nav() {
  return (
    <header className="sticky top-0 z-50 h-16 glass border-x-0 border-t-0">
      <nav className="mx-auto flex h-full max-w-[1200px] items-center justify-between px-6">
        <Link href="/" className="flex items-center gap-2.5">
          <span
            aria-hidden="true"
            className="h-5 w-5 rounded-full"
            style={{ background: "var(--siri-gradient)" }}
          />
          <span className="text-[15px] font-semibold tracking-tight">VoxGate</span>
        </Link>

        <ul className="hidden items-center gap-8 md:flex">
          {LINKS.map((link) => (
            <li key={link.href}>
              <Link
                href={link.href}
                className="text-[13.5px] text-text-dim transition-colors hover:text-text"
              >
                {link.label}
              </Link>
            </li>
          ))}
        </ul>

        <div className="flex items-center gap-2.5">
          <Link
            href="/console"
            className="hidden rounded-[var(--r-pill)] border border-glass-border px-4 py-2 text-[13.5px] font-medium text-text transition-all hover:border-white/25 active:scale-[0.98] sm:inline-block"
          >
            Reviewer console
          </Link>
          <Link
            href="/apply"
            className="rounded-[var(--r-pill)] px-4 py-2 text-[13.5px] font-semibold text-[#0a0a12] transition-transform active:scale-[0.98]"
            style={{ background: "var(--siri-gradient)" }}
          >
            Try the interview
          </Link>
        </div>
      </nav>
    </header>
  );
}
