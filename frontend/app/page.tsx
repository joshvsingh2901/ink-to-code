import Link from "next/link";
import { Inter_Tight, JetBrains_Mono } from "next/font/google";
import HeroTransformation from "@/components/HeroTransformation";
import WorkspaceShowcase from "@/components/landing/WorkspaceShowcase";

/**
 * Marketing landing page. Visual/layout source of truth: the Claude
 * Design project "InkToCode landing page" ("InkToCode Landing v2.dc.html").
 * Uses its own inline-styled visual identity (distinct from the app's
 * design-token system used on /upload, /review, /editor), scoped under
 * the itc-landing class in globals.css.
 *
 * The hero's animation slot mounts the existing HeroTransformation
 * component verbatim — not recreated from the design file.
 */

const interTight = Inter_Tight({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});
const jetBrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
});

const GITHUB_URL = "https://github.com/joshvsingh2901/ink-to-code";
const MONO = jetBrainsMono.style.fontFamily + ", monospace";
const ACCENT = "#5b7cfa";

const BENEFITS = [
  {
    n: "01",
    title: "Handwriting → editable C++",
    body: "Low-confidence characters are flagged inline. You approve the code before it builds.",
  },
  {
    n: "02",
    title: "Real compiler, deterministic tests",
    body: "g++ with C++17 and sanitizers. Same file, same verdict, every run.",
  },
  {
    n: "03",
    title: "AI-drafted edge cases",
    body: "Cases proposed from the assignment text. Execution and scoring stay deterministic.",
  },
];

function PrimaryCta() {
  return (
    <Link
      href="/upload"
      className="itc-btn-primary"
      style={{
        fontSize: 14.5,
        fontWeight: 500,
        color: "#fff",
        background: ACCENT,
        borderRadius: 6,
        padding: "11px 20px",
      }}
    >
      Try InkToCode
    </Link>
  );
}

function SecondaryCta() {
  return (
    <a
      href={GITHUB_URL}
      target="_blank"
      rel="noopener noreferrer"
      className="itc-btn-secondary"
      style={{
        fontSize: 14.5,
        color: "#d3d8df",
        border: "1px solid #22262e",
        borderRadius: 6,
        padding: "11px 18px",
      }}
    >
      GitHub
    </a>
  );
}

