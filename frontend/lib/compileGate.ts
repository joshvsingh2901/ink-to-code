import type { CompileResult } from "./compiler";

export type CompileGateState =
  | "never_compiled"
  | "compiling"
  | "stale"
  | "failed"
  | "unknown"
  | "ready";

export type CompileGateInput = {
  compiledVersion: number | null;
  codeVersion: number;
  isCompiling: boolean;
  compileResult: CompileResult | null;
  checkError: string | null;
  compileError: string | null;
};

// checkError/compileError are only ever set for the current codeVersion (the
// compile request's own version-mismatch guards discard responses for a
// superseded version before either error state is written), so a non-null
// error always outranks a stale-by-version compiledVersion.
export function deriveCompileGate(input: CompileGateInput): CompileGateState {
  const {
    compiledVersion,
    codeVersion,
    isCompiling,
    compileResult,
    checkError,
    compileError,
  } = input;

  if (isCompiling) return "compiling";
  if (checkError || compileError) return "unknown";
  if (compiledVersion === null) return "never_compiled";
  if (compiledVersion !== codeVersion) return "stale";

  const isCleanSuccess =
    compileResult?.success === true &&
    compileResult.exit_code === 0 &&
    compileResult.diagnostics.length === 0;
  return isCleanSuccess ? "ready" : "failed";
}
