"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";

import {
  addEntry,
  addRow,
  adapterOrderLabel,
  containerStateSignature,
  duplicateMapKeys,
  editorKindFor,
  entriesToArgument,
  moveEntry,
  moveRow,
  parseArgumentToEntries,
  parseArgumentToRows,
  removeEntry,
  removeRow,
  rowsToArgument,
  type ContainerEntry,
  type ContainerRow,
} from "../lib/containerValues";
import type { FunctionTypeMetadata } from "../lib/testExecution";

type Props = {
  id: string;
  label: string;
  metadata: FunctionTypeMetadata | null | undefined;
  value: string;
  onChange: (next: string) => void;
  usage?: "input" | "expected";
  helperText?: string;
  disabled?: boolean;
};

const INPUT_CLASS =
  "mt-1 w-full min-w-0 rounded-md border border-slate-300 px-2 py-1.5 font-mono text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-slate-200 disabled:opacity-50";

const ICON_BUTTON =
  "rounded px-1.5 py-0.5 text-xs text-slate-500 hover:bg-slate-100 disabled:opacity-30 disabled:cursor-not-allowed";

export function ContainerValueEditor({
  id,
  label,
  metadata,
  value,
  onChange,
  usage = "input",
  helperText,
  disabled = false,
}: Props) {
  const kind = editorKindFor(metadata);

  if (kind === "scalar") {
    return (
      <div className="min-w-0">
        <label
          htmlFor={id}
          className="block text-xs font-medium text-slate-700"
        >
          {label}
        </label>
        <input
          id={id}
          value={value}
          maxLength={1_000}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          className={INPUT_CLASS}
        />
        {helperText && (
          <p className="mt-1 text-[11px] leading-4 text-slate-500">
            {helperText}
          </p>
        )}
      </div>
    );
  }

  if (kind === "map") {
    return (
      <MapEditor
        id={id}
        label={label}
        metadata={metadata!}
        value={value}
        onChange={onChange}
        disabled={disabled}
        helperText={helperText}
      />
    );
  }

  return (
    <RowEditor
      id={id}
      label={label}
      metadata={metadata!}
      value={value}
      onChange={onChange}
      usage={usage}
      disabled={disabled}
      helperText={helperText}
      kind={kind}
    />
  );
}

// ---------------------------------------------------------------------------
// RowEditor — sequence, set, adapter
// ---------------------------------------------------------------------------

