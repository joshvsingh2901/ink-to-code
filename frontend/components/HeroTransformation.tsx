"use client";

import { useEffect, useState } from "react";
import { motion, useReducedMotion, type Easing } from "motion/react";
import { Caveat } from "next/font/google";

// Self-hosted at build time via next/font (same mechanism layout.tsx uses
// for Inter/JetBrains Mono) — no runtime external font request. Used only
// for the handwritten-paper phase; the typed-code/editor phase keeps the
// product's own --font-mono.
const handwritingFont = Caveat({ subsets: ["latin"], weight: ["600", "700"] });

/**
 * Isolated prototype of the InkToCode hero animation: handwritten C++ on
 * paper -> the same paper becoming the editor workspace -> typed code ->
 * a testing pane with results. Every element animates on a single shared
 * timeline anchored to mount time, so the sequence is deterministic and
 * reproducible (no scroll triggers, no randomness).
 *
 * Mounted on /animation-demo and in the landing page's hero slot — not
 * wired into the actual product workflow (upload/review/editor).
 */

const TOTAL_DURATION = 6; // seconds; sequence completes and holds by 5.3s

function frac(seconds: number) {
  return seconds / TOTAL_DURATION;
}

// ---------------------------------------------------------------------------
// Paper -> editor pane transform
//
// The card is always laid out at its final (editor) size and position; the
// "paper" look is produced entirely by animating transform (x/y/rotate/
// scale) around a top-left origin, plus a color/radius crossfade. Driving
// this via transform rather than width/height/left/top keeps it on the
// compositor thread — smooth regardless of main-thread load.
// ---------------------------------------------------------------------------

const EDITOR_POSE = { width: 540, height: 440, left: 20, top: 20, borderRadius: 10 };
const PAPER_VISUAL = { width: 300, height: 400, left: 130, top: 30, rotate: -3, borderRadius: 4 };

// Warm ivory paper tones (paper phase only — the editor's final dark
// surface/border colors below are the product's own tokens, unchanged).
const PAPER_FILL = "#f7efdc";
const PAPER_BORDER = "#ddceac";
const EDITOR_FILL = "#0d1117";
const EDITOR_BORDER = "#1b202b";

// Fine paper grain: a static, self-contained SVG fractal-noise tile (no
// image asset, no network request) layered under the handwriting at low
// opacity. Fades out with the rest of the paper — the editor pane stays
// perfectly flat, matching the real product surface.
const PAPER_GRAIN_URL =
  "data:image/svg+xml;utf8," +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="180" height="180">' +
      '<filter id="n"><feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2" stitchTiles="stitch"/>' +
      '<feColorMatrix type="saturate" values="0"/></filter>' +
      '<rect width="100%" height="100%" filter="url(#n)"/></svg>',
  );

const PAPER_SCALE_X = PAPER_VISUAL.width / EDITOR_POSE.width;
const PAPER_SCALE_Y = PAPER_VISUAL.height / EDITOR_POSE.height;
const PAPER_TRANSLATE_X = PAPER_VISUAL.left - EDITOR_POSE.left;
const PAPER_TRANSLATE_Y = PAPER_VISUAL.top - EDITOR_POSE.top;

const PAPER_TIMES = [0, frac(3.0), frac(3.8), 1];
const PAPER_TRANSFORM_X = [PAPER_TRANSLATE_X, PAPER_TRANSLATE_X, 0, 0];
const PAPER_TRANSFORM_Y = [PAPER_TRANSLATE_Y, PAPER_TRANSLATE_Y, 0, 0];
const PAPER_ROTATE = [PAPER_VISUAL.rotate, PAPER_VISUAL.rotate, 0, 0];
const PAPER_SCALE_X_KF = [PAPER_SCALE_X, PAPER_SCALE_X, 1, 1];
const PAPER_SCALE_Y_KF = [PAPER_SCALE_Y, PAPER_SCALE_Y, 1, 1];
const PAPER_BORDER_RADIUS = [
  PAPER_VISUAL.borderRadius,
  PAPER_VISUAL.borderRadius,
  EDITOR_POSE.borderRadius,
  EDITOR_POSE.borderRadius,
];

