import type { PresentedArtifact, ServerEvent } from "./types";

// Map a `workspace.present` event to an artifact, or null if it lacks a path.
export function presentedFromEvent(event: ServerEvent): PresentedArtifact | null {
  if (event.type !== "workspace.present" || !event.path) {
    return null;
  }
  const version = event.version ?? 1;
  return {
    id: event.artifact_id || `${event.path}-${version}`,
    path: event.path,
    mimeType: event.mime_type || "application/octet-stream",
    title: event.title ?? null,
    version,
    messageId: event.message_id ?? null,
    createdAt: event.created_at ?? event.timestamp,
    sizeBytes: event.size_bytes,
  };
}

// Collapse a presentation list to one entry per path, keeping the highest
// version seen. Used to render the panel's distinct presented files.
export function latestByPath(
  artifacts: PresentedArtifact[],
): PresentedArtifact[] {
  const byPath = new Map<string, PresentedArtifact>();
  for (const artifact of artifacts) {
    const existing = byPath.get(artifact.path);
    if (!existing || artifact.version >= existing.version) {
      byPath.set(artifact.path, artifact);
    }
  }
  return [...byPath.values()];
}

export function mergePresentations(
  artifacts: PresentedArtifact[],
  incoming: PresentedArtifact,
): PresentedArtifact[] {
  const existingIndex = artifacts.findIndex((artifact) => artifact.id === incoming.id);
  if (existingIndex >= 0) {
    const next = [...artifacts];
    next[existingIndex] = incoming;
    return next;
  }
  return [...artifacts, incoming].sort((left, right) =>
    (left.createdAt || "").localeCompare(right.createdAt || ""),
  );
}

export function presentationsByMessage(
  artifacts: PresentedArtifact[],
): Map<string, PresentedArtifact[]> {
  const grouped = new Map<string, PresentedArtifact[]>();
  for (const artifact of artifacts) {
    if (!artifact.messageId) continue;
    const current = grouped.get(artifact.messageId) || [];
    grouped.set(artifact.messageId, [...current, artifact]);
  }
  return grouped;
}

export function parseCsv(text: string): string[][] {
  if (!text) return [];
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (quoted) {
      if (char === '"' && text[index + 1] === '"') {
        cell += '"';
        index += 1;
      } else if (char === '"') {
        quoted = false;
      } else {
        cell += char;
      }
      continue;
    }
    if (char === '"' && cell.length === 0) {
      quoted = true;
    } else if (char === ",") {
      row.push(cell);
      cell = "";
    } else if (char === "\n") {
      row.push(cell.replace(/\r$/, ""));
      rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += char;
    }
  }
  if (cell || row.length) {
    row.push(cell.replace(/\r$/, ""));
    rows.push(row);
  }
  return rows;
}
