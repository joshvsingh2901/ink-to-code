"use client";

import { useState } from "react";

/**
 * Static "workspace" mockup for the landing page's second section — a
 * faithful recreation of the Claude Design source's editor/tests panel,
 * including its Tests/Compiler/Memory tab switching. This is illustrative
 * marketing content, not the real product's compiler/test UI (that lives
 * in app/editor/page.tsx and is untouched by this page).
 */

type Panel = "tests" | "compiler" | "memory";

const MONO = "'JetBrains Mono', monospace";

function TabButton({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <div
      onClick={onClick}
      role="tab"
      aria-selected={active}
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick();
        }
      }}
      style={{
        display: "flex",
        alignItems: "center",
        padding: "0 14px",
        cursor: "pointer",
        borderRight: "1px solid #16191f",
        background: active ? "#0d1014" : "transparent",
        borderBottom: `1px solid ${active ? "#5b7cfa" : "transparent"}`,
        color: active ? "#dfe3e9" : "#606772",
      }}
    >
      {label}
    </div>
  );
}

function StatRow({ label, value, ok }: { label: string; value: string; ok?: boolean }) {
  return (
    <div
      style={{
        display: "flex",
        padding: "7px 10px",
        border: "1px solid #171b21",
        borderRadius: 5,
        background: "#0c0f13",
      }}
    >
      <span style={{ color: "#8b929d" }}>{label}</span>
      <div style={{ flex: 1 }} />
      <span style={{ color: ok ? "#8fc470" : "#c9cfd8" }}>{value}</span>
    </div>
  );
}

