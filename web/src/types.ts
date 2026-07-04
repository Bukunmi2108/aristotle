export type ServiceName = "model" | "search";

export type ServiceStatus = {
  ok: boolean;
  service: ServiceName;
  url: string;
  latency_ms?: number | null;
  error?: string | null;
};

export type ServicesResponse = {
  model: ServiceStatus;
  search: ServiceStatus;
};

export type RunState =
  | "idle"
  | "connecting"
  | "warming"
  | "streaming"
  | "complete"
  | "error";

export type ClientUserMessage = {
  type: "user.message";
  message: string;
  conversation_id?: string;
  history?: ChatHistoryMessage[];
};

export type ChatHistoryMessage = {
  role: MessageRole;
  content: string;
};

export type ModelProviderState = {
  provider?: string | null;
  model?: string | null;
  url?: string | null;
  reason?: string | null;
  selectedLatencyMs?: number | null;
  firstTokenLatencyMs?: number | null;
  source: "status" | "event";
};

export type ToolResultPreview = {
  title?: string | null;
  url?: string | null;
  source?: string | null;
};

export type ServerEventType =
  | "session.started"
  | "service.checking"
  | "service.waking"
  | "service.ready"
  | "agent.started"
  | "model.selected"
  | "model.fallback"
  | "model.first_token"
  | "tool.started"
  | "tool.result"
  | "tool.error"
  | "reasoning.delta"
  | "message.delta"
  | "message.completed"
  | "session.completed"
  | "error";

export type ServerEvent = {
  type: ServerEventType;
  sequence: number;
  timestamp: string;
  conversation_id?: string;
  service?: string;
  provider?: string;
  model?: string;
  url?: string;
  tool?: string;
  input?: Record<string, unknown>;
  result_count?: number;
  result_preview?: ToolResultPreview[];
  text?: string;
  message?: string;
  code?: string;
  reason?: string;
  latency_ms?: number | null;
};

export type MessageRole = "user" | "assistant";

export type MessagePart =
  | {
      id: string;
      type: "text" | "reasoning";
      text: string;
      status?: "streaming" | "complete";
    }
  | {
      id: string;
      type: "tool";
      label: string;
      status: "running" | "complete" | "error";
      timestamp: string;
      input?: Record<string, unknown>;
      resultCount?: number;
      resultPreview?: ToolResultPreview[];
      message?: string;
    }
  | {
      id: string;
      type: "warning";
      text: string;
    };

export type ChatMessage = {
  id: string;
  role: MessageRole;
  content?: string;
  createdAt: string;
  status?: "streaming" | "complete" | "error" | "stopped";
  parts?: MessagePart[];
};

export type Conversation = {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: ChatMessage[];
};
