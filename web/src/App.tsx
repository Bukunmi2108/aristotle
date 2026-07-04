import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import {
  connectChat,
  deleteConversation as deleteServerConversation,
  fetchConversationMessages,
  fetchConversations,
  fetchServices,
  renameConversation as renameServerConversation,
} from "./api";
import {
  AppHeader,
  Composer,
  HistorySidebar,
  MessageList,
  ServiceAlert,
} from "./components";
import {
  createConversation,
  loadConversations,
  saveConversations,
  titleFromPrompt,
} from "./storage";
import type {
  ChatHistoryMessage,
  ChatMessage,
  Conversation,
  MessagePart,
  ModelProviderState,
  RunState,
  ServerEvent,
  ServicesResponse,
  StoredConversation,
  StoredMessage,
  ToolResultPreview,
} from "./types";

const MAX_HISTORY_MESSAGES = 24;
const MAX_HISTORY_CHARS = 24_000;

function App() {
  const [conversations, setConversations] = useState<Conversation[]>(() => {
    const stored = loadConversations();
    return stored.length ? stored : [createConversation()];
  });
  const [activeId, setActiveId] = useState(() => conversations[0]?.id ?? "");
  const [services, setServices] = useState<ServicesResponse | null>(null);
  const [serviceError, setServiceError] = useState<string | null>(null);
  const [composer, setComposer] = useState("");
  const [runState, setRunState] = useState<RunState>("idle");
  const [modelProvider, setModelProvider] =
    useState<ModelProviderState | null>(null);
  const [detailsOpen, setDetailsOpen] = useState<Record<string, boolean>>({});
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);
  const activeAssistantIdRef = useRef<string | null>(null);

  const activeConversation = useMemo(
    () => conversations.find((conversation) => conversation.id === activeId),
    [activeId, conversations],
  );

  useEffect(() => {
    saveConversations(conversations);
  }, [conversations]);

  useEffect(() => {
    void refreshServices();
    void hydrateServerHistory();
  }, []);

  useEffect(() => {
    const scrollTarget = document.getElementById("conversation-end");
    scrollTarget?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [activeConversation?.messages]);

  async function refreshServices() {
    try {
      setServiceError(null);
      const nextServices = await fetchServices();
      setServices(nextServices);
      setModelProvider((current) =>
        current?.source === "event" ? current : providerFromServices(nextServices),
      );
    } catch (error) {
      setServiceError(
        error instanceof Error ? error.message : "Status check failed.",
      );
    }
  }

  async function hydrateServerHistory() {
    try {
      const response = await fetchConversations();
      if (!response.conversations.length) {
        return;
      }

      const hydrated = await Promise.all(
        response.conversations.map(async (conversation) => {
          const messages = await fetchConversationMessages(conversation.id);
          return conversationFromServer(conversation, messages.messages);
        }),
      );

      setConversations(hydrated);
      setActiveId((current) =>
        hydrated.some((conversation) => conversation.id === current)
          ? current
          : hydrated[0]?.id || "",
      );
    } catch {
      // Persistence is optional in local/dev deployments. Browser storage remains
      // the fallback when the server has no DB configured yet.
    }
  }

  function updateConversation(
    conversationId: string,
    updater: (conversation: Conversation) => Conversation,
  ) {
    setConversations((current) =>
      current.map((conversation) =>
        conversation.id === conversationId
          ? updater(conversation)
          : conversation,
      ),
    );
  }

  function createNewChat() {
    stopStream("stopped");
    const conversation = createConversation();
    setConversations((current) => [conversation, ...current]);
    setActiveId(conversation.id);
    setComposer("");
    setRunState("idle");
    setSidebarOpen(false);
  }

  function selectConversation(conversationId: string) {
    if (conversationId === activeId) {
      setSidebarOpen(false);
      return;
    }
    stopStream("stopped");
    setActiveId(conversationId);
    setRunState("idle");
    setSidebarOpen(false);
  }

  async function renameConversationById(conversationId: string, title: string) {
    const conversation = conversations.find((item) => item.id === conversationId);
    if (!conversation) return;

    const cleaned = title.trim();
    if (!cleaned || cleaned === conversation.title) {
      return;
    }

    updateConversation(conversationId, (current) => ({
      ...current,
      title: cleaned,
      updatedAt: new Date().toISOString(),
    }));

    try {
      await renameServerConversation(conversationId, cleaned);
    } catch {
      // Local history still supports rename when server persistence is disabled.
    }
  }

  async function deleteConversationById(conversationId: string) {
    const conversation = conversations.find((item) => item.id === conversationId);
    if (!conversation) return;
    if (!window.confirm(`Delete "${conversation.title}"?`)) {
      return;
    }

    const deletedId = conversation.id;
    const deletedActiveConversation = deletedId === activeId;
    if (deletedActiveConversation) {
      stopStream("stopped");
    }

    const remaining = conversations.filter(
      (conversation) => conversation.id !== deletedId,
    );
    const nextConversations = remaining.length ? remaining : [createConversation()];
    setConversations(nextConversations);
    if (deletedActiveConversation) {
      setActiveId(nextConversations[0]?.id || "");
      setRunState("idle");
    }
    setSidebarOpen(false);

    try {
      await deleteServerConversation(deletedId);
    } catch {
      // Local history still supports deletion when server persistence is disabled.
    }
  }

  function submitMessage(event: FormEvent) {
    event.preventDefault();
    const prompt = composer.trim();
    if (
      !prompt ||
      !activeConversation ||
      runState === "streaming" ||
      runState === "connecting"
    ) {
      return;
    }

    stopStream("stopped");
    const history = buildChatHistory(activeConversation.messages);

    const now = new Date().toISOString();
    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: prompt,
      createdAt: now,
      status: "complete",
    };
    const assistantMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "assistant",
      createdAt: now,
      status: "streaming",
      parts: [],
    };

    activeAssistantIdRef.current = assistantMessage.id;
    setComposer("");
    setRunState("connecting");

    updateConversation(activeConversation.id, (conversation) => ({
      ...conversation,
      title: conversation.messages.length
        ? conversation.title
        : titleFromPrompt(prompt),
      updatedAt: now,
      messages: [...conversation.messages, userMessage, assistantMessage],
    }));

    socketRef.current = connectChat(
      {
        type: "user.message",
        message: prompt,
        conversation_id: activeConversation.id,
        history,
      },
      (serverEvent) =>
        handleServerEvent(
          activeConversation.id,
          assistantMessage.id,
          serverEvent,
        ),
      () => {
        socketRef.current = null;
      },
      (message) => {
        appendWarning(activeConversation.id, assistantMessage.id, message);
        setRunState("error");
      },
    );
  }

  function handleServerEvent(
    conversationId: string,
    assistantId: string,
    event: ServerEvent,
  ) {
    if (event.type === "service.checking" || event.type === "service.waking") {
      setRunState("warming");
      appendTool(conversationId, assistantId, {
        id: `${event.type}-${event.sequence}`,
        type: "tool",
        label: event.service
          ? `${event.service} ${event.type.split(".")[1]}`
          : event.type,
        status: "running",
        timestamp: event.timestamp,
      });
      return;
    }

    if (event.type === "service.ready") {
      setRunState("streaming");
      completeServiceStatus(
        conversationId,
        assistantId,
        event.service,
        event.timestamp,
      );
      return;
    }

    if (event.type === "agent.started") {
      setRunState("streaming");
      return;
    }

    if (event.type === "model.fallback") {
      setModelProvider({
        provider: "fallback",
        model: event.model,
        url: event.url,
        reason: event.reason,
        selectedLatencyMs: event.latency_ms,
        source: "event",
      });
      return;
    }

    if (event.type === "model.selected") {
      setModelProvider((current) => ({
        provider: event.provider,
        model: event.model,
        url: event.url,
        reason: current?.reason,
        selectedLatencyMs: event.latency_ms,
        firstTokenLatencyMs: current?.firstTokenLatencyMs,
        source: "event",
      }));
      return;
    }

    if (event.type === "model.first_token") {
      setModelProvider((current) => ({
        provider: event.provider || current?.provider,
        model: event.model || current?.model,
        url: event.url || current?.url,
        reason: current?.reason,
        selectedLatencyMs: current?.selectedLatencyMs,
        firstTokenLatencyMs: event.latency_ms,
        source: "event",
      }));
      return;
    }

    if (event.type === "tool.started") {
      appendTool(conversationId, assistantId, {
        id: `${event.type}-${event.sequence}`,
        type: "tool",
        label: event.tool || "tool",
        status: "running",
        timestamp: event.timestamp,
        input: event.input,
      });
      return;
    }

    if (event.type === "tool.result") {
      completeTool(
        conversationId,
        assistantId,
        event.tool,
        event.result_count,
        event.result_preview,
      );
      return;
    }

    if (event.type === "tool.error") {
      failTool(
        conversationId,
        assistantId,
        event.tool,
        event.message || "Tool failed.",
      );
      return;
    }

    if (event.type === "reasoning.delta" && event.text) {
      appendTextPart(conversationId, assistantId, "reasoning", event.text);
      return;
    }

    if (event.type === "message.delta" && event.text) {
      appendTextPart(conversationId, assistantId, "text", event.text);
      return;
    }

    if (event.type === "message.completed") {
      completeAssistant(conversationId, assistantId, event.message || "");
      return;
    }

    if (event.type === "session.completed") {
      setRunState("complete");
      socketRef.current?.close();
      socketRef.current = null;
      activeAssistantIdRef.current = null;
      return;
    }

    if (event.type === "error") {
      appendWarning(
        conversationId,
        assistantId,
        event.message || event.code || "Run failed.",
      );
      completeAssistant(conversationId, assistantId, "", "error");
      setRunState("error");
    }
  }

  function updateAssistantParts(
    conversationId: string,
    assistantId: string,
    updater: (parts: MessagePart[]) => MessagePart[],
  ) {
    updateConversation(conversationId, (conversation) => ({
      ...conversation,
      updatedAt: new Date().toISOString(),
      messages: conversation.messages.map((message) =>
        message.id === assistantId
          ? { ...message, parts: updater(message.parts ?? []) }
          : message,
      ),
    }));
  }

  function appendTool(
    conversationId: string,
    assistantId: string,
    part: MessagePart,
  ) {
    updateAssistantParts(conversationId, assistantId, (parts) => [
      ...parts,
      part,
    ]);
  }

  function completeTool(
    conversationId: string,
    assistantId: string,
    toolName?: string,
    resultCount?: number,
    resultPreview?: ToolResultPreview[],
  ) {
    updateAssistantParts(conversationId, assistantId, (parts) => {
      const next = [...parts];
      const index = findLastToolIndex(next, toolName, "running");
      if (index >= 0 && next[index].type === "tool") {
        next[index] = {
          ...next[index],
          status: "complete",
          resultCount,
          resultPreview,
        };
      } else {
        next.push({
          id: `tool-result-${crypto.randomUUID()}`,
          type: "tool",
          label: toolName || "tool",
          status: "complete",
          timestamp: new Date().toISOString(),
          resultCount,
          resultPreview,
        });
      }
      return next;
    });
  }

  function completeServiceStatus(
    conversationId: string,
    assistantId: string,
    service?: string,
    timestamp?: string,
  ) {
    updateAssistantParts(conversationId, assistantId, (parts) => {
      const next = [...parts];
      const labels = service
        ? [`${service} checking`, `${service} waking`]
        : ["service.checking", "service.waking"];
      const index = findLastServiceStatusIndex(next, labels);
      const readyLabel = service ? `${service} ready` : "service ready";

      if (index >= 0 && next[index].type === "tool") {
        next[index] = {
          ...next[index],
          label: readyLabel,
          status: "complete",
          timestamp: timestamp || next[index].timestamp,
        };
      } else {
        next.push({
          id: `service-ready-${crypto.randomUUID()}`,
          type: "tool",
          label: readyLabel,
          status: "complete",
          timestamp: timestamp || new Date().toISOString(),
        });
      }

      return next;
    });
  }

  function failTool(
    conversationId: string,
    assistantId: string,
    toolName?: string,
    message?: string,
  ) {
    updateAssistantParts(conversationId, assistantId, (parts) => {
      const next = [...parts];
      const index = findLastToolIndex(next, toolName, "running");
      if (index >= 0 && next[index].type === "tool") {
        next[index] = {
          ...next[index],
          status: "error",
          message,
        };
      } else {
        next.push({
          id: `tool-error-${crypto.randomUUID()}`,
          type: "tool",
          label: toolName || "tool",
          status: "error",
          timestamp: new Date().toISOString(),
          message,
        });
      }
      return next;
    });
  }

  function appendTextPart(
    conversationId: string,
    assistantId: string,
    type: "reasoning" | "text",
    text: string,
  ) {
    updateAssistantParts(conversationId, assistantId, (parts) => {
      const last = parts[parts.length - 1];
      if (last?.type === type) {
        return [
          ...parts.slice(0, -1),
          { ...last, text: `${last.text}${text}`, status: "streaming" },
        ];
      }
      return [
        ...parts,
        {
          id: `${type}-${crypto.randomUUID()}`,
          type,
          text,
          status: "streaming",
        },
      ];
    });
  }

  function appendWarning(
    conversationId: string,
    assistantId: string,
    text: string,
  ) {
    updateAssistantParts(conversationId, assistantId, (parts) => [
      ...parts,
      { id: `warning-${crypto.randomUUID()}`, type: "warning", text },
    ]);
  }

  function completeAssistant(
    conversationId: string,
    assistantId: string,
    content: string,
    status: "complete" | "error" = "complete",
  ) {
    updateConversation(conversationId, (conversation) => ({
      ...conversation,
      updatedAt: new Date().toISOString(),
      messages: conversation.messages.map((message) =>
        message.id === assistantId
          ? {
              ...message,
              content,
              status,
              parts: (message.parts ?? []).map((part) =>
                part.type === "text" || part.type === "reasoning"
                  ? { ...part, status: "complete" }
                  : part,
              ),
            }
          : message,
      ),
    }));
  }

  function stopStream(status: "stopped" | "complete" = "stopped") {
    const hadSocket = socketRef.current !== null;
    socketRef.current?.close();
    socketRef.current = null;

    if (hadSocket && activeConversation && activeAssistantIdRef.current) {
      const assistantId = activeAssistantIdRef.current;
      updateConversation(activeConversation.id, (conversation) => ({
        ...conversation,
        updatedAt: new Date().toISOString(),
        messages: conversation.messages.map((message) =>
          message.id === assistantId ? { ...message, status } : message,
        ),
      }));
    }

    activeAssistantIdRef.current = null;
    setRunState("idle");
  }

  async function copyMessage(message: ChatMessage) {
    const text = message.content || textFromParts(message.parts ?? []);
    if (text) {
      await navigator.clipboard.writeText(text);
    }
  }

  const isRunning =
    runState === "connecting" ||
    runState === "warming" ||
    runState === "streaming";

  return (
    <main className="app-root">
      <HistorySidebar
        isOpen={sidebarOpen}
        conversations={conversations}
        activeConversationId={activeId}
        onClose={() => setSidebarOpen(false)}
        onNewChat={createNewChat}
        onSelectConversation={selectConversation}
        onRenameConversation={(conversationId, title) =>
          void renameConversationById(conversationId, title)
        }
        onDeleteConversation={(conversationId) =>
          void deleteConversationById(conversationId)
        }
      />
      <section className="app-shell">
        <AppHeader
          runState={runState}
          services={services}
          modelProvider={modelProvider}
          onOpenSidebar={() => setSidebarOpen(true)}
          onNewChat={createNewChat}
        />

        {serviceError && <ServiceAlert>{serviceError}</ServiceAlert>}

        <MessageList
          conversation={activeConversation}
          detailsOpen={detailsOpen}
          setDetailsOpen={setDetailsOpen}
          onCopyMessage={(message) => void copyMessage(message)}
          onPickPrompt={setComposer}
        />

        <Composer
          composer={composer}
          isRunning={isRunning}
          setComposer={setComposer}
          onSubmit={submitMessage}
          onStop={() => stopStream("stopped")}
        />
      </section>
    </main>
  );
}

