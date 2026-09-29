/**
 * CP-8: "Person 2 can feed 20–30 mock transcripts into the system and get
 * structured RepairResults."
 *
 * Run with: npm run test:pipeline
 *
 * By default this uses a deterministic, rule-based MOCK "LLM" (see
 * mockLLMCompletion below) so the whole pipeline is testable with NO API
 * key and NO network access — exactly what Person 2 needs on Day 3-4
 * while working from mocks, per the task board ("Unblocked by design").
 *
 * TO USE THE REAL CLAUDE API INSTEAD:
 *   1. Set env var ANTHROPIC_API_KEY
 *   2. Remove the `mockCompletionFn` option below (or set it to undefined)
 *   The Person2Pipeline / LLMRepairEngine code does not change at all.
 */

import { Person2Pipeline } from "../pipeline";
import { RepairInput } from "../llmRepair";
import { MOCK_TRANSCRIPTS } from "./mockData";

/**
 * A small deterministic stand-in for the real LLM, implementing the same
 * 9 rules with simple string heuristics, purely so this test suite can run
 * offline. This is NOT meant to replace the real system prompt/LLM in
 * production — see llmRepair.ts SYSTEM_PROMPT for the real logic that goes
 * to Claude.
 */
async function mockLLMCompletion(input: RepairInput): Promise<string> {
  const original = input.transcript.text;
  let text = original;
  const changes: Array<{ type: string; original?: string; replacement?: string }> = [];

  // Remove immediate word-level stutters: "I I I want" -> "I want"
  const beforeStutter = text;
  text = text.replace(/\b(\w+)( \1\b)+/gi, (match, word) => {
    // Preserve if it looks like intentional emphasis (comma-joined or an
    // emphasis word nearby) — crude check mirroring analyzer's logic.
    const commaJoined = /,\s*\w+,?\s*\w+/.test(match);
    if (commaJoined) return match;
    return word;
  });
  if (text !== beforeStutter) {
    changes.push({ type: "remove_repetition", original: beforeStutter, replacement: text });
  }

  // Remove filler words
  const beforeFiller = text;
  text = text
    .replace(/\b(um+|uh+|erm|kind of|sort of)\b,?/gi, "")
    .replace(/\s{2,}/g, " ")
    .trim();
  if (text !== beforeFiller) {
    changes.push({ type: "remove_filler", original: beforeFiller, replacement: text });
  }

  // Resolve "X ... no/actually Y" self-corrections -> keep only Y
  const correctionMatch = text.match(/^(.*?)(?:,|\s)?\s*(?:no|actually)[, ]+([^.]+)\.?$/i);
  if (correctionMatch && /—|no,|actually|no\s|for .*no /i.test(text)) {
    const before = text;
    const kept = correctionMatch[2].trim();
    const prefix = correctionMatch[1].replace(/[—-]\s*$/, "").trim();
    // crude re-assembly: keep prefix words minus the abandoned final value
    const candidate = `${prefix.split(" ").slice(0, -1).join(" ")} ${kept}`.trim();
    if (candidate.length > 3) {
      text = candidate.endsWith(".") ? candidate : candidate + ".";
      changes.push({ type: "resolve_restart", original: before, replacement: text });
    }
  }

  // Uncertainty: if analyzer flagged an "uncertain" segment, be conservative.
  const hasUncertain = input.analysis.segments.some((s) => s.label === "uncertain");
  const isVeryShortOrIncomplete = original.trim().endsWith("…") || original.trim().endsWith("for");

  const uncertain = hasUncertain && isVeryShortOrIncomplete;
  const confidence = uncertain ? 0.3 : changes.length > 0 ? 0.88 : 0.95;

  const output = {
    repairedText: uncertain ? original : text,
    confidence,
    changes,
    uncertain,
  };

  return JSON.stringify(output);
}

async function main() {
  const pipeline = new Person2Pipeline({
    llmOptions: { mockCompletionFn: mockLLMCompletion },
  });

  console.log(`=== CP-8: Pipeline Test — ${MOCK_TRANSCRIPTS.length} mock transcripts ===\n`);

  let succeeded = 0;
  for (const transcript of MOCK_TRANSCRIPTS) {
    try {
      const result = await pipeline.repair(transcript);
      succeeded++;
      console.log(`[${result.utteranceId}] "${result.originalText}"`);
      console.log(`   -> "${result.repairedText}"  (confidence=${result.confidence})`);
      if (result.changes.length > 0) {
        console.log(
          `   changes: ${result.changes.map((c) => c.type).join(", ")}`
        );
      }
      console.log();
    } catch (err: any) {
      console.log(`[${transcript.utteranceId}] ERROR: ${err.message}\n`);
    }
  }

  console.log(
    `\n${succeeded}/${MOCK_TRANSCRIPTS.length} transcripts produced a structured RepairResult.`
  );
  if (succeeded !== MOCK_TRANSCRIPTS.length) process.exitCode = 1;
}

main();
