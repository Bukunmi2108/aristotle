import type {
  ClientUserMessage,
  FileUploadResponse,
  PresentedArtifact,
  ServerEvent,
  ServiceStatus,
  ServicesResponse,
  StoredConversation,
  StoredConversationResponse,
  StoredConversationsResponse,
  StoredMessagesResponse,
} from "./types";

const DEFAULT_HTTP_BASE_URL = "https://aristotle-api.duckdns.org";
const DEFAULT_WS_BASE_URL = "wss://aristotle-api.duckdns.org";

export const agentHttpBaseUrl = trimTrailingSlash(
  import.meta.env.VITE_AGENT_HTTP_BASE_URL || DEFAULT_HTTP_BASE_URL,
);

export const agentWsBaseUrl = trimTrailingSlash(
  import.meta.env.VITE_AGENT_WS_BASE_URL || DEFAULT_WS_BASE_URL,
);

// Separate origin for HTML previews (defence-in-depth). Falls back to the API
// origin, still safe because the preview iframe omits allow-same-origin.
export const previewBaseUrl = trimTrailingSlash(
  import.meta.env.VITE_PREVIEW_ORIGIN || agentHttpBaseUrl,
);

export function workspaceFileUrl(
  conversationId: string,
  path: string,
  options: { download?: boolean; preview?: boolean } = {},
): string {
  const params = new URLSearchParams({ path });
  if (options.download) {
    params.set("download", "1");
  }
  const base = options.preview ? previewBaseUrl : agentHttpBaseUrl;
  return `${base}/workspace/${encodeURIComponent(
    conversationId,
  )}/file?${params.toString()}`;
}

export function presentationContentUrl(
  presentationId: string,
  options: { download?: boolean; preview?: boolean } = {},
): string {
  const params = new URLSearchParams();
  if (options.download) {
    params.set("download", "1");
  }
  const base = options.preview ? previewBaseUrl : agentHttpBaseUrl;
  const query = params.toString();
  return `${base}/presentations/${encodeURIComponent(presentationId)}/content${
    query ? `?${query}` : ""
  }`;
}

export async function fetchPresentations(
  conversationId: string,
): Promise<PresentedArtifact[]> {
  const response = await fetch(
    `${agentHttpBaseUrl}/conversations/${encodeURIComponent(
      conversationId,
    )}/presentations`,
  );
  if (!response.ok) {
    throw new Error(`Presentations failed with ${response.status}`);
  }
  const payload = (await response.json()) as {
    presentations: Array<{
      id: string;
      path: string;
      mime_type: string;
      title?: string | null;
      version: number;
      message_id?: string | null;
      created_at?: string;
      size_bytes?: number;
    }>;
  };
  return payload.presentations.map((item) => ({
    id: item.id,
    path: item.path,
    mimeType: item.mime_type,
    title: item.title,
    version: item.version,
    messageId: item.message_id,
    createdAt: item.created_at,
    sizeBytes: item.size_bytes,
  }));
}

export async function fetchServices(): Promise<ServicesResponse> {
  const response = await fetch(`${agentHttpBaseUrl}/services`);
  if (!response.ok) {
    throw new Error(`Service status failed with ${response.status}`);
  }
  return response.json() as Promise<ServicesResponse>;
}

export async function fetchConversations(): Promise<StoredConversationsResponse> {
  const response = await fetch(`${agentHttpBaseUrl}/conversations`);
  if (!response.ok) {
    throw new Error(`Conversation history failed with ${response.status}`);
  }
  return response.json() as Promise<StoredConversationsResponse>;
}

export async function fetchConversation(
  conversationId: string,
): Promise<StoredConversation | null> {
  const response = await fetch(
    `${agentHttpBaseUrl}/conversations/${encodeURIComponent(conversationId)}`,
  );
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`Conversation failed with ${response.status}`);
  }
  const payload = (await response.json()) as StoredConversationResponse;
  return payload.conversation;
}

export async function fetchConversationMessages(
  conversationId: string,
): Promise<StoredMessagesResponse> {
  const response = await fetch(
    `${agentHttpBaseUrl}/conversations/${encodeURIComponent(conversationId)}/messages`,
  );
  if (!response.ok) {
    throw new Error(`Conversation messages failed with ${response.status}`);
  }
  return response.json() as Promise<StoredMessagesResponse>;
}

export async function uploadFile(
  file: File,
  conversationId?: string,
): Promise<FileUploadResponse> {
  const params = new URLSearchParams({ filename: file.name });
  if (conversationId) {
    params.set("conversation_id", conversationId);
  }
  const response = await fetch(`${agentHttpBaseUrl}/files?${params.toString()}`, {
    method: "POST",
    headers: { "Content-Type": file.type || "application/octet-stream" },
    body: file,
  });
  if (!response.ok) {
    throw new Error(await errorMessage(response, "File upload failed"));
  }
  return response.json() as Promise<FileUploadResponse>;
}

export async function deleteFile(fileId: string): Promise<void> {
  const response = await fetch(
    `${agentHttpBaseUrl}/files/${encodeURIComponent(fileId)}`,
    { method: "DELETE" },
  );
  if (!response.ok) {
    throw new Error(`Delete file failed with ${response.status}`);
  }
}