// ---------------------------------------------------------------------------
// Hand + pen (paper-local coordinates)
// ---------------------------------------------------------------------------

const HAND_TIMES = [
  0,
  frac(0.5),
  frac(1.0),
  frac(1.15),
  frac(1.5),
  frac(1.65),
  frac(2.0),
  frac(2.3),
  1,
].map((t) => Math.min(t, 1));

const HAND_X = [260, 30, 210, 30, 200, 30, 180, 280, 280];
const HAND_Y = [300, 85, 90, 135, 140, 185, 190, 260, 260];
const HAND_OPACITY = [0, 1, 1, 1, 1, 1, 1, 0, 0];
// Per-segment eases (one per gap between consecutive HAND_TIMES entries).
// Each segment's curve is independent, so — unlike a single ease applied
// across the whole duration — this can't shift when later keyframes fire;
// it only smooths the feel of the entrance, each writing/jump segment, and
// the exit.
const HAND_EASE: Easing[] = [
  "easeOut", // entrance
  "easeInOut", // writing line 1
  "easeInOut", // jump to line 2
  "easeInOut", // writing line 2
  "easeInOut", // jump to line 3
  "easeInOut", // writing line 3
  "easeIn", // exit
  "linear", // held hidden
];

const LINE_TIMES = [
  [0, frac(0.5), frac(1.0), 1],
  [0, frac(1.15), frac(1.5), 1],
  [0, frac(1.65), frac(2.0), 1],
];
const LINE_CLIP = [
  "inset(0 100% 0 0)",
  "inset(0 100% 0 0)",
  "inset(0 0% 0 0)",
  "inset(0 0% 0 0)",
];

const HANDWRITING_LINES = [
  "int findMax(int a, int b)",
  "if (a > b)",
  "return a;",
];

// ---------------------------------------------------------------------------
// Scan line
// ---------------------------------------------------------------------------

const SCAN_TIMES = [0, frac(2.3), frac(2.4), frac(2.9), frac(3.0), 1];
const SCAN_OPACITY = [0, 0, 1, 1, 0, 0];
const SCAN_TOP = ["0%", "0%", "4%", "94%", "100%", "100%"];

// ---------------------------------------------------------------------------
// Handwriting fade-out / typed code fade-in
// ---------------------------------------------------------------------------

const CODE_SWAP_TIMES = [0, frac(3.4), frac(4.0), 1];
const HANDWRITING_OPACITY = [1, 1, 0, 0];
const TYPED_OPACITY = [0, 0, 1, 1];

// ---------------------------------------------------------------------------
// Testing pane
// ---------------------------------------------------------------------------

const PANE_TIMES = [0, frac(4.0), frac(4.7), 1];
const PANE_OPACITY = [0, 0, 1, 1];
const PANE_X = [16, 16, 0, 0];

const RESULTS = [
  { label: "findMax(3, 7) == 7", verdict: "PASS" as const, delay: 4.4 },
  { label: "findMax(9, 2) == 9", verdict: "PASS" as const, delay: 4.7 },
  { label: "findMax(4, 4) == 4", verdict: "FAIL" as const, delay: 5.0 },
];

// Tip (ink point) sits at local (0,0); the whole pen is drawn pointing
// straight up from there, then rotated/translated into place as one group.
// The wrapper's negative left/top offset below cancels that translate so
// the rendered ink point — not the icon's bounding box — lands exactly on
// the HAND_X/HAND_Y target coordinates.
const PEN_TIP_LOCAL = { x: 18, y: 90 };
const PEN_ROTATE_DEG = 34;
const PEN_ICON_SIZE = 112;
const PEN_SCALE = PEN_ICON_SIZE / 100;
const PEN_OFFSET_LEFT = -(PEN_TIP_LOCAL.x * PEN_SCALE);
const PEN_OFFSET_TOP = -(PEN_TIP_LOCAL.y * PEN_SCALE);

