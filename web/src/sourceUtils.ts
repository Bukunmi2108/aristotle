import type { ChatMessage, SourcePreview, ToolResultPreview } from "./types";

export function sourcesFromMessage(message: ChatMessage): SourcePreview[] {
  const toolSources =
    message.parts
      ?.flatMap((part) => (part.type === "tool" ? part.resultPreview ?? [] : []))
      .map((preview) => normalizeSourcePreview(preview))
      .filter((source): source is SourcePreview => Boolean(source)) ?? [];

  return mergeSources(message.sources ?? [], toolSources);
}

export function normalizeSourcePreview(
  preview: ToolResultPreview,
  toolName?: string,
): SourcePreview | null {
  if (!preview.url || !isLikelyHttpUrl(preview.url)) {
    return null;
  }

  const domain = preview.domain || domainFromUrl(preview.url);
  return {
    ...preview,
    id: preview.id || canonicalSourceUrl(preview.url),
    domain,
    title: preview.title || domain || preview.url,
    status: preview.status || sourceStatusForTool(toolName),
    tool: preview.tool || toolName || null,
  };
}

export function mergeSources(
  current: SourcePreview[],
  incoming: SourcePreview[],
): SourcePreview[] {
  const byUrl = new Map<string, SourcePreview>();

  for (const source of current) {
    const normalized = normalizeSourcePreview(source);
    if (!normalized?.url) continue;
    byUrl.set(canonicalSourceUrl(normalized.url), normalized);
  }

  for (const source of incoming) {
    const normalized = normalizeSourcePreview(source);
    if (!normalized?.url) continue;
    const key = canonicalSourceUrl(normalized.url);
    const existing = byUrl.get(key);
    byUrl.set(key, {
      ...existing,
      ...normalized,
      title: normalized.title || existing?.title,
      domain: normalized.domain || existing?.domain,
      snippet: normalized.snippet || existing?.snippet,
      source: normalized.source || existing?.source,
      citationIndex: existing?.citationIndex,
    });
  }

  return Array.from(byUrl.values()).map((source, index) => ({
    ...source,
    citationIndex: source.citationIndex ?? index + 1,
  }));
}

export function sameSourceUrl(first: string, second: string): boolean {
  return canonicalSourceUrl(first) === canonicalSourceUrl(second);
}

function isLikelyHttpUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

function canonicalSourceUrl(value: string): string {
  try {
    const url = new URL(value);
    url.hash = "";
    for (const key of Array.from(url.searchParams.keys())) {
      if (key.toLowerCase().startsWith("utm_")) {
        url.searchParams.delete(key);
      }
    }
    url.hostname = url.hostname.toLowerCase();
    url.pathname = url.pathname.replace(/\/+$/, "") || "/";
    return url.toString();
  } catch {
    return value;
  }
}

function domainFromUrl(value: string): string | null {
  try {
    return new URL(value).hostname.replace(/^www\./, "");
  } catch {
    return null;
  }
}

function sourceStatusForTool(toolName?: string): SourcePreview["status"] {
  const normalized = (toolName || "").toLowerCase();
  if (normalized.includes("fetch")) return "fetched";
  if (normalized.includes("rank")) return "ranked";
  if (normalized.includes("citation")) return "cited";
  return "searched";
}
