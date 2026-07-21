export default function Home() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 px-6 py-16">
      <section className="w-full max-w-2xl text-center">
        <h1 className="text-4xl font-bold tracking-tight text-slate-950 sm:text-6xl">
          InkToCode
        </h1>
        <p className="mx-auto mt-6 max-w-xl text-lg leading-8 text-slate-600 sm:text-xl">
          Turn handwritten code into editable source files.
        </p>
        <button
          type="button"
          disabled
          className="mt-10 rounded-lg bg-slate-900 px-6 py-3 font-semibold text-white opacity-50 disabled:cursor-not-allowed"
        >
          Start Transcribing
        </button>
      </section>
    </main>
  );
}
