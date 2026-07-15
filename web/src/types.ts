export type ServiceName = "model" | "search";

export type ServiceStatus = {
  ok: boolean;
  service: ServiceName;
  url: string;
  model?: string | null;
  latency_ms?: number | null;
  error?: string | null;
};

export type ServicesResponse = {
  model: ServiceStatus;
  search: ServiceStatus;
  poll_interval_seconds?: number | null;
  wake_timeout_seconds?: number | null;
};

export type StoredConversation = {
  id: string;
  title: string;
  status: string;
  created_at: string;
  updated_at: string;
};

export type StoredMessage = {
  id: string;
  conversation_id: string;
  role: MessageRole;
  content?: string | null;
  status: "streaming" | "complete" | "error" | "stopped" | string;
  parent_message_id?: string | null;
  created_at: string;
  completed_at?: string | null;
  attachments?: MessageAttachment[];
};

export type StoredConversationsResponse = {
  conversations: StoredConversation[];
};

export type StoredConversationResponse = {
  conversation: StoredConversation;
};

export type StoredMessagesResponse = {
  messages: StoredMessage[];
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
  options?: {
    max_search_results?: number;
    file_ids?: string[];
  };
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

export type SourcePreview = {
  id?: string;
  citationIndex?: number;
  title?: string | null;
  url?: string | null;
  domain?: string | null;
  source?: string | null;
  source_type?: "web" | "document" | string | null;
  sourceType?: "web" | "document" | string | null;
  file_id?: string | null;
  fileId?: string | null;
  chunk_id?: string | null;
  chunkId?: string | null;
  locator?: string | null;
  page?: number | null;
  section?: string | null;
  row_start?: number | null;
  rowStart?: number | null;
  row_end?: number | null;
  rowEnd?: number | null;
  snippet?: string | null;
  status?: "searched" | "fetched" | "ranked" | "cited" | "failed" | string;
  marker?: string | null;
  tool?: string | null;
};

export type ToolResultPreview = SourcePreview;

export type ArtifactRef = {
  id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
};

export type ToolOutput = {
  status: "ok" | "error" | "timeout" | "rejected";
  stdout: string;
  stderr: string;
  exit_code: number;
  timed_out: boolean;
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
  artifacts?: ArtifactRef[];
  output?: ToolOutput;
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
      artifacts?: ArtifactRef[];
      output?: ToolOutput;
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
  attachments?: MessageAttachment[];
  parts?: MessagePart[];
  sources?: SourcePreview[];
  metrics?: MessageMetrics;
};

export type MessageMetrics = {
  ttftMs?: number | null;
  durationMs?: number | null;
  outputTokens?: number | null;
  tps?: number | null;
  tokenSource?: "server" | "estimated";
  startedAt?: string | null;
  firstTokenAt?: string | null;
};

export type Conversation = {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: ChatMessage[];
};

export type FileRecord = {
  id: string;
  owner_id?: string | null;
  filename: string;
  mime_type: string;
  size_bytes: number;
  storage_path: string;
  uploaded_at: string;
  parse_status: "pending" | "parsed" | "failed" | string;
  parse_error?: string | null;
};

export type MessageAttachment = {
  id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  parse_status: "pending" | "parsed" | "failed" | string;
  parse_error?: string | null;
};

export type FileUploadResponse = {
  file: FileRecord;
};
