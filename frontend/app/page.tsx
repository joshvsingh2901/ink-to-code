"use client";

import { useRouter } from "next/navigation";
import ImageUploadCard from "@/components/ImageUploadCard";
import { useUploads } from "@/components/UploadProvider";

export default function Home() {
  const router = useRouter();
  const { codeUpload, setCodeUpload, questionUpload, setQuestionUpload } =
    useUploads();

  return (
    <main className="min-h-screen bg-slate-50 px-4 py-8 sm:px-6 sm:py-12 lg:px-8">
      <div className="mx-auto max-w-6xl">
        <header>
          <p className="text-lg font-bold tracking-tight text-slate-950">
            InkToCode
          </p>
          <div className="mt-10 max-w-3xl sm:mt-14">
            <h1 className="text-3xl font-bold tracking-tight text-slate-950 sm:text-5xl">
              Upload Your Handwritten Code
            </h1>
            <p className="mt-5 text-base leading-7 text-slate-600 sm:text-lg">
              Upload images or a PDF of your handwritten code. You may also
              upload the programming question if you want test generation and
              question-aware feedback later.
            </p>
          </div>
        </header>

        <div className="mt-10 grid items-start gap-6 lg:grid-cols-2">
          <ImageUploadCard
            id="code-images"
            sectionLabel="code"
            title="Handwritten Code"
            description="Upload up to 5 images or one PDF."
            required
            upload={codeUpload}
            onUploadChange={setCodeUpload}
          />
          <ImageUploadCard
            id="question-images"
            sectionLabel="question"
            title="Programming Question"
            description="Add up to 5 images or one PDF."
            upload={questionUpload}
            onUploadChange={setQuestionUpload}
          />
        </div>

        <div className="mt-8 flex flex-col items-start gap-3 sm:flex-row sm:items-center">
          <button
            type="button"
            disabled={codeUpload.pages.length === 0}
            onClick={() => router.push("/review")}
            className="rounded-lg bg-slate-900 px-6 py-3 font-semibold text-white transition-colors hover:bg-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-slate-900"
          >
            Continue
          </button>
        </div>
      </div>
    </main>
  );
}
