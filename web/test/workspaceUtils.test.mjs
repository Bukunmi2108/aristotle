import assert from "node:assert/strict";
import test from "node:test";

import {
  latestByPath,
  mergePresentations,
  parseCsv,
  presentedFromEvent,
  presentationsByMessage,
} from "../src/workspaceUtils.ts";

test("presentedFromEvent maps a workspace.present event", () => {
  const artifact = presentedFromEvent({
    type: "workspace.present",
    sequence: 1,
    timestamp: "now",
    artifact_id: "pres_1",
    path: "report.html",
    mime_type: "text/html",
    title: "Report",
    version: 2,
    message_id: "msg_1",
    created_at: "2026-07-26T10:00:00Z",
    size_bytes: 42,
  });
  assert.deepEqual(artifact, {
    id: "pres_1",
    path: "report.html",
    mimeType: "text/html",
    title: "Report",
    version: 2,
    messageId: "msg_1",
    createdAt: "2026-07-26T10:00:00Z",
    sizeBytes: 42,
  });
});

test("parseCsv handles quoted commas, escaped quotes, and embedded newlines", () => {
  assert.deepEqual(
    parseCsv('name,notes\nAda,"one, two"\nGrace,"said ""hello"""\nLinus,"a\nb"'),
    [
      ["name", "notes"],
      ["Ada", "one, two"],
      ["Grace", 'said "hello"'],
      ["Linus", "a\nb"],
    ],
  );
});

test("presentedFromEvent ignores non-present events and missing paths", () => {
  assert.equal(
    presentedFromEvent({ type: "message.delta", sequence: 1, timestamp: "t" }),
    null,
  );
  assert.equal(
    presentedFromEvent({ type: "workspace.present", sequence: 1, timestamp: "t" }),
    null,
  );
});

test("presentedFromEvent falls back to defaults", () => {
  const artifact = presentedFromEvent({
    type: "workspace.present",
    sequence: 1,
    timestamp: "t",
    path: "a.txt",
  });
  assert.equal(artifact.id, "a.txt-1");
  assert.equal(artifact.mimeType, "application/octet-stream");
  assert.equal(artifact.version, 1);
});

test("latestByPath keeps the highest version per path", () => {
  const result = latestByPath([
    { id: "1", path: "a.txt", mimeType: "text/plain", version: 1 },
    { id: "2", path: "b.png", mimeType: "image/png", version: 1 },
    { id: "3", path: "a.txt", mimeType: "text/plain", version: 2 },
  ]);
  assert.equal(result.length, 2);
  const a = result.find((item) => item.path === "a.txt");
  assert.equal(a.version, 2);
});

test("mergePresentations deduplicates by id and preserves chronological order", () => {
  const result = mergePresentations(
    [
      {
        id: "pres_1",
        path: "a.txt",
        mimeType: "text/plain",
        version: 1,
        createdAt: "2026-07-26T10:00:00Z",
      },
    ],
    {
      id: "pres_2",
      path: "a.txt",
      mimeType: "text/plain",
      version: 2,
      createdAt: "2026-07-26T10:05:00Z",
    },
  );
  assert.deepEqual(result.map((item) => item.id), ["pres_1", "pres_2"]);
  assert.equal(mergePresentations(result, result[1]).length, 2);
});

test("presentationsByMessage groups only presentations with provenance", () => {
  const grouped = presentationsByMessage([
    {
      id: "pres_1",
      path: "a.txt",
      mimeType: "text/plain",
      version: 1,
      messageId: "msg_1",
    },
    {
      id: "pres_2",
      path: "b.txt",
      mimeType: "text/plain",
      version: 1,
      messageId: "msg_1",
    },
    { id: "legacy", path: "old.txt", mimeType: "text/plain", version: 1 },
  ]);
  assert.deepEqual(
    grouped.get("msg_1").map((item) => item.id),
    ["pres_1", "pres_2"],
  );
  assert.equal(grouped.has(""), false);
});
