"use client";

import Editor, { type EditorProps } from "@monaco-editor/react";
import { useEffect, useState } from "react";
import {
  describeMonacoInitializationError,
  initializeMonaco,
} from "@/lib/monacoLoader";

export default function LocalMonacoEditor(props: EditorProps) {
  const [isReady, setIsReady] = useState(false);
  const [initializationError, setInitializationError] = useState<string | null>(
    null,
  );

  useEffect(() => {
    let active = true;

    initializeMonaco()
      .then(() => {
        if (active) setIsReady(true);
      })
      .catch((error: unknown) => {
        if (!active) return;
        const message = describeMonacoInitializationError(error);
        console.error("Monaco initialization failed:", message);
        setInitializationError(message);
      });

    return () => {
      active = false;
    };
  }, []);

  if (initializationError) {
    return (
      <div
        role="alert"
        className="flex h-full items-center justify-center p-6 text-sm text-[var(--status-fail-fg)]"
      >
        {initializationError} Refresh the page to retry.
      </div>
    );
  }

  if (!isReady) {
    return (
      props.loading ?? (
        <p className="p-6 text-sm text-[var(--ink-secondary)]">
          Loading code editor…
        </p>
      )
    );
  }

  return <Editor {...props} />;
}
