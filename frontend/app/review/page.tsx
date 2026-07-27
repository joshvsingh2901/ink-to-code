"use client";

import Image from "next/image";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useUploads } from "@/components/UploadProvider";
import { createMockTranscription, type UncertainRegion } from "@/lib/transcription";

export default function ReviewPage() {
  const router = useRouter();
  const {
    codeUpload,
    transcriptionResult,
    reviewedCode,
    setReviewedCode,
  } = useUploads();
  const [selectedPageIndex, setSelectedPageIndex] = useState(0);
  const editorRef = useRef<HTMLTextAreaElement>(null);
  const pages = codeUpload.pages;
  const allowMock = process.env.NEXT_PUBLIC_USE_MOCK_TRANSCRIPTION === "true";
  const result =
    transcriptionResult ??
    (allowMock && pages.length > 0 ? createMockTranscription(pages.length) : null);
  const transcription = reviewedCode ?? result?.code ?? "";
  const isEdited = result !== null && transcription !== result.code;

  useEffect(() => {
    if (pages.length === 0 || !result) router.replace("/");
  }, [pages.length, result, router]);

  function focusLine(lineNumber: number) {
    const lines = transcription.split("\n");
    const start = lines
      .slice(0, lineNumber - 1)
      .reduce((length, line) => length + line.length + 1, 0);
    const end = start + (lines[lineNumber - 1]?.length ?? 0);
    editorRef.current?.focus();
    editorRef.current?.setSelectionRange(start, end);
  }

  function applySuggestion(region: UncertainRegion, alternative: string) {
    if (region.line === null) return;
    const lines = transcription.split("\n");
    const lineIndex = region.line - 1;
    if (lines[lineIndex]?.includes(region.detected)) {
      lines[lineIndex] = lines[lineIndex].replace(region.detected, alternative);
      setReviewedCode(lines.join("\n"));
      requestAnimationFrame(() => focusLine(region.line!));
    } else {
      focusLine(region.line);
    }
  }

  if (pages.length === 0 || !result) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-50 px-6">
        <div className="text-center">
          <p className="font-semibold text-slate-900">
            No completed transcription was found.
          </p>
          <button
            type="button"
            onClick={() => router.push("/")}
            className="mt-4 rounded-lg bg-slate-900 px-5 py-2.5 font-semibold text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
          >
            Return to Upload
          </button>
        </div>
      </main>
    );
  }

  const selectedPage = pages[selectedPageIndex] ?? pages[0];

  return (
    <main className="min-h-screen bg-slate-50 px-4 py-8 sm:px-6 sm:py-12 lg:px-8">
      <div className="mx-auto max-w-7xl">
        <header>
          <p className="text-lg font-bold tracking-tight text-slate-950">InkToCode</p>
          <h1 className="mt-8 text-3xl font-bold tracking-tight text-slate-950 sm:text-5xl">
            Review Your Transcription
          </h1>
          <p className="mt-4 max-w-3xl text-base leading-7 text-slate-600 sm:text-lg">
            Check the extracted code and correct any transcription mistakes before continuing.
          </p>
        </header>

        <div className="mt-8 grid items-start gap-6 lg:grid-cols-2">
          <section aria-labelledby="original-pages-heading" className="min-w-0 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
            <div className="flex items-center justify-between gap-4">
              <h2 id="original-pages-heading" className="font-semibold text-slate-950">Original pages</h2>
              <p className="text-sm font-medium text-slate-600">Page {selectedPageIndex + 1} of {pages.length}</p>
            </div>
            <div className="relative mt-4 aspect-[4/3] overflow-hidden rounded-xl bg-slate-100 sm:aspect-[5/4]">
              <Image src={selectedPage.previewUrl} alt={`Handwritten code page ${selectedPageIndex + 1}`} fill unoptimized className="object-contain" />
            </div>
            <div className="mt-4 flex items-center justify-between gap-3">
              <button type="button" disabled={selectedPageIndex === 0} onClick={() => setSelectedPageIndex((index) => index - 1)} aria-label="Show previous handwritten-code page" className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 disabled:cursor-not-allowed disabled:opacity-40">Previous</button>
              <button type="button" disabled={selectedPageIndex === pages.length - 1} onClick={() => setSelectedPageIndex((index) => index + 1)} aria-label="Show next handwritten-code page" className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 disabled:cursor-not-allowed disabled:opacity-40">Next</button>
            </div>
            <div className="mt-4 flex gap-3 overflow-x-auto pb-1" aria-label="Choose a page">
              {pages.map((page, index) => (
                <button key={page.id} type="button" onClick={() => setSelectedPageIndex(index)} aria-label={`Show handwritten-code page ${index + 1}`} aria-current={selectedPageIndex === index ? "page" : undefined} className={`relative h-20 w-20 shrink-0 overflow-hidden rounded-lg border-2 bg-slate-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 ${selectedPageIndex === index ? "border-slate-900" : "border-transparent hover:border-slate-300"}`}>
                  <Image src={page.previewUrl} alt="" fill unoptimized className="object-contain" />
                  <span className="absolute bottom-1 right-1 rounded bg-slate-950/80 px-1.5 py-0.5 text-xs font-semibold text-white">{index + 1}</span>
                </button>
              ))}
            </div>
          </section>

          <section aria-labelledby="transcription-heading" className="min-w-0 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 id="transcription-heading" className="font-semibold text-slate-950">Editable transcription</h2>
              <p className="text-sm text-slate-600">Overall confidence: {Math.round(result.overall_confidence * 100)}%</p>
            </div>
            <div className="mt-3 flex items-center gap-2 text-xs font-medium text-slate-500">
              <span>{isEdited ? "Edited locally" : "Transcribed"}</span>
              {isEdited && <span>Not saved permanently</span>}
            </div>
            <label htmlFor="transcription-editor" className="sr-only">Editable code transcription</label>
            <textarea ref={editorRef} id="transcription-editor" value={transcription} onChange={(event) => setReviewedCode(event.target.value)} spellCheck={false} className="mt-4 min-h-96 w-full resize-y rounded-xl border border-slate-300 bg-slate-950 p-4 font-mono text-sm leading-6 text-slate-100 focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-300" />

            <div className="mt-5 border-t border-slate-100 pt-5">
              <h3 className="text-sm font-semibold text-slate-900">Uncertain regions</h3>
              {result.uncertain_regions.length === 0 ? (
                <p className="mt-3 text-sm text-slate-500">No uncertain regions reported.</p>
              ) : (
                <div className="mt-3 space-y-3">
                  {result.uncertain_regions.map((region) => {
                    const alternative = region.alternatives[0];
                    return (
                      <div key={region.id} className="flex flex-col gap-4 rounded-xl bg-slate-50 p-4 sm:flex-row sm:items-center sm:justify-between">
                        <button type="button" disabled={region.line === null} onClick={() => region.line !== null && focusLine(region.line)} className="text-left focus-visible:rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 disabled:cursor-default" aria-label={region.line === null ? `Review uncertainty on page ${region.page}` : `Focus uncertain transcription on line ${region.line}`}>
                          <span className="block text-sm font-semibold text-slate-900">{region.line === null ? `Page ${region.page}` : `Line ${region.line}`}</span>
                          <span className="mt-1 block text-sm text-slate-600">Detected: <code>{region.detected}</code>{alternative ? <> · Alternative: <code>{alternative}</code></> : null}</span>
                          <span className="mt-1 block text-xs text-slate-500">Confidence: {Math.round(region.confidence * 100)}%</span>
                        </button>
                        {alternative && region.line !== null && (
                          <button type="button" onClick={() => applySuggestion(region, alternative)} className="shrink-0 rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900">Apply {alternative}</button>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </section>
        </div>

        <div className="mt-8 flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between">
          <button type="button" onClick={() => router.push("/")} className="rounded-lg border border-slate-300 px-5 py-3 font-semibold text-slate-700 hover:bg-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900">Back to Upload</button>
          <button type="button" onClick={() => { setReviewedCode(transcription); router.push("/editor"); }} className="rounded-lg bg-slate-900 px-5 py-3 font-semibold text-white hover:bg-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900">Confirm and Continue</button>
        </div>
      </div>
    </main>
  );
}