function FountainPenIcon() {
  return (
    <svg
      viewBox="0 0 100 100"
      width={PEN_ICON_SIZE}
      height={PEN_ICON_SIZE}
      aria-hidden="true"
      style={{
        position: "absolute",
        left: PEN_OFFSET_LEFT,
        top: PEN_OFFSET_TOP,
        pointerEvents: "none",
      }}
    >
      <g transform={`translate(${PEN_TIP_LOCAL.x} ${PEN_TIP_LOCAL.y}) rotate(${PEN_ROTATE_DEG})`}>
        {/* Barrel */}
        <rect x="-5" y="-62" width="10" height="38" rx="5" fill="#1c1e24" />
        <line x1="-2" y1="-58" x2="-2" y2="-27" stroke="#4a4d57" strokeWidth="1.4" strokeLinecap="round" opacity={0.6} />
        {/* Grip section */}
        <rect x="-4.5" y="-25" width="9" height="7" rx="2" fill="#2a2d35" />
        {/* Gold trim band */}
        <rect x="-5" y="-24.5" width="10" height="3" rx="1" fill="#c9a24b" />
        {/* Nib */}
        <path d="M0 0 L-5.5 -14 Q0 -17 5.5 -14 Z" fill="#c9a24b" stroke="#8a6b2e" strokeWidth="0.6" />
        <line x1="0" y1="-3" x2="0" y2="-13" stroke="#8a6b2e" strokeWidth="0.8" />
        <circle cx="0" cy="-14.5" r="1.5" fill="#1c1e24" />
      </g>
    </svg>
  );
}

