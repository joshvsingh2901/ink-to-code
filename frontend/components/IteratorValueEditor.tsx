"use client";

import React, { useEffect, useRef } from "react";

import { ContainerValueEditor } from "./ContainerValueEditor";
import {
  containerJsonFromHeadPayload,
  headPayloadFromContainerJson,
  iteratorBackingMetadata,
  parseHeadArgument,
  parseTailArgument,
  tailArgumentPayload,
} from "../lib/iteratorValues";
import type { FunctionTypeMetadata } from "../lib/testExecution";

type Props = {
  id: string;
  // Metadata of the range_begin (or single) iterator parameter.
  metadata: FunctionTypeMetadata;
  // Serialized head argument: {"container":[...],"position":N}
  headValue: string;
  onHeadChange: (next: string) => void;
  // Only present for range pairs: the tail argument {"position":N}
  tailValue?: string;
  onTailChange?: (next: string) => void;
  // Mutation opt-in: only provided for non-const mutable iterators.
  mutationChecked?: boolean;
  onMutationCheckedChange?: (checked: boolean) => void;
  disabled?: boolean;
};

export default function IteratorValueEditor({
  id,
  metadata,
  headValue,
  onHeadChange,
  tailValue,
  onTailChange,
  mutationChecked,
  onMutationCheckedChange,
  disabled = false,
}: Props) {
  const isRange = onTailChange !== undefined;
  const backingMeta = iteratorBackingMetadata(metadata);

  // Extract current container JSON and head position from stored argument.
  const containerJson = containerJsonFromHeadPayload(headValue);
  const headPos = parseHeadArgument(headValue)?.position ?? 0;
  const containerSize = (() => {
    try {
      const arr = JSON.parse(containerJson) as unknown[];
      return Array.isArray(arr) ? arr.length : 0;
    } catch {
      return 0;
    }
  })();

  // Extract tail position.
  const tailPos = tailValue !== undefined
    ? (parseTailArgument(tailValue)?.position ?? parseHeadArgument(tailValue)?.position ?? 0)
    : 0;

  // On first render, if the head slot is empty (never been set), initialize it
  // to {"container":[],"position":0} so the backend receives a valid head
  // payload even if the user never changes any field.
  const headInitialized = useRef(false);
  useEffect(() => {
    if (!headInitialized.current && !parseHeadArgument(headValue)) {
      headInitialized.current = true;
      onHeadChange(headPayloadFromContainerJson("[]", 0));
    }
  }, [headValue, onHeadChange]);

  // On first render, if this is a range pair and the tail slot is empty (never
  // been set), initialize it to {"position":0} so the backend receives a valid
  // tail payload even if the user never changes the End position.
  const tailInitialized = useRef(false);
  useEffect(() => {
    if (!tailInitialized.current && isRange && !parseTailArgument(tailValue ?? "")) {
      tailInitialized.current = true;
      onTailChange?.(tailArgumentPayload(0));
    }
  }, [isRange, onTailChange, tailValue]);

  const handleContainerChange = (newContainerJson: string) => {
    onHeadChange(headPayloadFromContainerJson(newContainerJson, headPos));
  };

  const handleHeadPositionChange = (pos: number) => {
    onHeadChange(headPayloadFromContainerJson(containerJson, pos));
  };

  const handleTailPositionChange = (pos: number) => {
    onTailChange!(tailArgumentPayload(pos));
  };

  const rangeCaption = isRange
    ? `Uses the half-open range [start, end)`
    : null;

  return (
    <div className="space-y-3">
      {/* Backing container — one editor shared by head and (if range) tail */}
      <ContainerValueEditor
        id={`${id}-container`}
        label={`Backing container (${backingMeta.display_type})`}
        metadata={backingMeta}
        value={containerJson}
        usage="input"
        onChange={handleContainerChange}
        disabled={disabled}
      />

      {/* Position inputs */}
      <div className={`flex gap-4 ${isRange ? "" : ""}`}>
        <div className="space-y-1">
          <label
            htmlFor={`${id}-start`}
            className="block text-xs text-slate-500"
          >
            {isRange ? "Start index" : "Position"}
            <span className="ml-1 text-[11px] text-slate-400">
              (0–{containerSize})
            </span>
          </label>
          <input
            id={`${id}-start`}
            type="number"
            inputMode="numeric"
            min={0}
            max={containerSize}
            value={headPos}
            onChange={(e) => handleHeadPositionChange(Number(e.target.value))}
            disabled={disabled}
            className="w-24 rounded-md border border-slate-300 px-2 py-1.5 font-mono text-xs text-slate-800 focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200 disabled:opacity-50"
          />
        </div>

        {isRange && (
          <div className="space-y-1">
            <label
              htmlFor={`${id}-end`}
              className="block text-xs text-slate-500"
            >
              End index
              <span className="ml-1 text-[11px] text-slate-400">
                (0–{containerSize})
              </span>
            </label>
            <input
              id={`${id}-end`}
              type="number"
              inputMode="numeric"
              min={0}
              max={containerSize}
              value={tailPos}
              onChange={(e) => handleTailPositionChange(Number(e.target.value))}
              disabled={disabled}
              className="w-24 rounded-md border border-slate-300 px-2 py-1.5 font-mono text-xs text-slate-800 focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200 disabled:opacity-50"
            />
          </div>
        )}
      </div>

      {rangeCaption && (
        <p className="text-[11px] text-slate-500">{rangeCaption}</p>
      )}

      {/* Mutation opt-in: shown only for non-const mutable iterators */}
      {onMutationCheckedChange !== undefined && (
        <label className="flex cursor-pointer items-center gap-2">
          <input
            type="checkbox"
            checked={mutationChecked ?? false}
            onChange={(e) => onMutationCheckedChange(e.target.checked)}
            disabled={disabled}
            className="h-3.5 w-3.5 rounded border-slate-300 text-slate-700 focus:ring-2 focus:ring-slate-200"
          />
          <span className="text-xs text-slate-600">
            Check backing container after call
          </span>
        </label>
      )}
    </div>
  );
}
