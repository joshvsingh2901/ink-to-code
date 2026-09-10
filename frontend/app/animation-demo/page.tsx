import HeroTransformation from "@/components/HeroTransformation";

export default function AnimationDemoPage() {
  return (
    <main
      style={{
        minHeight: "100dvh",
        background: "var(--surface-base)",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "48px 24px",
        boxSizing: "border-box",
      }}
    >
      <p
        style={{
          margin: "0 0 24px",
          fontFamily: "var(--font-ui), sans-serif",
          fontSize: 13,
          color: "var(--ink-tertiary)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
        }}
      >
        Hero animation prototype
      </p>
      <HeroTransformation />
    </main>
  );
}
