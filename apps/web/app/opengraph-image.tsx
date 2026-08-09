import { ImageResponse } from "next/og";

export const runtime = "edge";
export const alt = "VoxGate: automate compliance intake with voice agents";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

/**
 * Social card, generated at build time rather than shipped as a static asset,
 * so it stays in sync with the brand tokens and never goes stale.
 */
export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          padding: "0 96px",
          background:
            "radial-gradient(900px 520px at 50% 30%, #4A1D69 0%, #2A123C 38%, #18071F 66%, #09030C 100%)",
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
          <div
            style={{
              width: 40,
              height: 40,
              borderRadius: 999,
              background: "linear-gradient(120deg, #7DEBFF, #6C7DFF 52%, #C87BFF)",
            }}
          />
          <div style={{ fontSize: 30, color: "#EEF1FA", fontWeight: 600 }}>VoxGate</div>
        </div>

        <div
          style={{
            marginTop: 40,
            fontSize: 68,
            lineHeight: 1.08,
            fontWeight: 700,
            color: "#FFFFFF",
            maxWidth: 900,
          }}
        >
          Automate compliance intake with voice agents
        </div>

        <div
          style={{
            marginTop: 28,
            fontSize: 28,
            lineHeight: 1.4,
            color: "#B7B7C2",
            maxWidth: 820,
          }}
        >
          Applicants answer out loud. Every answer is screened. Reviewers get a decision
          that already explains itself.
        </div>

        <div style={{ marginTop: 44, display: "flex", gap: 14 }}>
          {["Durable", "Explainable", "Pack-driven"].map((tag) => (
            <div
              key={tag}
              style={{
                fontSize: 22,
                color: "#B7B7C2",
                border: "1px solid rgba(255,255,255,0.16)",
                borderRadius: 999,
                padding: "8px 22px",
              }}
            >
              {tag}
            </div>
          ))}
        </div>
      </div>
    ),
    size,
  );
}