const CODE_LINES: { n: number; content: React.ReactNode; flagged?: boolean }[] = [
  { n: 1, content: <><span style={{ color: "#b48ce8" }}>#include</span> <span style={{ color: "#8fc470" }}>&lt;vector&gt;</span></> },
  { n: 2, content: <><span style={{ color: "#b48ce8" }}>#include</span> <span style={{ color: "#8fc470" }}>&lt;algorithm&gt;</span></> },
  { n: 3, content: "" },
  { n: 4, content: <span style={{ color: "#5a616c" }}>{"// Assignment 4 — largest sum of a contiguous subarray"}</span> },
  {
    n: 5,
    content: (
      <>
        <span style={{ color: "#6fb3d9" }}>int</span> <span style={{ color: "#8aa8ff" }}>maxSubarraySum</span>(
        <span style={{ color: "#b48ce8" }}>const</span> <span style={{ color: "#6fb3d9" }}>std::vector</span>&lt;
        <span style={{ color: "#6fb3d9" }}>int</span>&gt;&amp; nums) {"{"}
      </>
    ),
  },
  {
    n: 6,
    flagged: true,
    content: (
      <>
        {"    "}
        <span style={{ color: "#6fb3d9" }}>int</span> best <span style={{ color: "#c9cfd8" }}>=</span>{" "}
        <span style={{ color: "#d8a76a" }}>0</span>;
        <span style={{ color: "#5a616c" }}>{"          // ← flagged: unreachable for all-negative input"}</span>
      </>
    ),
  },
  {
    n: 7,
    content: (
      <>
        {"    "}
        <span style={{ color: "#6fb3d9" }}>int</span> current <span style={{ color: "#c9cfd8" }}>=</span>{" "}
        <span style={{ color: "#d8a76a" }}>0</span>;
      </>
    ),
  },
  { n: 8, content: "" },
  {
    n: 9,
    content: (
      <>
        {"    "}
        <span style={{ color: "#b48ce8" }}>for</span> (<span style={{ color: "#6fb3d9" }}>size_t</span> i{" "}
        <span style={{ color: "#c9cfd8" }}>=</span> <span style={{ color: "#d8a76a" }}>0</span>; i{" "}
        <span style={{ color: "#c9cfd8" }}>&lt;</span> nums.<span style={{ color: "#8aa8ff" }}>size</span>();{" "}
        <span style={{ color: "#c9cfd8" }}>++</span>i) {"{"}
      </>
    ),
  },
  {
    n: 10,
    content: (
      <>
        {"        "}
        current <span style={{ color: "#c9cfd8" }}>=</span> <span style={{ color: "#6fb3d9" }}>std::max</span>
        (nums[i], current <span style={{ color: "#c9cfd8" }}>+</span> nums[i]);
      </>
    ),
  },
  {
    n: 11,
    content: (
      <>
        {"        "}
        best <span style={{ color: "#c9cfd8" }}>=</span> <span style={{ color: "#6fb3d9" }}>std::max</span>
        (best, current);
      </>
    ),
  },
  { n: 12, content: "    }" },
  { n: 13, content: "" },
  {
    n: 14,
    content: (
      <>
        {"    "}
        <span style={{ color: "#b48ce8" }}>return</span> best;
      </>
    ),
  },
  { n: 15, content: "}" },
];

export default function WorkspaceShowcase() {
  const [panel, setPanel] = useState<Panel>("tests");

  return (
    <div style={{ border: "1px solid #1b1f26", borderRadius: 9, background: "#0b0d10", overflow: "hidden" }}>
      {/* Title bar */}
      <div
        style={{
          height: 38,
          borderBottom: "1px solid #16191f",
          display: "flex",
          alignItems: "center",
          padding: "0 12px",
          gap: 12,
          background: "#0a0c0f",
        }}
      >
        <div style={{ display: "flex", gap: 6 }}>
          <span style={{ width: 9, height: 9, borderRadius: "50%", background: "#22262e" }} />
          <span style={{ width: 9, height: 9, borderRadius: "50%", background: "#22262e" }} />
          <span style={{ width: 9, height: 9, borderRadius: "50%", background: "#22262e" }} />
        </div>
        <div style={{ fontFamily: MONO, fontSize: 11.5, color: "#6b7280" }}>
          assignment-04 / max-subarray
        </div>
        <div style={{ flex: 1 }} />
        <div style={{ display: "flex", alignItems: "center", gap: 8, fontFamily: MONO, fontSize: 11, color: "#6b7280" }}>
          <span style={{ border: "1px solid #1e222a", borderRadius: 4, padding: "2px 7px" }}>g++ 13 · -std=c++17</span>
          <span style={{ border: "1px solid #1e222a", borderRadius: 4, padding: "2px 7px" }}>1 of 4 tests failing</span>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 1px minmax(0,0.86fr)" }}>
        {/* Left: editor mock */}
        <div style={{ background: "#0b0d10" }}>
          <div style={{ height: 34, borderBottom: "1px solid #16191f", display: "flex", alignItems: "stretch", fontFamily: MONO, fontSize: 11.5 }}>
            <div style={{ display: "flex", alignItems: "center", padding: "0 14px", color: "#dfe3e9", borderRight: "1px solid #16191f", borderBottom: "1px solid #5b7cfa", background: "#0d1014" }}>
              solution.cpp
            </div>
            <div style={{ display: "flex", alignItems: "center", padding: "0 14px", color: "#606772", borderRight: "1px solid #16191f" }}>
              tests.json
            </div>
            <div style={{ display: "flex", alignItems: "center", padding: "0 14px", color: "#606772", borderRight: "1px solid #16191f" }}>
              scan_01.jpg
            </div>
          </div>
          <div style={{ padding: "14px 0 20px", fontFamily: MONO, fontSize: 12.5, lineHeight: 1.85, whiteSpace: "pre", overflow: "hidden" }}>
            {CODE_LINES.map((line) => (
              <div
                key={line.n}
                style={{
                  display: "flex",
                  background: line.flagged ? "#141826" : undefined,
                  borderLeft: line.flagged ? "2px solid #5b7cfa" : undefined,
                }}
              >
                <span
                  style={{
                    width: line.flagged ? 42 : 44,
                    flex: "none",
                    textAlign: "right",
                    paddingRight: 16,
                    color: line.flagged ? "#7d86ff" : "#3b414b",
                  }}
                >
                  {line.n}
                </span>
                <span>{line.content}</span>
              </div>
            ))}
          </div>
          <div style={{ borderTop: "1px solid #16191f", padding: "8px 16px", display: "flex", gap: 18, fontFamily: MONO, fontSize: 11, color: "#5f6672" }}>
            <span>Ln 6, Col 17</span>
            <span>C++17</span>
            <span>transcribed 2 min ago</span>
            <div style={{ flex: 1 }} />
            <span style={{ color: "#7f8794" }}>98.6% confidence</span>
          </div>
        </div>

        <div style={{ background: "#16191f" }} />

        {/* Right: tests / compiler / memory */}
        <div style={{ background: "#0a0c0f", display: "flex", flexDirection: "column" }}>
          <div role="tablist" style={{ height: 34, borderBottom: "1px solid #16191f", display: "flex", alignItems: "stretch", fontFamily: MONO, fontSize: 11.5 }}>
            <TabButton label="Tests" active={panel === "tests"} onClick={() => setPanel("tests")} />
            <TabButton label="Compiler" active={panel === "compiler"} onClick={() => setPanel("compiler")} />
            <TabButton label="Memory" active={panel === "memory"} onClick={() => setPanel("memory")} />
            <div style={{ flex: 1 }} />
            <div style={{ display: "flex", alignItems: "center", padding: "0 12px", color: "#8b929d" }}>Run all ⌘↵</div>
          </div>

          {panel === "tests" && (
            <div style={{ padding: "14px 16px 18px", fontFamily: MONO, fontSize: 12 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, color: "#7f8794", fontSize: 11, letterSpacing: "0.04em", textTransform: "uppercase", marginBottom: 12 }}>
                <span>Test run · 0.31s</span>
                <span style={{ flex: 1, height: 1, background: "#16191f" }} />
                <span style={{ color: "#8fc470" }}>3 passed</span>
                <span style={{ color: "#e0776b" }}>1 failed</span>
              </div>
              <div style={{ display: "grid", gap: 6 }}>
                <div style={{ border: "1px solid #35242a", borderRadius: 5, background: "#120f11", overflow: "hidden" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 10px", borderBottom: "1px solid #241b1f" }}>
                    <span style={{ color: "#e0776b" }}>✗</span>
                    <span style={{ color: "#f0d6d2" }}>all_negative</span>
                    <div style={{ flex: 1 }} />
                    <span style={{ color: "#8b929d" }}>assertion failed</span>
                  </div>
                  <div style={{ padding: 10, display: "grid", gap: 5, lineHeight: 1.7 }}>
                    <div><span style={{ color: "#6b7280" }}>input   </span><span style={{ color: "#c9cfd8" }}>nums = {"{-4, -2, -7, -3}"}</span></div>
                    <div><span style={{ color: "#6b7280" }}>expected</span><span style={{ color: "#8fc470" }}> -2</span></div>
                    <div><span style={{ color: "#6b7280" }}>actual  </span><span style={{ color: "#e0776b" }}> 0</span></div>
                    <div style={{ color: "#6b7280", paddingTop: 4, whiteSpace: "normal", lineHeight: 1.6 }}>
                      `best` starts at 0, so an empty subarray always wins. Initialise from nums[0].
                    </div>
                  </div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 10px", border: "1px solid #171b21", borderRadius: 5, background: "#0c0f13" }}>
                  <span style={{ color: "#8fc470" }}>✓</span>
                  <span style={{ color: "#c9cfd8" }}>mixed_signs</span>
                  <div style={{ flex: 1 }} />
                  <span style={{ color: "#5f6672" }}>[-2,1,-3,4,-1,2,1,-5,4] → 6</span>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 10px", border: "1px solid #171b21", borderRadius: 5, background: "#0c0f13" }}>
                  <span style={{ color: "#8fc470" }}>✓</span>
                  <span style={{ color: "#c9cfd8" }}>single_element</span>
                  <div style={{ flex: 1 }} />
                  <span style={{ color: "#5f6672" }}>[7] → 7</span>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 10px", border: "1px solid #171b21", borderRadius: 5, background: "#0c0f13" }}>
                  <span style={{ color: "#8fc470" }}>✓</span>
                  <span style={{ color: "#c9cfd8" }}>large_input_10k</span>
                  <div style={{ flex: 1 }} />
                  <span style={{ color: "#5f6672" }}>0.08s · 4 MB peak</span>
                </div>
              </div>
              <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
                <span style={{ border: "1px solid #22262e", borderRadius: 5, padding: "5px 10px", color: "#c3c9d2", cursor: "pointer" }}>+ Add test</span>
                <span style={{ border: "1px solid #22262e", borderRadius: 5, padding: "5px 10px", color: "#c3c9d2", cursor: "pointer" }}>Re-run failed</span>
              </div>
            </div>
          )}

          {panel === "compiler" && (
            <div style={{ padding: "14px 16px 18px", fontFamily: MONO, fontSize: 12, lineHeight: 1.8 }}>
              <div style={{ color: "#7f8794", fontSize: 11, letterSpacing: "0.04em", textTransform: "uppercase", marginBottom: 12 }}>
                g++ -std=c++17 -Wall -Wextra -fsanitize=address
              </div>
              <div style={{ border: "1px solid #171b21", borderRadius: 5, background: "#0c0f13", padding: 12, whiteSpace: "pre-wrap" }}>
                <div>
                  <span style={{ color: "#c9cfd8" }}>solution.cpp:9:34: </span>
                  <span style={{ color: "#d8a76a" }}>warning: </span>
                  <span style={{ color: "#98a0ab" }}>comparison of integer expressions of different signedness [-Wsign-compare]</span>
                </div>
                <div style={{ color: "#6b7280" }}>    9 |     for (size_t i = 0; i &lt; nums.size(); ++i) {"{"}</div>
                <div style={{ color: "#6b7280" }}>      |                        ~~^~~~~~~~~~~~~</div>
                <div style={{ height: 10 }} />
                <div>
                  <span style={{ color: "#8fc470" }}>Build succeeded</span>
                  <span style={{ color: "#6b7280" }}> — 1 warning, 0 errors, 0.42s</span>
                </div>
              </div>
            </div>
          )}

          {panel === "memory" && (
            <div style={{ padding: "14px 16px 18px", fontFamily: MONO, fontSize: 12, lineHeight: 1.8 }}>
              <div style={{ color: "#7f8794", fontSize: 11, letterSpacing: "0.04em", textTransform: "uppercase", marginBottom: 12 }}>
                Memory report · AddressSanitizer
              </div>
              <div style={{ display: "grid", gap: 6 }}>
                <StatRow label="Peak heap" value="4.1 MB" />
                <StatRow label="Leaked bytes" value="0" ok />
                <StatRow label="Invalid reads" value="0" ok />
                <StatRow label="Out-of-bounds writes" value="0" ok />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
