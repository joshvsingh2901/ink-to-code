"use client";

import { useEffect, useState } from "react";

type BackendState = "checking" | "connected" | "unavailable";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function BackendStatus() {
  const [status, setStatus] = useState<BackendState>("checking");

  useEffect(() => {
    if (process.env.NODE_ENV !== "development") return;

    const controller = new AbortController();

    async function checkBackend() {
      try {
        const response = await fetch(
          `${API_BASE_URL.replace(/\/$/, "")}/health`,
          { signal: controller.signal },
        );

        if (!response.ok) {
          setStatus("unavailable");
          return;
        }

        const body: unknown = await response.json();
        const isHealthy =
          typeof body === "object" &&
          body !== null &&
          "status" in body &&
          body.status === "ok";
        setStatus(isHealthy ? "connected" : "unavailable");
      } catch (error) {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setStatus("unavailable");
        }
      }
    }

    void checkBackend();
    return () => controller.abort();
  }, []);

  if (process.env.NODE_ENV !== "development") return null;

  const label =
    status === "checking"
      ? "Checking backend..."
      : status === "connected"
        ? "Backend connected"
        : "Backend unavailable";

  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed bottom-3 right-3 z-50 flex items-center gap-2 rounded-full border border-slate-200 bg-white/95 px-3 py-1.5 text-xs font-medium text-slate-600 shadow-sm backdrop-blur"
    >
      <span
        aria-hidden="true"
        className={`h-2 w-2 rounded-full ${
          status === "connected"
            ? "bg-emerald-500"
            : status === "unavailable"
              ? "bg-slate-400"
              : "animate-pulse bg-amber-400"
        }`}
      />
      {label}
    </div>
  );
}
