import assert from "node:assert/strict";
import test from "node:test";

import { latestByPath, presentedFromEvent } from "../src/workspaceUtils.ts";

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
  });
  assert.deepEqual(artifact, {
    id: "pres_1",
    path: "report.html",
    mimeType: "text/html",
    title: "Report",
    version: 2,
  });
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