function RowEditor({
  id,
  label,
  metadata,
  value,
  onChange,
  usage,
  disabled,
  helperText,
  kind,
}: {
  id: string;
  label: string;
  metadata: FunctionTypeMetadata;
  value: string;
  onChange: (next: string) => void;
  usage: "input" | "expected";
  disabled: boolean;
  helperText?: string;
  kind: "sequence" | "set" | "adapter";
}) {
  const sigRef = useRef(containerStateSignature(metadata));
  const [rows, setRows] = useState<ContainerRow[]>(() =>
    parseArgumentToRows(value, metadata),
  );

  // Reinitialize when container type changes
  useEffect(() => {
    const sig = containerStateSignature(metadata);
    if (sig !== sigRef.current) {
      sigRef.current = sig;
      setRows(parseArgumentToRows(value, metadata));
    }
  }, [metadata, value]);

  const emit = useCallback(
    (next: ContainerRow[]) => {
      setRows(next);
      onChange(rowsToArgument(next, metadata));
    },
    [metadata, onChange],
  );

  const noun =
    kind === "adapter" && metadata.container_name === "priority_queue"
      ? "value"
      : "element";

  const adapterLabel =
    kind === "adapter" && metadata.container_name
      ? adapterOrderLabel(metadata.container_name, usage)
      : null;

  return (
    <div className="min-w-0">
      <p className="text-xs font-medium text-slate-700">{label}</p>
      {adapterLabel && (
        <p className="mt-0.5 text-[11px] text-slate-500">{adapterLabel}</p>
      )}
      <div className="mt-1 space-y-1">
        {rows.map((row, idx) => (
          <div key={row.id} className="flex items-center gap-1">
            <label
              htmlFor={`${id}-row-${row.id}`}
              className="sr-only"
            >{`${noun.charAt(0).toUpperCase() + noun.slice(1)} ${idx + 1}`}</label>
            <input
              id={`${id}-row-${row.id}`}
              value={row.value}
              disabled={disabled}
              maxLength={200}
              aria-label={`${noun} ${idx + 1}`}
              onChange={(e) =>
                emit(
                  rows.map((r) =>
                    r.id === row.id ? { ...r, value: e.target.value } : r,
                  ),
                )
              }
              className="flex-1 min-w-0 rounded-md border border-slate-300 px-2 py-1 font-mono text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-slate-200 disabled:opacity-50"
            />
            <button
              type="button"
              aria-label={`Move ${noun} ${idx + 1} up`}
              disabled={disabled || idx === 0}
              onClick={() => emit(moveRow(rows, row.id, -1))}
              className={ICON_BUTTON}
            >
              ↑
            </button>
            <button
              type="button"
              aria-label={`Move ${noun} ${idx + 1} down`}
              disabled={disabled || idx === rows.length - 1}
              onClick={() => emit(moveRow(rows, row.id, 1))}
              className={ICON_BUTTON}
            >
              ↓
            </button>
            <button
              type="button"
              aria-label={`Remove ${noun} ${idx + 1}`}
              disabled={disabled}
              onClick={() => emit(removeRow(rows, row.id))}
              className={ICON_BUTTON}
            >
              ✕
            </button>
          </div>
        ))}
      </div>
      <button
        type="button"
        disabled={disabled}
        onClick={() => emit(addRow(rows))}
        className="mt-1 text-xs text-slate-500 hover:text-slate-700 disabled:opacity-50"
      >
        + Add {noun}
      </button>
      {helperText && (
        <p className="mt-1 text-[11px] leading-4 text-slate-500">{helperText}</p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// MapEditor — map, multimap, unordered_map, unordered_multimap
// ---------------------------------------------------------------------------

function MapEditor({
  id,
  label,
  metadata,
  value,
  onChange,
  disabled,
  helperText,
}: {
  id: string;
  label: string;
  metadata: FunctionTypeMetadata;
  value: string;
  onChange: (next: string) => void;
  disabled: boolean;
  helperText?: string;
}) {
  const sigRef = useRef(containerStateSignature(metadata));
  const [entries, setEntries] = useState<ContainerEntry[]>(() =>
    parseArgumentToEntries(value, metadata),
  );

  useEffect(() => {
    const sig = containerStateSignature(metadata);
    if (sig !== sigRef.current) {
      sigRef.current = sig;
      setEntries(parseArgumentToEntries(value, metadata));
    }
  }, [metadata, value]);

  const emit = useCallback(
    (next: ContainerEntry[]) => {
      setEntries(next);
      onChange(entriesToArgument(next, metadata));
    },
    [metadata, onChange],
  );

  const dupes = duplicateMapKeys(entries, metadata);

  return (
    <div className="min-w-0">
      <p className="text-xs font-medium text-slate-700">{label}</p>
      <div className="mt-1 space-y-2">
        {entries.map((entry, idx) => {
          const isDupe = dupes.includes(entry.key.trim());
          return (
            <div key={entry.id} className="flex flex-wrap items-start gap-1">
              <div className="flex-1 min-w-0">
                <label
                  htmlFor={`${id}-entry-${entry.id}-key`}
                  className="block text-[10px] text-slate-500"
                >
                  {`Entry ${idx + 1} key`}
                </label>
                <input
                  id={`${id}-entry-${entry.id}-key`}
                  value={entry.key}
                  disabled={disabled}
                  maxLength={200}
                  aria-invalid={isDupe}
                  aria-label={`Entry ${idx + 1} key`}
                  onChange={(e) =>
                    emit(
                      entries.map((en) =>
                        en.id === entry.id
                          ? { ...en, key: e.target.value }
                          : en,
                      ),
                    )
                  }
                  className={`w-full rounded-md border px-2 py-1 font-mono text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-slate-200 disabled:opacity-50 ${isDupe ? "border-red-400" : "border-slate-300"}`}
                />
                {isDupe && (
                  <p role="alert" className="mt-0.5 text-[10px] text-red-600">
                    Duplicate key &ldquo;{entry.key.trim()}&rdquo;
                  </p>
                )}
              </div>
              <div className="flex-1 min-w-0">
                <label
                  htmlFor={`${id}-entry-${entry.id}-value`}
                  className="block text-[10px] text-slate-500"
                >
                  {`Entry ${idx + 1} value`}
                </label>
                <input
                  id={`${id}-entry-${entry.id}-value`}
                  value={entry.value}
                  disabled={disabled}
                  maxLength={200}
                  aria-label={`Entry ${idx + 1} value`}
                  onChange={(e) =>
                    emit(
                      entries.map((en) =>
                        en.id === entry.id
                          ? { ...en, value: e.target.value }
                          : en,
                      ),
                    )
                  }
                  className="w-full rounded-md border border-slate-300 px-2 py-1 font-mono text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-slate-200 disabled:opacity-50"
                />
              </div>
              <div className="flex items-end gap-0.5 pt-5">
                <button
                  type="button"
                  aria-label={`Move entry ${idx + 1} up`}
                  disabled={disabled || idx === 0}
                  onClick={() => emit(moveEntry(entries, entry.id, -1))}
                  className={ICON_BUTTON}
                >
                  ↑
                </button>
                <button
                  type="button"
                  aria-label={`Move entry ${idx + 1} down`}
                  disabled={disabled || idx === entries.length - 1}
                  onClick={() => emit(moveEntry(entries, entry.id, 1))}
                  className={ICON_BUTTON}
                >
                  ↓
                </button>
                <button
                  type="button"
                  aria-label={`Remove entry ${idx + 1}`}
                  disabled={disabled}
                  onClick={() => emit(removeEntry(entries, entry.id))}
                  className={ICON_BUTTON}
                >
                  ✕
                </button>
              </div>
            </div>
          );
        })}
      </div>
      <button
        type="button"
        disabled={disabled}
        onClick={() => emit(addEntry(entries))}
        className="mt-1 text-xs text-slate-500 hover:text-slate-700 disabled:opacity-50"
      >
        + Add entry
      </button>
      {helperText && (
        <p className="mt-1 text-[11px] leading-4 text-slate-500">{helperText}</p>
      )}
    </div>
  );
}
