export function nextTestName(tests: { name: string }[]): string {
  const usedNumbers = new Set(
    tests.flatMap((t) => {
      const m = /^Test (\d+)$/.exec(t.name);
      return m ? [parseInt(m[1], 10)] : [];
    }),
  );
  let n = 1;
  while (usedNumbers.has(n)) n++;
  return `Test ${n}`;
}
