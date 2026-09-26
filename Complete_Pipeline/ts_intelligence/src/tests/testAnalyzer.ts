/**
 * CP-5: "Analyzer correctly handles at least 10–20 curated test examples."
 * Run with: npm run test:analyzer
 */
import { analyzeTranscript } from "../analyzer";
import { ANALYZER_TEST_CASES } from "./mockData";

let passed = 0;
let failed = 0;

console.log("=== CP-5: Transcript Analyzer Test ===\n");

for (const testCase of ANALYZER_TEST_CASES) {
  const result = analyzeTranscript(testCase.text);
  const labels = result.segments.map((s) => s.label);
  const ok = labels.includes(testCase.expectLabel as any);

  if (ok) passed++;
  else failed++;

  console.log(`${ok ? "PASS" : "FAIL"}  "${testCase.text}"`);
  console.log(`      expected label present: ${testCase.expectLabel}  (${testCase.note})`);
  console.log(
    `      segments: ${result.segments
      .map((s) => `[${s.label}:"${s.text}"]`)
      .join(" ")}\n`
  );
}

console.log(`\n${passed}/${ANALYZER_TEST_CASES.length} passed, ${failed} failed.`);
if (failed > 0) process.exitCode = 1;