export default function LandingPage() {
  return (
    <div
      className={`itc-landing ${interTight.className}`}
      style={{
        background: "#08090b",
        color: "#e6e8ec",
        fontFamily: "'Inter', 'Helvetica Neue', Arial, sans-serif",
        fontSize: 16,
        lineHeight: 1.5,
        WebkitFontSmoothing: "antialiased",
        minWidth: 1280,
      }}
    >
      {/* Nav */}
      <div
        style={{
          position: "sticky",
          top: 0,
          zIndex: 50,
          background: "rgba(8,9,11,0.86)",
          backdropFilter: "blur(8px)",
          borderBottom: "1px solid #14171d",
        }}
      >
        <div style={{ maxWidth: 1160, margin: "0 auto", padding: "0 32px", height: 56, display: "flex", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
            <div style={{ width: 16, height: 16, border: `1px solid ${ACCENT}`, borderRadius: 3, position: "relative", flex: "none" }}>
              <div style={{ position: "absolute", left: 3, top: 3, width: 8, height: 8, background: ACCENT, borderRadius: 1 }} />
            </div>
            <span style={{ fontSize: 14.5, fontWeight: 600, letterSpacing: "-0.01em" }}>InkToCode</span>
          </div>
          <div style={{ flex: 1 }} />
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <a
              href={GITHUB_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="itc-link-github"
              style={{ fontSize: 13.5, color: "#c3c9d2", padding: "6px 4px" }}
            >
              GitHub
            </a>
            <PrimaryCta />
          </div>
        </div>
      </div>

      {/* 1. Hero */}
      <div style={{ position: "relative", overflow: "hidden" }}>
        <div
          aria-hidden="true"
          style={{
            position: "absolute",
            inset: 0,
            pointerEvents: "none",
            backgroundImage:
              "linear-gradient(to right,#ffffff 1px,transparent 1px),linear-gradient(to bottom,#ffffff 1px,transparent 1px)",
            backgroundSize: "72px 72px",
            backgroundPosition: "center top",
            opacity: 0.035,
            WebkitMaskImage:
              "radial-gradient(ellipse 78% 62% at 50% 34%,#000 0%,rgba(0,0,0,0.55) 55%,transparent 100%)",
            maskImage:
              "radial-gradient(ellipse 78% 62% at 50% 34%,#000 0%,rgba(0,0,0,0.55) 55%,transparent 100%)",
          }}
        />
        <div
          aria-hidden="true"
          style={{
            position: "absolute",
            inset: 0,
            pointerEvents: "none",
            background: "radial-gradient(ellipse 60% 46% at 50% 30%,rgba(91,124,250,0.085),transparent 70%)",
          }}
        />

        <div style={{ position: "relative", maxWidth: 1160, margin: "0 auto", padding: "88px 32px 0", textAlign: "center" }}>
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 9,
              fontFamily: MONO,
              fontSize: 11,
              letterSpacing: "0.16em",
              textTransform: "uppercase",
              color: "#6f7784",
            }}
          >
            <span style={{ width: 5, height: 5, borderRadius: "50%", background: ACCENT, flex: "none" }} />
            <span>
              Handwritten <span style={{ color: "#3f4650" }}>→</span> Compiled{" "}
              <span style={{ color: "#3f4650" }}>→</span> Tested
            </span>
          </div>
          <h1
            style={{
              margin: "22px 0 0",
              fontSize: 74,
              lineHeight: 1.0,
              letterSpacing: "-0.042em",
              fontWeight: 600,
              color: "#b9c0cb",
              textWrap: "balance",
            }}
          >
            From handwritten C++
            <br />
            <span style={{ color: "#f4f6fa" }}>to tested code.</span>
          </h1>
          <p
            style={{
              margin: "22px auto 0",
              fontSize: 17.5,
              lineHeight: 1.55,
              color: "#8f97a3",
              maxWidth: 520,
              textWrap: "pretty",
              fontFamily: "'Inter', 'Helvetica Neue', Arial, sans-serif",
              fontWeight: 400,
            }}
          >
            Turn what you wrote on paper into editable C++, compile it, and see what actually breaks.
          </p>
          <div style={{ display: "flex", gap: 10, justifyContent: "center", marginTop: 26 }}>
            <PrimaryCta />
            <SecondaryCta />
          </div>
        </div>

        {/* Hero animation slot — mounts the existing HeroTransformation
            component verbatim; not recreated from the design file. */}
        <div style={{ position: "relative", maxWidth: 1160, margin: "44px auto 0", padding: "0 32px" }}>
          <div
            style={{
              position: "relative",
              border: "1px solid #1e222a",
              borderRadius: 10,
              background: "#0a0c0f",
              overflow: "hidden",
              display: "flex",
              justifyContent: "center",
              padding: "36px 0",
            }}
          >
            <HeroTransformation />
          </div>
        </div>
      </div>

      {/* 2. Workspace showcase */}
      <div style={{ maxWidth: 1280, margin: "0 auto", padding: "120px 32px 0" }}>
        <div style={{ maxWidth: 640, margin: "0 auto 34px", textAlign: "center" }}>
          <h2 style={{ margin: 0, fontSize: 30, lineHeight: 1.18, letterSpacing: "-0.028em", fontWeight: 600 }}>
            A real workspace, not a transcript.
          </h2>
          <p
            style={{
              margin: "14px 0 0",
              fontSize: 15.5,
              color: "#8b929d",
              fontFamily: "'Inter', 'Helvetica Neue', Arial, sans-serif",
              fontWeight: 400,
            }}
          >
            Editor on the left, compiler and tests on the right. Failures first.
          </p>
        </div>

        <WorkspaceShowcase />
      </div>

      {/* 3. Three benefits */}
      <div style={{ maxWidth: 1160, margin: "120px auto 0", padding: "0 32px" }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(3,minmax(0,1fr))",
            gap: 1,
            background: "#16191f",
            border: "1px solid #16191f",
            borderRadius: 8,
            overflow: "hidden",
          }}
        >
          {BENEFITS.map((benefit) => (
            <div key={benefit.n} style={{ background: "#0a0c0f", padding: "26px 24px 28px" }}>
              <div style={{ fontFamily: MONO, fontSize: 11, color: ACCENT, letterSpacing: "0.05em", marginBottom: 14 }}>
                {benefit.n}
              </div>
              <div style={{ fontSize: 15, fontWeight: 500, marginBottom: 7 }}>{benefit.title}</div>
              <div
                style={{
                  fontSize: 13.5,
                  color: "#7f8794",
                  lineHeight: 1.6,
                  fontFamily: "'Inter', 'Helvetica Neue', Arial, sans-serif",
                  fontWeight: 400,
                }}
              >
                {benefit.body}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 4. Final CTA */}
      <div style={{ maxWidth: 1160, margin: "0 auto", padding: "120px 32px 128px", textAlign: "center" }}>
        <h2
          style={{
            margin: "0 auto",
            fontSize: 38,
            lineHeight: 1.12,
            letterSpacing: "-0.03em",
            fontWeight: 600,
            maxWidth: 620,
            textWrap: "balance",
          }}
        >
          Test the solution you wrote on paper.
        </h2>
        <div style={{ display: "flex", gap: 10, justifyContent: "center", marginTop: 28 }}>
          <PrimaryCta />
          <SecondaryCta />
        </div>
      </div>

      {/* Footer */}
      <div style={{ borderTop: "1px solid #14171d" }}>
        <div style={{ maxWidth: 1160, margin: "0 auto", padding: "20px 32px", display: "flex", alignItems: "center", gap: 20, fontSize: 13, color: "#5f6672" }}>
          <span>InkToCode</span>
          <span style={{ color: "#22262e" }}>·</span>
          <span style={{ fontFamily: MONO, fontSize: 11.5 }}>From handwritten C++ to tested code</span>
          <div style={{ flex: 1 }} />
          <a href={`${GITHUB_URL}#readme`} target="_blank" rel="noopener noreferrer" className="itc-footer-link" style={{ color: "#7f8794" }}>
            Docs
          </a>
          <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer" className="itc-footer-link" style={{ color: "#7f8794" }}>
            GitHub
          </a>
        </div>
      </div>
    </div>
  );
}
