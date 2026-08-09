import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

// next/font self-hosts at build time, so there is no runtime CDN fetch.
const geist = Geist({ variable: "--font-geist", subsets: ["latin"], display: "swap" });
const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
  display: "swap",
});

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://voxgate.app";
const TITLE = "VoxGate: Automate compliance intake with voice agents";
const DESCRIPTION =
  "VoxGate runs structured intake interviews by voice, screens every answer against sanctions, PEP and adverse media lists, and routes each case to auto-approval or a human reviewer with the evidence already assembled.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: TITLE,
    // Sub-pages set their own title and inherit the brand suffix.
    template: "%s | VoxGate",
  },
  description: DESCRIPTION,
  applicationName: "VoxGate",
  authors: [{ name: "VoxGate" }],
  generator: "Next.js",
  keywords: [
    "voice agent",
    "compliance automation",
    "KYC onboarding",
    "AML screening",
    "sanctions screening",
    "PEP screening",
    "adverse media screening",
    "customer onboarding software",
    "identity verification",
    "conversational AI",
    "human in the loop",
    "durable workflow",
    "LangGraph",
    "risk scorecard",
    "explainable AI",
    "regtech",
  ],
  category: "technology",
  referrer: "origin-when-cross-origin",
  alternates: {
    canonical: "/",
  },
  openGraph: {
    type: "website",
    siteName: "VoxGate",
    title: TITLE,
    description: DESCRIPTION,
    url: SITE_URL,
    locale: "en_US",
    images: [
      {
        url: "/opengraph-image",
        width: 1200,
        height: 630,
        alt: "VoxGate: automate compliance intake with voice agents",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: TITLE,
    description: DESCRIPTION,
    images: ["/opengraph-image"],
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      "max-image-preview": "large",
      "max-snippet": -1,
      "max-video-preview": -1,
    },
  },
  formatDetection: { telephone: false, address: false, email: false },
};

export const viewport: Viewport = {
  themeColor: "#09030C",
  colorScheme: "dark",
  width: "device-width",
  initialScale: 1,
};

/**
 * Structured data. SoftwareApplication is the accurate type here, and the FAQ
 * block mirrors questions the page genuinely answers rather than invented ones,
 * which is what keeps it inside Google's structured-data guidelines.
 */
const JSON_LD = {
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "Organization",
      "@id": `${SITE_URL}/#organization`,
      name: "VoxGate",
      url: SITE_URL,
      description: DESCRIPTION,
    },
    {
      "@type": "WebSite",
      "@id": `${SITE_URL}/#website`,
      url: SITE_URL,
      name: "VoxGate",
      description: DESCRIPTION,
      publisher: { "@id": `${SITE_URL}/#organization` },
      inLanguage: "en-US",
    },
    {
      "@type": "SoftwareApplication",
      "@id": `${SITE_URL}/#software`,
      name: "VoxGate",
      applicationCategory: "BusinessApplication",
      applicationSubCategory: "Compliance and onboarding automation",
      operatingSystem: "Web",
      description: DESCRIPTION,
      featureList: [
        "Voice-driven structured intake interviews",
        "Sanctions, PEP and adverse media screening",
        "Explainable additive risk scorecards",
        "Durable human-in-the-loop review gates",
        "Pluggable scenario packs per use case",
      ],
      publisher: { "@id": `${SITE_URL}/#organization` },
    },
    {
      "@type": "FAQPage",
      "@id": `${SITE_URL}/#faq`,
      mainEntity: [
        {
          "@type": "Question",
          name: "How does VoxGate collect applicant information?",
          acceptedAnswer: {
            "@type": "Answer",
            text: "A voice agent asks each question defined by the scenario pack and the applicant answers out loud. Answers are validated against the pack schema, and anything unclear is re-asked, capped at two attempts before the case escalates.",
          },
        },
        {
          "@type": "Question",
          name: "Does a human still make the decision?",
          acceptedAnswer: {
            "@type": "Answer",
            text: "Yes, wherever judgment is required. Low-risk cases with no screening hits are approved automatically. Anything high risk, or with a sanctions, PEP or adverse media hit, routes to a reviewer gate where a compliance officer decides with the evidence already assembled.",
          },
        },
        {
          "@type": "Question",
          name: "Can VoxGate be used outside financial compliance?",
          acceptedAnswer: {
            "@type": "Answer",
            text: "Yes. Each use case is a self-contained pack holding its own schema, checks, scoring model and question phrasings. Adding one requires no platform code, so the same engine covers insurance first notice of loss, loan origination, patient intake, tenant screening and benefits enrollment.",
          },
        },
        {
          "@type": "Question",
          name: "Is the risk score explainable?",
          acceptedAnswer: {
            "@type": "Answer",
            text: "The scorecard is additive, so every feature's contribution to the final probability is attributable and can be shown to an auditor or regulator alongside the decision.",
          },
        },
      ],
    },
  ],
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body
        className={`${geist.variable} ${geistMono.variable} antialiased bg-bg text-text`}
        style={{ fontFamily: "var(--font-geist), system-ui, sans-serif" }}
      >
        <script
          type="application/ld+json"
          // Static object built at module scope, never user input.
          dangerouslySetInnerHTML={{ __html: JSON.stringify(JSON_LD) }}
        />
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[100] focus:rounded-[var(--r-pill)] focus:bg-white focus:px-5 focus:py-2.5 focus:text-[14px] focus:font-semibold focus:text-black"
        >
          Skip to content
        </a>
        <div className="aurora" aria-hidden="true" />
        <div className="grain" aria-hidden="true" />
        <div className="relative z-10">{children}</div>
      </body>
    </html>
  );
}
