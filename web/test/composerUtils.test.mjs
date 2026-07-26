import assert from "node:assert/strict";
import test from "node:test";

import {
  MAX_PROMPT_LENGTH,
  insertPastedText,
  promptCharactersRemaining,
  shouldSubmitComposerKey,
} from "../src/composerUtils.ts";

test("promptCharactersRemaining matches the server prompt limit", () => {
  assert.equal(MAX_PROMPT_LENGTH, 12_000);
  assert.equal(promptCharactersRemaining("Aristotle"), 11_991);
  assert.equal(promptCharactersRemaining("x".repeat(MAX_PROMPT_LENGTH)), 0);
});

test("Enter submits while Shift+Enter preserves a newline", () => {
  assert.equal(
    shouldSubmitComposerKey({
      key: "Enter",
      shiftKey: false,
      isComposing: false,
    }),
    true,
  );
  assert.equal(
    shouldSubmitComposerKey({
      key: "Enter",
      shiftKey: true,
      isComposing: false,
    }),
    false,
  );
});

test("IME composition and non-Enter keys do not submit", () => {
  assert.equal(
    shouldSubmitComposerKey({
      key: "Enter",
      shiftKey: false,
      isComposing: true,
    }),
    false,
  );
  assert.equal(
    shouldSubmitComposerKey({
      key: "a",
      shiftKey: false,
      isComposing: false,
    }),
    false,
  );
});

test("paste inserts text at the current selection", () => {
  assert.deepEqual(insertPastedText("Ask old thing", "a new", 4, 7), {
    value: "Ask a new thing",
    cursor: 9,
    truncated: false,
  });
});

test("paste accepts as much text as the server prompt limit allows", () => {
  const prefix = "x".repeat(MAX_PROMPT_LENGTH - 2);
  const insertion = insertPastedText(prefix, "abcd", prefix.length, prefix.length);
  assert.equal(insertion.value, `${prefix}ab`);
  assert.equal(insertion.cursor, MAX_PROMPT_LENGTH);
  assert.equal(insertion.truncated, true);
});

test("paste can replace selected text at the prompt limit", () => {
  const value = "x".repeat(MAX_PROMPT_LENGTH);
  const insertion = insertPastedText(value, "hello", 100, 105);
  assert.equal(insertion.value.length, MAX_PROMPT_LENGTH);
  assert.equal(insertion.value.slice(100, 105), "hello");
  assert.equal(insertion.truncated, false);
});
