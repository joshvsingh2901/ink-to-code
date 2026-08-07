import type { FunctionTypeMetadata } from "./testExecution";

export type ContainerRow = {
  id: string;
  value: string;
};

export type ContainerEntry = {
  id: string;
  key: string;
  value: string;
};

export type ContainerEditorKind =
  | "sequence"
  | "set"
  | "map"
  | "adapter"
  | "scalar";

let _rowIdCounter = 0;
function nextId(): string {
  return `row-${++_rowIdCounter}`;
}

export function editorKindFor(
  metadata: FunctionTypeMetadata | null | undefined,
): ContainerEditorKind {
  if (!metadata || metadata.kind !== "container") return "scalar";
  if (metadata.vector_depth === 2) return "scalar"; // nested vector keeps legacy textarea

  const name = metadata.container_name;
  if (!name) return "scalar";

  if (
    name === "map" ||
    name === "multimap" ||
    name === "unordered_map" ||
    name === "unordered_multimap"
  )
    return "map";

  if (
    name === "set" ||
    name === "multiset" ||
    name === "unordered_set" ||
    name === "unordered_multiset"
  )
    return "set";

  if (name === "stack" || name === "queue" || name === "priority_queue")
    return "adapter";

  // deque, list (and sequence containers in general)
  return "sequence";
}

export function adapterOrderLabel(
  containerName: string,
  usage: "input" | "expected",
): string {
  if (usage === "input") {
    if (containerName === "stack") return "Enter values bottom → top";
    if (containerName === "queue") return "Enter values front → back";
    if (containerName === "priority_queue")
      return "Enter values in any insertion order; highest value has highest priority";
    return "";
  }
  // usage === "expected"
  if (containerName === "stack") return "Expected top → bottom";
  if (containerName === "queue") return "Expected front → back";
  if (containerName === "priority_queue") return "Expected pop order";
  return "";
}

export function createRow(value = ""): ContainerRow {
  return { id: nextId(), value };
}

export function createEntry(key = "", value = ""): ContainerEntry {
  return { id: nextId(), key, value };
}

export function addRow(rows: ContainerRow[]): ContainerRow[] {
  return [...rows, createRow()];
}

export function removeRow(rows: ContainerRow[], id: string): ContainerRow[] {
  return rows.filter((r) => r.id !== id);
}

export function moveRow(
  rows: ContainerRow[],
  id: string,
  direction: -1 | 1,
): ContainerRow[] {
  const idx = rows.findIndex((r) => r.id === id);
  if (idx < 0) return rows;
  const target = idx + direction;
  if (target < 0 || target >= rows.length) return rows;
  const next = [...rows];
  [next[idx], next[target]] = [next[target], next[idx]];
  return next;
}

export function addEntry(entries: ContainerEntry[]): ContainerEntry[] {
  return [...entries, createEntry()];
}

export function removeEntry(
  entries: ContainerEntry[],
  id: string,
): ContainerEntry[] {
  return entries.filter((e) => e.id !== id);
}

export function moveEntry(
  entries: ContainerEntry[],
  id: string,
  direction: -1 | 1,
): ContainerEntry[] {
  const idx = entries.findIndex((e) => e.id === id);
  if (idx < 0) return entries;
  const target = idx + direction;
  if (target < 0 || target >= entries.length) return entries;
  const next = [...entries];
  [next[idx], next[target]] = [next[target], next[idx]];
  return next;
}

function isStringElement(metadata: FunctionTypeMetadata): boolean {
  const et = metadata.element_type;
  return et === "std::string" || et === "char";
}

function isBoolElement(metadata: FunctionTypeMetadata): boolean {
  return metadata.element_type === "bool";
}

function formatValue(
  raw: string,
  metadata: FunctionTypeMetadata,
): string | number | boolean | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  if (isBoolElement(metadata)) {
    if (trimmed === "true" || trimmed === "1") return true;
    if (trimmed === "false" || trimmed === "0") return false;
    return trimmed; // let backend validate
  }
  if (isStringElement(metadata)) return trimmed;
  // numeric: try to parse, fallback to raw string so backend can report error
  const num = Number(trimmed);
  if (!isNaN(num) && trimmed !== "") return num;
  return trimmed;
}

export function rowsToArgument(
  rows: ContainerRow[],
  metadata: FunctionTypeMetadata,
): string {
  if (rows.length === 0) return "[]";
  const values = rows
    .map((r) => formatValue(r.value, metadata))
    .filter((v) => v !== null);
  return JSON.stringify(values);
}