export async function renameConversation(
  conversationId: string,
  title: string,
): Promise<void> {
  const response = await fetch(
    `${agentHttpBaseUrl}/conversations/${encodeURIComponent(conversationId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    },
  );
  if (!response.ok) {
    throw new Error(`Rename conversation failed with ${response.status}`);
  }
}

export async function deleteConversation(conversationId: string): Promise<void> {
  const response = await fetch(
    `${agentHttpBaseUrl}/conversations/${encodeURIComponent(conversationId)}`,
    { method: "DELETE" },
  );
  if (!response.ok) {
    throw new Error(`Delete conversation failed with ${response.status}`);
  }
}

export type RunCreated = {
  run_id: string;
  conversation_id: string;
  user_message_id: string;
  assistant_message_id: string;
  status: string;
};

export async function startChatRun(
  payload: ClientUserMessage,
): Promise<RunCreated> {
  const response = await fetch(`${agentHttpBaseUrl}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await errorMessage(response, "Unable to start Aristotle"));
  }
  return response.json() as Promise<RunCreated>;
}

export async function cancelChatRun(runId: string): Promise<void> {
  const response = await fetch(
    `${agentHttpBaseUrl}/runs/${encodeURIComponent(runId)}`,
    { method: "DELETE" },
  );
  if (!response.ok) {
    throw new Error(await errorMessage(response, "Unable to cancel run"));
  }
}

export async function steerChatRun(runId: string, message: string): Promise<void> {
  const response = await fetch(
    `${agentHttpBaseUrl}/runs/${encodeURIComponent(runId)}/steer`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    },
  );
  if (!response.ok) {
    throw new Error(await errorMessage(response, "Unable to add instruction"));
  }
}

export async function streamRunEvents(
  runId: string,
  onEvent: (event: ServerEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  let afterEventId: string | undefined;
  let reconnectDelay = 400;

  while (!signal.aborted) {
    const params = new URLSearchParams();
    if (afterEventId) params.set("after_event_id", afterEventId);
    const query = params.toString();
    try {
      const response = await fetch(
        `${agentHttpBaseUrl}/runs/${encodeURIComponent(runId)}/events/stream${
          query ? `?${query}` : ""
        }`,
        { headers: { Accept: "text/event-stream" }, signal },
      );
      if (!response.ok || !response.body) {
        throw new Error(`Run event stream failed with ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let terminal = false;
      while (!signal.aborted) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        const blocks = buffer.split(/\r?\n\r?\n/);
        buffer = blocks.pop() || "";
        for (const block of blocks) {
          const parsed = parseServerEvent(block);
          if (!parsed) continue;
          afterEventId = parsed.event.event_id || parsed.id || afterEventId;
          onEvent(parsed.event);
          if (
            parsed.event.type === "session.completed" ||
            parsed.event.type === "error"
          ) {
            terminal = true;
          }
        }
        if (done || terminal) break;
      }
      if (terminal || signal.aborted) return;
      reconnectDelay = 400;
    } catch (error) {
      if (signal.aborted || (error instanceof DOMException && error.name === "AbortError")) {
        return;
      }
    }

    await abortableDelay(reconnectDelay, signal);
    reconnectDelay = Math.min(reconnectDelay * 2, 5_000);
  }
}

function parseServerEvent(
  block: string,
): { id?: string; event: ServerEvent } | null {
  if (!block || block.startsWith(":")) return null;
  let id: string | undefined;
  const data: string[] = [];
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith("id:")) id = line.slice(3).trim();
    if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  if (!data.length) return null;
  try {
    return { id, event: JSON.parse(data.join("\n")) as ServerEvent };
  } catch {
    return null;
  }
}

function abortableDelay(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) return resolve();
    const timer = window.setTimeout(resolve, milliseconds);
    signal.addEventListener(
      "abort",
      () => {
        window.clearTimeout(timer);
        resolve();
      },
      { once: true },
    );
  });
}

export function connectChat(
  payload: ClientUserMessage,
  onEvent: (event: ServerEvent) => void,
  onClose: () => void,
  onError: (message: string) => void,
): WebSocket {
  const socket = new WebSocket(`${agentWsBaseUrl}/ws/chat`);

  socket.addEventListener("open", () => {
    socket.send(JSON.stringify(payload));
  });

  socket.addEventListener("message", (message) => {
    try {
      onEvent(JSON.parse(message.data) as ServerEvent);
    } catch {
      onError("Received an unreadable event from Aristotle.");
    }
  });

  socket.addEventListener("error", () => {
    onError("WebSocket connection failed.");
  });

  socket.addEventListener("close", () => {
    onClose();
  });

  return socket;
}

export function serviceSummary(status: ServiceStatus): string {
  if (!status.ok) {
    return status.error || "Unavailable";
  }
  if (status.latency_ms === null || status.latency_ms === undefined) {
    return "Ready";
  }
  return `${status.latency_ms} ms`;
}

function trimTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

async function errorMessage(
  response: Response,
  fallback: string,
): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === "string") {
      return payload.detail;
    }
  } catch {
    // Use the fallback below when the response body is not JSON.
  }
  return `${fallback} with ${response.status}`;
}