export default function HeroTransformation() {
  // useReducedMotion() resolves synchronously from the real matchMedia
  // value during the client's hydration render, while SSR always sees
  // `null` (no window) — branching on it directly causes a genuine
  // server/client hydration mismatch for anyone with reduced-motion
  // enabled. Instead: render the same (animated) branch as SSR on first
  // paint always, and only flip to the static branch after mount, once
  // an effect (not the render itself) has observed the real preference.
  const shouldReduceMotion = useReducedMotion();
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    // Syncing from the external matchMedia-derived value once it's known
    // post-mount — the same hydration-safe pattern used for restoring
    // the persisted rail width in app/editor/page.tsx.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (shouldReduceMotion) setReduced(true);
  }, [shouldReduceMotion]);

  if (reduced) {
    return (
      <div
        style={{
          position: "relative",
          width: 880,
          height: 500,
          maxWidth: "100%",
          margin: "0 auto",
        }}
      >
        <div
          style={{
            position: "absolute",
            width: EDITOR_POSE.width,
            height: EDITOR_POSE.height,
            left: EDITOR_POSE.left,
            top: EDITOR_POSE.top,
            borderRadius: EDITOR_POSE.borderRadius,
            background: "var(--surface-code)",
            border: "1px solid var(--border-subtle)",
            overflow: "hidden",
            padding: 20,
            boxSizing: "border-box",
          }}
        >
          <TypedCode style={{ opacity: 1 }} />
        </div>
        <div
          style={{
            position: "absolute",
            left: 580,
            top: 20,
            width: 280,
            height: 440,
            background: "var(--surface-raised)",
            border: "1px solid var(--border-subtle)",
            borderRadius: 10,
            padding: 16,
            boxSizing: "border-box",
            opacity: 1,
          }}
        >
          <TestingPaneContents allShown />
        </div>
      </div>
    );
  }

  return (
    <div
      style={{
        position: "relative",
        width: 880,
        height: 500,
        maxWidth: "100%",
        margin: "0 auto",
      }}
    >
      {/* Paper -> editor pane. Outer slot is static (defines the final
          layout box and clips overflow); the inner card animates purely
          via transform + color, so it stays compositor-driven. */}
      <div
        style={{
          position: "absolute",
          width: EDITOR_POSE.width,
          height: EDITOR_POSE.height,
          left: EDITOR_POSE.left,
          top: EDITOR_POSE.top,
          overflow: "hidden",
          borderRadius: EDITOR_POSE.borderRadius,
        }}
      >
        <motion.div
          initial={{
            x: PAPER_TRANSFORM_X[0],
            y: PAPER_TRANSFORM_Y[0],
            rotate: PAPER_ROTATE[0],
            scaleX: PAPER_SCALE_X_KF[0],
            scaleY: PAPER_SCALE_Y_KF[0],
            borderRadius: PAPER_BORDER_RADIUS[0],
            backgroundColor: PAPER_FILL,
            borderColor: PAPER_BORDER,
          }}
          animate={{
            x: PAPER_TRANSFORM_X,
            y: PAPER_TRANSFORM_Y,
            rotate: PAPER_ROTATE,
            scaleX: PAPER_SCALE_X_KF,
            scaleY: PAPER_SCALE_Y_KF,
            borderRadius: PAPER_BORDER_RADIUS,
            backgroundColor: [PAPER_FILL, PAPER_FILL, EDITOR_FILL, EDITOR_FILL],
            borderColor: [PAPER_BORDER, PAPER_BORDER, EDITOR_BORDER, EDITOR_BORDER],
          }}
          transition={{
            duration: TOTAL_DURATION,
            times: PAPER_TIMES,
            // Per-segment eases: linear through the two held (unchanging)
            // segments so they don't visually drift, easeInOut through the
            // middle segment where the transform actually happens. Without
            // per-segment eases, Motion applies one easing curve across the
            // whole duration, which shifts later keyframes' effective
            // start time — see the identical fix on the elements below.
            ease: ["linear", "easeInOut", "linear"],
          }}
          style={{
            position: "absolute",
            width: EDITOR_POSE.width,
            height: EDITOR_POSE.height,
            transformOrigin: "0 0",
            border: `1px solid ${PAPER_BORDER}`,
            // Constant across both phases (as before this refinement) —
            // just a richer, more layered shadow than the flat single-layer
            // one it replaces. No inset/rim-light here: that would also
            // show on the finished editor pane, which must keep matching
            // the real product's plain border exactly.
            boxShadow: "0 1px 2px rgb(0 0 0 / 0.16), 0 20px 44px rgb(0 0 0 / 0.4)",
            overflow: "hidden",
          }}
        >
          {/* Paper grain — fades out together with the rest of the paper
              (same PAPER_TIMES window), so the finished editor pane stays
              perfectly flat like the real product surface. */}
          <motion.div
            initial={{ opacity: 0.1 }}
            animate={{ opacity: [0.1, 0.1, 0, 0] }}
            transition={{ duration: TOTAL_DURATION, times: PAPER_TIMES, ease: "linear" }}
            style={{
              position: "absolute",
              inset: 0,
              backgroundImage: `url("${PAPER_GRAIN_URL}")`,
              backgroundSize: "180px 180px",
              mixBlendMode: "multiply",
              pointerEvents: "none",
            }}
          />

          {/* Hand + pen, card-local */}
          <motion.div
            initial={{ x: HAND_X[0], y: HAND_Y[0], opacity: HAND_OPACITY[0] }}
            animate={{ x: HAND_X, y: HAND_Y, opacity: HAND_OPACITY }}
            transition={{ duration: TOTAL_DURATION, times: HAND_TIMES, ease: HAND_EASE }}
            style={{ position: "absolute", zIndex: 3 }}
          >
            <FountainPenIcon />
          </motion.div>

          {/* Handwriting layer */}
          <motion.div
            initial={{ opacity: 1 }}
            animate={{ opacity: HANDWRITING_OPACITY }}
            transition={{ duration: TOTAL_DURATION, times: CODE_SWAP_TIMES, ease: "linear" }}
            style={{
              position: "absolute",
              inset: 0,
              padding: "72px 24px 0",
              boxSizing: "border-box",
            }}
          >
            {HANDWRITING_LINES.map((line, index) => (
              <motion.div
                key={line}
                initial={{ clipPath: LINE_CLIP[0] }}
                animate={{ clipPath: LINE_CLIP }}
                transition={{
                  duration: TOTAL_DURATION,
                  times: LINE_TIMES[index],
                  ease: "linear",
                }}
                style={{
                  fontFamily: `${handwritingFont.style.fontFamily}, cursive`,
                  fontWeight: 600,
                  fontSize: 30,
                  lineHeight: "42px",
                  letterSpacing: "0.01em",
                  color: "#241f36",
                  textShadow: "0 0.5px 0 rgb(0 0 0 / 0.12)",
                  whiteSpace: "pre",
                }}
              >
                {line}
              </motion.div>
            ))}
          </motion.div>

          {/* Scan line */}
          <motion.div
            initial={{ opacity: 0, top: SCAN_TOP[0] }}
            animate={{ opacity: SCAN_OPACITY, top: SCAN_TOP }}
            transition={{ duration: TOTAL_DURATION, times: SCAN_TIMES, ease: "linear" }}
            style={{
              position: "absolute",
              left: 0,
              right: 0,
              height: 2,
              background: "var(--accent)",
              zIndex: 2,
            }}
          />

          {/* Typed code layer */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: TYPED_OPACITY }}
            transition={{ duration: TOTAL_DURATION, times: CODE_SWAP_TIMES, ease: "linear" }}
            style={{
              position: "absolute",
              inset: 0,
              padding: 20,
              boxSizing: "border-box",
            }}
          >
            <TypedCode />
          </motion.div>
        </motion.div>
      </div>

      {/* Testing pane */}
      <motion.div
        initial={{ opacity: 0, x: PANE_X[0] }}
        animate={{ opacity: PANE_OPACITY, x: PANE_X }}
        transition={{ duration: TOTAL_DURATION, times: PANE_TIMES, ease: "linear" }}
        style={{
          position: "absolute",
          left: 580,
          top: 20,
          width: 280,
          height: 440,
          background: "var(--surface-raised)",
          border: "1px solid var(--border-subtle)",
          borderRadius: 10,
          padding: 16,
          boxSizing: "border-box",
        }}
      >
        <TestingPaneContents />
      </motion.div>
    </div>
  );
}

