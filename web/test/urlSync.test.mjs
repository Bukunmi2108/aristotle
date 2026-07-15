import assert from "node:assert/strict";
import test from "node:test";

import { pathForConversation, routeFromPath } from "../src/urlSync.ts";

const conversationId = "123e4567-e89b-12d3-a456-426614174000";

test("parses the root path as a new chat", () => {
  assert.deepEqual(routeFromPath("/"), { type: "new" });
});

test("parses a UUID conversation path", () => {
  assert.deepEqual(routeFromPath(`/c/${conversationId}`), {
    type: "conversation",
    conversationId,
  });
});

test("rejects malformed and unrelated paths", () => {
  assert.deepEqual(routeFromPath("/c/not-a-uuid"), { type: "invalid" });
  assert.deepEqual(routeFromPath(`/c/${conversationId}/messages`), {
    type: "invalid",
  });
  assert.deepEqual(routeFromPath("/settings"), { type: "invalid" });
});

test("builds a conversation path", () => {
  assert.equal(pathForConversation(conversationId), `/c/${conversationId}`);
});