export function entriesToArgument(
  entries: ContainerEntry[],
  metadata: FunctionTypeMetadata,
): string {
  if (entries.length === 0) return "[]";

  const name = metadata.container_name ?? "";
  const allowDuplicates = name === "multimap" || name === "unordered_multimap";
  const keys = entries.map((e) => e.key.trim());
  const allUniqueStringKeys =
    !allowDuplicates &&
    new Set(keys).size === keys.length &&
    keys.every((k) => k !== "");

  if (allUniqueStringKeys) {
    const obj: Record<string, unknown> = {};
    for (const entry of entries) {
      const k = entry.key.trim();
      const vt: FunctionTypeMetadata = {
        ...metadata,
        element_type: metadata.mapped_type ?? "int",
      };
      const v = formatValue(entry.value, vt);
      obj[k] = v;
    }
    return JSON.stringify(obj);
  }

  const list = entries.map((entry) => {
    const vt: FunctionTypeMetadata = {
      ...metadata,
      element_type: metadata.mapped_type ?? "int",
    };
    return {
      key: entry.key.trim(),
      value: formatValue(entry.value, vt),
    };
  });
  return JSON.stringify(list);
}

export function parseArgumentToRows(
  argument: string,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  _metadata: FunctionTypeMetadata,
): ContainerRow[] {
  try {
    const parsed = JSON.parse(argument);
    if (!Array.isArray(parsed)) return [createRow(argument)];
    return parsed.map((v) =>
      createRow(
        typeof v === "string"
          ? v
          : v === null || v === undefined
            ? ""
            : String(v),
      ),
    );
  } catch {
    if (!argument || argument.trim() === "" || argument.trim() === "[]")
      return [];
    return [createRow(argument)];
  }
}

export function parseArgumentToEntries(
  argument: string,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  _metadata: FunctionTypeMetadata,
): ContainerEntry[] {
  try {
    const parsed = JSON.parse(argument);
    if (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)) {
      // JSON object form: {"key": value}
      return Object.entries(parsed as Record<string, unknown>).map(
        ([k, v]) =>
          createEntry(
            k,
            v === null || v === undefined ? "" : String(v),
          ),
      );
    }
    if (Array.isArray(parsed)) {
      return parsed.map((item) => {
        if (
          typeof item === "object" &&
          item !== null &&
          "key" in item &&
          "value" in item
        ) {
          const entry = item as { key: unknown; value: unknown };
          return createEntry(String(entry.key ?? ""), String(entry.value ?? ""));
        }
        if (Array.isArray(item) && item.length === 2) {
          return createEntry(String(item[0] ?? ""), String(item[1] ?? ""));
        }
        return createEntry("", String(item ?? ""));
      });
    }
  } catch {
    // fall through
  }
  if (!argument || argument.trim() === "" || argument.trim() === "[]") return [];
  return [createEntry("", argument)];
}

export function duplicateMapKeys(
  entries: ContainerEntry[],
  metadata: FunctionTypeMetadata,
): string[] {
  const name = metadata.container_name ?? "";
  if (name === "multimap" || name === "unordered_multimap") return [];
  const seen = new Set<string>();
  const dupes: string[] = [];
  for (const entry of entries) {
    const k = entry.key.trim();
    if (k === "") continue;
    if (seen.has(k)) {
      if (!dupes.includes(k)) dupes.push(k);
    }
    seen.add(k);
  }
  return dupes;
}

export function containerStateSignature(
  metadata: FunctionTypeMetadata | null | undefined,
): string {
  if (!metadata) return "null";
  return [
    metadata.kind,
    metadata.container_name ?? "",
    metadata.element_type ?? "",
    metadata.key_type ?? "",
    metadata.mapped_type ?? "",
    metadata.fixed_size ?? "",
    metadata.vector_depth ?? "",
  ].join("|");
}

export function previewContainerValue(
  serialized: string,
  maxItems = 12,
): string {
  try {
    const parsed = JSON.parse(serialized);
    if (Array.isArray(parsed)) {
      if (parsed.length <= maxItems) return JSON.stringify(parsed);
      const shown = JSON.stringify(parsed.slice(0, maxItems));
      const remaining = parsed.length - maxItems;
      return shown.slice(0, -1) + `, … +${remaining} more]`;
    }
    if (typeof parsed === "object" && parsed !== null) {
      const keys = Object.keys(parsed);
      if (keys.length <= maxItems) return JSON.stringify(parsed);
      const subset: Record<string, unknown> = {};
      keys.slice(0, maxItems).forEach((k) => {
        subset[k] = (parsed as Record<string, unknown>)[k];
      });
      const remaining = keys.length - maxItems;
      return JSON.stringify(subset).slice(0, -1) + `, … +${remaining} more}`;
    }
  } catch {
    // not valid JSON
  }
  return serialized.length > 200 ? serialized.slice(0, 200) + "…" : serialized;
}
