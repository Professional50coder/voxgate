"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const SURFACES = [
  { href: "/dashboard", label: "Overview" },
  { href: "/agents", label: "Agent library" },
  { href: "/console", label: "Case queue" },
  { href: "/admin", label: "Admin" },
];

/** Chrome for the signed-in product surfaces. The marketing nav is separate. */
export function AppNav() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-50 h-16 glass border-x-0 border-t-0">
      <div className="mx-auto flex h-full max-w-[1200px] items-center justify-between px-6">
        <div className="flex items-center gap-8">
          <Link href="/" className="flex items-center gap-2.5">
            <span
              aria-hidden="true"
              className="h-5 w-5 rounded-full"
              style={{ background: "var(--siri-gradient)" }}
            />
            <span className="text-[15px] font-semibold tracking-tight">VoxGate</span>
          </Link>
          <nav>
            <ul className="flex items-center gap-1">
              {SURFACES.map((s) => {
                const active = pathname === s.href;
                return (
                  <li key={s.href}>
                    <Link
                      href={s.href}
                      aria-current={active ? "page" : undefined}
                      className={`rounded-[var(--r-pill)] px-3.5 py-1.5 text-[13.5px] transition-colors ${
                        active
                          ? "bg-[var(--color-glass)] text-text"
                          : "text-text-dim hover:text-text"
                      }`}
                    >
                      {s.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>
        </div>

        <div className="flex items-center gap-3">
          <Link
            href="/apply"
            className="hidden text-[13px] text-text-dim transition-colors hover:text-text sm:inline"
          >
            Applicant view
          </Link>
          <span
            className="grid h-8 w-8 place-items-center rounded-full text-[12px] font-semibold text-[#0a0a12]"
            style={{ background: "var(--siri-gradient)" }}
            title="Signed in as the demo tenant"
          >
            DT
          </span>
        </div>
      </div>
    </header>
  );
}
