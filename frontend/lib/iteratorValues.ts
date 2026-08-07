import type { FunctionTypeMetadata } from "./testExecution";

export type IteratorState = {
  container: string[];
  position: number;
};

export function isIteratorMetadata(
  meta: FunctionTypeMetadata,
): meta is FunctionTypeMetadata & { kind: "iterator" } {
  return meta.kind === "iterator";
}

export function isRangeEnd(meta: FunctionTypeMetadata): boolean {
  return meta.kind === "iterator" && meta.iterator_role === "range_end";
}

export function defaultIteratorState(): IteratorState {
  return { container: [], position: 0 };
}

// Head argument carries both container and position.
export function headArgumentPayload(state: IteratorState): string {
  return JSON.stringify({ container: state.container, position: state.position });
}

// Tail argument carries position only — no container key.
export function tailArgumentPayload(position: number): string {
  return JSON.stringify({ position });
}

// Kept for back-compat; alias of headArgumentPayload.
export const serializeIteratorHead = headArgumentPayload;

// Kept for back-compat; alias of tailArgumentPayload.
export const serializeTail = tailArgumentPayload;

// Parses a head argument JSON (must contain both "container" and "position").
export function parseHeadArgument(raw: string): IteratorState | null {
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (
      parsed !== null &&
      typeof parsed === "object" &&
      !Array.isArray(parsed) &&
      "container" in parsed &&
      "position" in parsed &&
      Array.isArray((parsed as Record<string, unknown>).container)
    ) {
      return {
        container: (
          (parsed as Record<string, unknown>).container as unknown[]
        ).map((x) => String(x)),
        position: Number((parsed as Record<string, unknown>).position),
      };
    }
  } catch {
    // fall through
  }
  return null;
}

// Parses a tail argument JSON (must contain "position", must NOT contain "container").
export function parseTailArgument(raw: string): { position: number } | null {
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (
      parsed !== null &&
      typeof parsed === "object" &&
      !Array.isArray(parsed) &&
      "position" in parsed &&
      !("container" in parsed)
    ) {
      return { position: Number((parsed as Record<string, unknown>).position) };
    }
  } catch {
    // fall through
  }
  return null;
}

// Kept for back-compat; tries head then tail parsing.
export function parseIteratorArgument(raw: string): IteratorState | null {
  return parseHeadArgument(raw);
}

// Returns the number of elements in the backing container parsed from a head argument.
// Returns 0 for empty, unparseable, or tail arguments.
export function elementCountOf(raw: string): number {
  const state = parseHeadArgument(raw);
  return state?.container.length ?? 0;
}

// Validates a position against a container size. Returns an error string, or null if valid.
// Position 0..size are all accepted (size == end).
export function validatePosition(
  pos: number,
  containerSize: number,
): string | null {
  if (!Number.isInteger(pos)) return "Position must be an integer.";
  if (pos < 0) return "Position must be 0 or greater.";
  if (pos > containerSize)
    return `Position ${pos} exceeds container size ${containerSize}.`;
  return null;
}

// Returns a short preview string of the elements selected by the half-open range [begin, end).
export function rangeElementsPreview(headRaw: string, tailRaw: string): string {
  const head = parseHeadArgument(headRaw);
  if (!head) return "";
  const tail = parseTailArgument(tailRaw);
  const endPos =
    tail !== null ? tail.position : parseHeadArgument(tailRaw)?.position ?? 0;
  const slice = head.container.slice(head.position, endPos);
  if (slice.length === 0) return "(empty range)";
  return `[${slice.join(", ")}]`;
}

// Returns helper text for a position input field.
export function positionHelperText(pos: number, containerSize: number): string {
  if (pos === containerSize) return `Position ${pos} — points past the last element (end())`;
  return `Position ${pos} of ${containerSize} (0 = begin, ${containerSize} = end())`;
}

// Extracts the container as a raw JSON array string from a head payload,
// preserving original element types (numbers stay numbers, not strings).
export function containerJsonFromHeadPayload(raw: string): string {
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    if (Array.isArray(parsed.container)) {
      return JSON.stringify(parsed.container);
    }
  } catch {
    // fall through
  }
  return "[]";
}

// Builds a head payload from a ContainerValueEditor JSON output and a position.
// containerJson is the raw JSON array string (e.g. "[1, 2, 3]") with proper types.
export function headPayloadFromContainerJson(
  containerJson: string,
  position: number,
): string {
  try {
    const arr = JSON.parse(containerJson) as unknown[];
    return JSON.stringify({ container: arr, position });
  } catch {
    return JSON.stringify({ container: [], position });
  }
}

// Returns a synthetic FunctionTypeMetadata suitable for ContainerValueEditor,
// derived from an iterator parameter's metadata.
export function iteratorBackingMetadata(
  meta: FunctionTypeMetadata,
): FunctionTypeMetadata {
  const containerName = meta.iterator_container ?? "vector";
  return {
    kind: "container",
    display_type: `std::${containerName}<${meta.element_type ?? "int"}>`,
    scalar_type: null,
    element_type: meta.element_type ?? "int",
    vector_depth: null,
    passing: "value",
    size_parameter_name: null,
    container_family: "sequence",
    container_name: containerName,
    key_type: null,
    mapped_type: null,
    fixed_size: meta.fixed_size ?? null,
    nested_depth: 1,
    ordered: true,
    associative: false,
    unordered: false,
    adapter: false,
    supported: true,
    unsupported_reason: null,
  };
}

// Returns a signature string that distinguishes iterator types for change detection.
export function iteratorStateSignature(meta: FunctionTypeMetadata): string {
  if (meta.kind !== "iterator") return "";
  return [
    meta.iterator_container ?? "",
    meta.element_type ?? "",
    meta.fixed_size ?? "",
    meta.iterator_const ? "const" : "mutable",
    meta.iterator_role ?? "",
  ].join(":");
}

// Formats a raw iterator result value for display.
export function formatIteratorResult(raw: string | number | null): string {
  if (raw === null) return "";
  const s = String(raw);
  if (s === "end") return "end() — past the last element";
  const n = Number(s);
  if (!isNaN(n)) return `Index ${n}`;
  return s;
}
