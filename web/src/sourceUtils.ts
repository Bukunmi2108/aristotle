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
  if (isDocumentSource(preview)) {
    const chunkId = preview.chunk_id || preview.chunkId || preview.id || null;
    const fileId = preview.file_id || preview.fileId || null;
    const locator = preview.locator || documentLocator(preview);
    return {
      ...preview,
      id: chunkId || fileId || preview.id,
      source_type: "document",
      sourceType: "document",
      file_id: fileId,
      fileId,
      chunk_id: chunkId,
      chunkId,
      locator,
      title: preview.title || "Uploaded file",
      domain: locator || "Uploaded file",
      status: preview.status || sourceStatusForTool(toolName),
      tool: preview.tool || toolName || null,
    };
  }

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
  const byKey = new Map<string, SourcePreview>();

  for (const source of current) {
    const normalized = normalizeSourcePreview(source);
    if (!normalized) continue;
    byKey.set(sourceKey(normalized), normalized);
  }

  for (const source of incoming) {
    const normalized = normalizeSourcePreview(source);
    if (!normalized) continue;
    const key = sourceKey(normalized);
    const existing = byKey.get(key);
    byKey.set(key, {
      ...existing,
      ...normalized,
      title: normalized.title || existing?.title,
      domain: normalized.domain || existing?.domain,
      snippet: normalized.snippet || existing?.snippet,
      source: normalized.source || existing?.source,
      citationIndex: existing?.citationIndex,
    });
  }

  return Array.from(byKey.values()).map((source, index) => ({
    ...source,
    citationIndex: source.citationIndex ?? index + 1,
  }));
}

export function sameSourceUrl(first: string, second: string): boolean {
  return canonicalSourceUrl(first) === canonicalSourceUrl(second);
}

export function isDocumentSource(source: SourcePreview): boolean {
  return (
    source.sourceType === "document" ||
    source.source_type === "document" ||
    Boolean(source.file_id || source.fileId || source.chunk_id || source.chunkId)
  );
}

function sourceKey(source: SourcePreview): string {
  if (isDocumentSource(source)) {
    return (
      source.chunk_id ||
      source.chunkId ||
      source.id ||
      source.file_id ||
      source.fileId ||
      "document"
    );
  }
  return source.url ? canonicalSourceUrl(source.url) : source.id || "source";
}

function documentLocator(source: SourcePreview): string | null {
  if (source.locator) return source.locator;
  if (source.page !== null && source.page !== undefined) return `page ${source.page}`;
  if (
    source.row_start !== null &&
    source.row_start !== undefined &&
    source.row_end !== null &&
    source.row_end !== undefined
  ) {
    return `rows ${source.row_start}-${source.row_end}`;
  }
  if (
    source.rowStart !== null &&
    source.rowStart !== undefined &&
    source.rowEnd !== null &&
    source.rowEnd !== undefined
  ) {
    return `rows ${source.rowStart}-${source.rowEnd}`;
  }
  if (source.section) return source.section;
  return null;
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
