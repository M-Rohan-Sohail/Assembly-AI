import { TranscriptEvent } from "../types";

/**
 * CP-5 fixtures: curated examples the Transcript Analyzer must handle
 * correctly. Each includes the expected label that should appear SOMEWHERE
 * in the segments (used loosely by the test harness — this is a heuristic
 * analyzer, not a full NLP model, so we assert presence, not exact spans).
 */
export const ANALYZER_TEST_CASES: Array<{
  text: string;
  expectLabel: string;
  note: string;
}> = [
  { text: "I I wanted to book an appointment.", expectLabel: "possible_repetition", note: "single word repetition" },
  { text: "I I I want to go home.", expectLabel: "possible_repetition", note: "triple repetition" },
  { text: "Um, I need help with my account.", expectLabel: "filler", note: "leading filler" },
  { text: "I want to, uh, schedule a call.", expectLabel: "filler", note: "mid-sentence filler" },
  { text: "I want Friday—actually Thursday.", expectLabel: "restart", note: "dash restart marker" },
  { text: "No, actually, let's do Tuesday.", expectLabel: "restart", note: "explicit restart word" },
  { text: "I wanted to…", expectLabel: "uncertain", note: "trailing incomplete phrase" },
  { text: "I need to schedule a meeting for", expectLabel: "uncertain", note: "dangling preposition" },
  { text: "No, no, I really mean it.", expectLabel: "normal", note: "intentional repetition should NOT be flagged as filler" },
  { text: "I really, really like this.", expectLabel: "normal", note: "intentional emphasis repetition" },
  { text: "Book an appointment book an appointment for Monday.", expectLabel: "possible_repetition", note: "repeated fragment" },
  { text: "I need 500 dollars.", expectLabel: "normal", note: "plain numeric statement, nothing to flag" },
  { text: "My appointment is on September 15th.", expectLabel: "normal", note: "plain date statement" },
  { text: "I want to meet him there.", expectLabel: "normal", note: "ambiguous but not a dysfluency" },
  { text: "So, like, I kind of need this done today.", expectLabel: "filler", note: "multiple casual fillers" },
  { text: "Wait, sorry, I meant Thursday, not Wednesday.", expectLabel: "restart", note: "self-correction with sorry/wait" },
  { text: "He he said he would call.", expectLabel: "possible_repetition", note: "pronoun repetition" },
  { text: "I don't, I don't want that one.", expectLabel: "possible_repetition", note: "repeated negation phrase (must not flip negation later)" },
];

let counter = 0;
function mk(text: string, confidence: number): TranscriptEvent {
  counter++;
  return {
    type: "transcript.final",
    version: 1,
    sessionId: "test-session-1",
    utteranceId: `utt-${counter}`,
    text,
    isFinal: true,
    confidence,
    startMs: counter * 1000,
    endMs: counter * 1000 + 800,
  };
}

/**
 * CP-8 fixtures: 20-30 mock TranscriptEvents to push end-to-end through the
 * Person2Pipeline, spanning the Day-13 scenario categories from the task
 * board: repetition, pause, restart, number, date, intentional repetition,
 * ambiguous, plus filler/incomplete/negation cases for good measure.
 */
export const MOCK_TRANSCRIPTS: TranscriptEvent[] = [
  mk("I I wanted to book an appointment for Friday… no Wednesday.", 0.9),
  mk("I I I want to go home.", 0.85),
  mk("I need to schedule a meeting.", 0.95),
  mk("For Wednesday morning.", 0.92),
  mk("Um, I need help with my account.", 0.8),
  mk("I want to, uh, schedule a call for tomorrow.", 0.83),
  mk("I want Friday—actually Thursday.", 0.88),
  mk("No, actually, let's do Tuesday instead.", 0.9),
  mk("I need 500 dollars.", 0.97),
  mk("My appointment is on September 15th.", 0.96),
  mk("No, no, I really mean it.", 0.93),
  mk("I really, really like this plan.", 0.94),
  mk("I want to meet him there.", 0.7),
  mk("So, like, I kind of need this done today.", 0.75),
  mk("Wait, sorry, I meant Thursday, not Wednesday.", 0.82),
  mk("He he said he would call me back.", 0.79),
  mk("I don't, I don't want that one.", 0.86),
  mk("Book an appointment book an appointment for Monday.", 0.81),
  mk("I wanted to…", 0.4),
  mk("I need to schedule a meeting for", 0.35),
  mk("Can you send the invoice to John by Friday?", 0.95),
  mk("I I have three three questions about the bill.", 0.77),
  mk("Actually, no, cancel that request.", 0.89),
  mk("The flight leaves at 500 pm, I mean 5 pm.", 0.6),
  mk("Please don't call me before 9am.", 0.9),
  mk("Um um I think it's on the twelfth.", 0.68),
  mk("I need two thousand dollars, not two hundred.", 0.72),
  mk("Yes, yes, that's exactly right.", 0.91),
  mk("I want a refund for order number 4471.", 0.93),
  mk("She she told me to call back Thursday.", 0.8),
];
