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
    }>;
  };
  return payload.presentations.map((item) => ({
    id: item.id,
    path: item.path,
    mimeType: item.mime_type,
    title: item.title,
    version: item.version,
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
