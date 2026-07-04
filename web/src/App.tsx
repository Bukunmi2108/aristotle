import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { connectChat, fetchServices } from "./api";
import {
  AppHeader,
  Composer,
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
  ChatMessage,
  Conversation,
  MessagePart,
  ModelProviderState,
  RunState,
  ServerEvent,
  ServicesResponse,
  ToolResultPreview,
} from "./types";

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
      appendTool(conversationId, assistantId, {
        id: `${event.type}-${event.sequence}`,
        type: "tool",
        label: event.service ? `${event.service} ready` : "service ready",
        status: "complete",
        timestamp: event.timestamp,
      });
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
      <section className="app-shell">
        <AppHeader
          runState={runState}
          services={services}
          modelProvider={modelProvider}
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
  if (url.includes("modelscope")) {
    return {
      provider: "primary",
      model: "zai-org/GLM-5.2",
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