function findLastToolIndex(
  parts: MessagePart[],
  toolName?: string,
  status?: "running" | "complete" | "error",
) {
  for (let index = parts.length - 1; index >= 0; index -= 1) {
    const part = parts[index];
    if (
      part.type === "tool" &&
      (!toolName || part.label === toolName) &&
      (!status || part.status === status)
    ) {
      return index;
    }
  }
  return -1;
}

function findLastServiceStatusIndex(parts: MessagePart[], labels: string[]) {
  for (let index = parts.length - 1; index >= 0; index -= 1) {
    const part = parts[index];
    if (
      part.type === "tool" &&
      part.status === "running" &&
      labels.includes(part.label)
    ) {
      return index;
    }
  }
  return -1;
}

function conversationFromServer(
  conversation: StoredConversation,
  messages: StoredMessage[],
): Conversation {
  return {
    id: conversation.id,
    title: conversation.title,
    createdAt: conversation.created_at,
    updatedAt: conversation.updated_at,
    messages: messages.map(messageFromServer),
  };
}

function messageFromServer(message: StoredMessage): ChatMessage {
  return {
    id: message.id,
    role: message.role,
    content: message.content || "",
    createdAt: message.created_at,
    status: normalizeMessageStatus(message.status),
    parts:
      message.role === "assistant" && message.content
        ? [
            {
              id: `text-${message.id}`,
              type: "text",
              text: message.content,
              status: message.status === "streaming" ? "streaming" : "complete",
            },
          ]
        : undefined,
  };
}

