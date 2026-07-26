import assert from "node:assert/strict";
import test from "node:test";

import {
  artifactIdFromLocation,
  pathForConversation,
  routeFromPath,
  urlForArtifact,
} from "../src/urlSync.ts";

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

test("builds and parses artifact workspace URLs", () => {
  const url = urlForArtifact(
    "1e263075-b1e8-4850-864b-263485755e6d",
    "pres_123",
  );
  assert.equal(
    url,
    "/c/1e263075-b1e8-4850-864b-263485755e6d?artifact=pres_123",
  );
  assert.equal(artifactIdFromLocation(url), "pres_123");
});

test("closing the artifact workspace removes only its query parameter", () => {
  assert.equal(
    urlForArtifact(
      "1e263075-b1e8-4850-864b-263485755e6d",
      null,
      "?artifact=pres_123&debug=1",
    ),
    "/c/1e263075-b1e8-4850-864b-263485755e6d?debug=1",
  );
});
