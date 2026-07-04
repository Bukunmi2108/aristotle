import type {
  ClientUserMessage,
  ServerEvent,
  ServiceStatus,
  ServicesResponse,
  StoredConversationsResponse,
  StoredMessagesResponse,
} from "./types";

const DEFAULT_HTTP_BASE_URL = "https://bukunmi2108-aristotle-api.hf.space";
const DEFAULT_WS_BASE_URL = "wss://bukunmi2108-aristotle-api.hf.space";

export const agentHttpBaseUrl = trimTrailingSlash(
  import.meta.env.VITE_AGENT_HTTP_BASE_URL || DEFAULT_HTTP_BASE_URL,
);

export const agentWsBaseUrl = trimTrailingSlash(
  import.meta.env.VITE_AGENT_WS_BASE_URL || DEFAULT_WS_BASE_URL,
);

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
