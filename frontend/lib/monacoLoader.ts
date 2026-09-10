import { loader } from "@monaco-editor/react";

type MonacoInstance = Awaited<ReturnType<typeof loader.init>>;
type MonacoGlobal = typeof globalThis & {
  MonacoEnvironment?: {
    getWorker(moduleId: string, label: string): Worker;
  };
};

let initializationPromise: Promise<MonacoInstance> | null = null;

function configureMonacoWorker() {
  (globalThis as MonacoGlobal).MonacoEnvironment = {
    getWorker(_moduleId: string, label: string) {
      return new Worker(
        new URL("../workers/monacoEditor.worker.ts", import.meta.url),
        { name: label, type: "module" },
      );
    },
  };
}

export function describeMonacoInitializationError(error: unknown): string {
  if (error instanceof Error && error.message.trim()) {
    return `The code editor could not initialize: ${error.message.trim()}`;
  }

  if (typeof error === "object" && error !== null) {
    const candidate = error as {
      type?: unknown;
      target?: { tagName?: unknown; src?: unknown } | null;
    };
    const eventType =
      typeof candidate.type === "string" ? candidate.type : "unknown";
    const tagName =
      typeof candidate.target?.tagName === "string"
        ? candidate.target.tagName.toLowerCase()
        : null;
    const resourceKind = tagName === "script" ? "script" : "resource";

    return `The code editor could not load a required ${resourceKind} (${eventType} event).`;
  }

  return "The code editor could not initialize because an unknown loading error occurred.";
}

/**
 * Load Monaco from the installed package so editor startup never depends on a
 * third-party CDN. The module-level promise also makes React development
 * remounts share one initialization attempt.
 */
export function initializeMonaco() {
  if (!initializationPromise) {
    configureMonacoWorker();
    initializationPromise = import("monaco-editor")
      .then((monaco) => {
        loader.config({ monaco });
        return loader.init();
      })
      .catch((error: unknown) => {
        initializationPromise = null;
        throw error;
      });
  }

  return initializationPromise;
}