function TypedCode({ style }: { style?: React.CSSProperties }) {
  return (
    <pre
      style={{
        margin: 0,
        fontFamily: "var(--font-mono), monospace",
        fontSize: 13,
        lineHeight: "20px",
        color: "var(--ink-code)",
        ...style,
      }}
    >
      <span style={{ color: "var(--accent-emphasis)" }}>int</span> findMax(
      <span style={{ color: "var(--accent-emphasis)" }}>int</span> a,{" "}
      <span style={{ color: "var(--accent-emphasis)" }}>int</span> b) {"{"}
      {"\n  "}
      <span style={{ color: "var(--accent-emphasis)" }}>if</span> (a &gt; b)
      {"\n    "}
      <span style={{ color: "var(--accent-emphasis)" }}>return</span> a;
      {"\n  "}
      <span style={{ color: "var(--accent-emphasis)" }}>return</span> b;
      {"\n"}
      {"}"}
    </pre>
  );
}

function TestingPaneContents({ allShown = false }: { allShown?: boolean }) {
  return (
    <div>
      <p
        style={{
          margin: "0 0 12px",
          fontSize: 12,
          fontWeight: 600,
          color: "var(--ink-secondary)",
          textTransform: "uppercase",
          letterSpacing: "0.04em",
        }}
      >
        Tests
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {RESULTS.map((result) =>
          allShown ? (
            <ResultRow key={result.label} result={result} />
          ) : (
            <motion.div
              key={result.label}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: result.delay, duration: 0.35 }}
            >
              <ResultRow result={result} />
            </motion.div>
          ),
        )}
      </div>
    </div>
  );
}

function ResultRow({
  result,
}: {
  result: { label: string; verdict: "PASS" | "FAIL" };
}) {
  const ok = result.verdict === "PASS";
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "8px 10px",
        borderRadius: 6,
        background: ok ? "var(--status-ok-bg)" : "var(--status-fail-bg)",
        borderLeft: `2px solid ${ok ? "var(--status-ok-border)" : "var(--status-fail-border)"}`,
      }}
    >
      <span
        style={{
          fontSize: 11,
          fontWeight: 700,
          color: ok ? "var(--status-ok-fg)" : "var(--status-fail-fg)",
        }}
      >
        {result.verdict}
      </span>
      <span
        style={{
          fontFamily: "var(--font-mono), monospace",
          fontSize: 12,
          color: "var(--ink-secondary)",
        }}
      >
        {result.label}
      </span>
    </div>
  );
}
