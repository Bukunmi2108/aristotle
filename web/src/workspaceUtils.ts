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
