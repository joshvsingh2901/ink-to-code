import type { MemoryDiagnosis } from "./testExecution";

export type MemoryDiagnosisPresentation = {
  primary: MemoryDiagnosis | null;
  secondary: MemoryDiagnosis[];
  confidenceLabel: "Confirmed issue" | "Likely issue" | "Possible issue" | null;
  likelyAccess: string | null;
};

export function presentMemoryDiagnoses(
  diagnoses: MemoryDiagnosis[] | undefined,
): MemoryDiagnosisPresentation {
  const bounded = (diagnoses ?? []).slice(0, 3);
  const primary = bounded[0] ?? null;
  return {
    primary,
    secondary: bounded.slice(1),
    confidenceLabel:
      primary?.confidence === "confirmed"
        ? "Confirmed issue"
        : primary?.confidence === "likely"
          ? "Likely issue"
          : primary
            ? "Possible issue"
            : null,
    likelyAccess: primary?.source_range?.excerpt ?? null,
  };
}