function normalizeMessageStatus(status?: string): ChatMessage["status"] {
  if (
    status === "streaming" ||
    status === "complete" ||
    status === "error" ||
    status === "stopped"
  ) {
    return status;
  }
  return "complete";
}

function buildChatHistory(messages: ChatMessage[]): ChatHistoryMessage[] {
  const history: ChatHistoryMessage[] = [];
  let remainingChars = MAX_HISTORY_CHARS;

  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message.status && message.status !== "complete") {
      continue;
    }

    const content = historyContent(message);
    if (!content) {
      continue;
    }

    const trimmed =
      content.length > remainingChars
        ? content.slice(content.length - remainingChars).trim()
        : content;
    if (!trimmed) {
      break;
    }

    history.push({ role: message.role, content: trimmed });
    remainingChars -= trimmed.length;
    if (history.length >= MAX_HISTORY_MESSAGES || remainingChars <= 0) {
      break;
    }
  }

  return history.reverse();
}

function historyContent(message: ChatMessage): string {
  const content =
    message.role === "assistant"
      ? message.content || textFromParts(message.parts ?? [])
      : message.content;
  return (content || "").trim();
}

function textFromParts(parts: MessagePart[]): string {
  return parts
    .map((part) => (part.type === "text" ? part.text : ""))
    .join("")
    .trim();
}

function providerFromServices(services: ServicesResponse): ModelProviderState | null {
  if (!services.model.ok) {
    return null;
  }

  const url = services.model.url;
  if (services.model.model || url.includes("modelscope")) {
    return {
      provider: "primary",
      model: services.model.model || "primary",
      url,
      source: "status",
    };
  }

  return {
    provider: "fallback",
    model: "fallback",
    url,
    source: "status",
  };
}

export default App;
