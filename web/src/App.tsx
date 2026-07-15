import {
  FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  connectChat,
  deleteFile as deleteUploadedFile,
  deleteConversation as deleteServerConversation,
  fetchConversationMessages,
  fetchConversations,
  fetchServices,
  renameConversation as renameServerConversation,
  uploadFile,
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
import {
  mergeSources,
  normalizeSourcePreview,
  sourcesFromMessage,
} from "./sourceUtils";
import type {
  ChatHistoryMessage,
  ChatMessage,
  Conversation,
  FileRecord,
  MessageAttachment,
  MessagePart,
  ModelProviderState,
  RunState,
  ServerEvent,
  SourcePreview,
  ServicesResponse,
  StoredConversation,
  StoredMessage,
  ToolResultPreview,
} from "./types";

const MAX_HISTORY_MESSAGES = 24;
const MAX_HISTORY_CHARS = 24_000;
const SCROLL_BOTTOM_THRESHOLD = 72;
const DEFAULT_WAKE_POLL_INTERVAL_MS = 3_000;
const DEFAULT_WAKE_TIMEOUT_MS = 180_000;

type ServiceWakePhase = "checking" | "waking" | "ready" | "timeout";

function App() {
  const [conversations, setConversations] = useState<Conversation[]>(() => {
    const stored = loadConversations();
    return stored.length ? stored : [createConversation()];
  });
  const [activeId, setActiveId] = useState(() => conversations[0]?.id ?? "");
  const [services, setServices] = useState<ServicesResponse | null>(null);
  const [serviceError, setServiceError] = useState<string | null>(null);
  const [serviceWakePhase, setServiceWakePhase] =
    useState<ServiceWakePhase>("checking");
  const wakePollTimerRef = useRef<number | null>(null);
  const wakePollTokenRef = useRef(0);
  const [composer, setComposer] = useState("");
  const [runState, setRunState] = useState<RunState>("idle");
  const [modelProvider, setModelProvider] =
    useState<ModelProviderState | null>(null);
  const [detailsOpen, setDetailsOpen] = useState<Record<string, boolean>>({});
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [attachedFiles, setAttachedFiles] = useState<FileRecord[]>([]);
  const [fileError, setFileError] = useState<string | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const activeAssistantIdRef = useRef<string | null>(null);
  const messageScrollRef = useRef<HTMLDivElement | null>(null);
  const autoScrollRef = useRef(true);
  const scrollFrameRef = useRef<number | null>(null);
  const [showJumpToLatest, setShowJumpToLatest] = useState(false);

  const activeConversation = useMemo(
    () => conversations.find((conversation) => conversation.id === activeId),
    [activeId, conversations],
  );
  const activeMessageCount = activeConversation?.messages.length ?? 0;
  const shouldShowJumpToLatest = showJumpToLatest && activeMessageCount > 0;

  const scrollToLatest = useCallback((behavior: ScrollBehavior = "auto") => {
    const scrollElement = messageScrollRef.current;
    if (!scrollElement) return;

    autoScrollRef.current = true;
    setShowJumpToLatest(false);
    scrollElement.scrollTo({
      top: scrollElement.scrollHeight,
      behavior,
    });
  }, []);

  const scheduleScrollToLatest = useCallback(
    (behavior: ScrollBehavior = "auto") => {
      if (scrollFrameRef.current !== null) {
        window.cancelAnimationFrame(scrollFrameRef.current);
      }

      scrollFrameRef.current = window.requestAnimationFrame(() => {
        scrollFrameRef.current = null;
        scrollToLatest(behavior);
      });
    },
    [scrollToLatest],
  );

  const updateScrollPin = useCallback(() => {
    const scrollElement = messageScrollRef.current;
    if (!scrollElement) return;

    const distanceFromBottom =
      scrollElement.scrollHeight -
      scrollElement.scrollTop -
      scrollElement.clientHeight;
    const isPinned = distanceFromBottom <= SCROLL_BOTTOM_THRESHOLD;

    autoScrollRef.current = isPinned;
    setShowJumpToLatest(!isPinned && activeMessageCount > 0);
  }, [activeMessageCount]);

  const jumpToLatest = useCallback(() => {
    scrollToLatest("auto");
  }, [scrollToLatest]);

  useEffect(() => {
    saveConversations(conversations);
  }, [conversations]);

  useEffect(() => {
    void refreshServices();
    void hydrateServerHistory();
    return () => {
      wakePollTokenRef.current += 1;
      if (wakePollTimerRef.current !== null) {
        window.clearTimeout(wakePollTimerRef.current);
        wakePollTimerRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    autoScrollRef.current = true;
    scheduleScrollToLatest("auto");
  }, [activeId, scheduleScrollToLatest]);

  useEffect(() => {
    if (!activeMessageCount) {
      autoScrollRef.current = true;
      return;
    }

    if (autoScrollRef.current) {
      scheduleScrollToLatest("auto");
    }
  }, [activeConversation?.messages, activeMessageCount, scheduleScrollToLatest]);

  useEffect(
    () => () => {
      if (scrollFrameRef.current !== null) {
        window.cancelAnimationFrame(scrollFrameRef.current);
      }
    },
    [],
  );

  async function refreshServices() {
    wakePollTokenRef.current += 1;
    const token = wakePollTokenRef.current;
    if (wakePollTimerRef.current !== null) {
      window.clearTimeout(wakePollTimerRef.current);
      wakePollTimerRef.current = null;
    }

    setServiceError(null);
    setServiceWakePhase("checking");

    let intervalMs = DEFAULT_WAKE_POLL_INTERVAL_MS;
    let deadline = Date.now() + DEFAULT_WAKE_TIMEOUT_MS;

    while (wakePollTokenRef.current === token) {
      try {
        const nextServices = await fetchServices();
        if (wakePollTokenRef.current !== token) return;

        setServices(nextServices);
        setModelProvider((current) =>
          current?.source === "event" ? current : providerFromServices(nextServices),
        );
        if (nextServices.poll_interval_seconds) {
          intervalMs = nextServices.poll_interval_seconds * 1000;
        }
        if (nextServices.wake_timeout_seconds) {
          deadline = Date.now() + nextServices.wake_timeout_seconds * 1000;
        }

        if (nextServices.model.ok && nextServices.search.ok) {
          setServiceWakePhase("ready");
          return;
        }
        setServiceWakePhase("waking");
      } catch {
        if (wakePollTokenRef.current !== token) return;
        setServiceWakePhase("waking");
      }

      if (Date.now() >= deadline) {
        setServiceWakePhase("timeout");
        setServiceError(
          "Aristotle's services are taking longer than expected to wake up.",
        );
        return;
      }

      await new Promise<void>((resolve) => {
        wakePollTimerRef.current = window.setTimeout(() => {
          wakePollTimerRef.current = null;
          resolve();
        }, intervalMs);
      });
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
    autoScrollRef.current = true;
    setShowJumpToLatest(false);
    setConversations((current) => [conversation, ...current]);
    setActiveId(conversation.id);
    setComposer("");
    setAttachedFiles([]);
    setFileError(null);
    setRunState("idle");
    setSidebarOpen(false);
  }

  function selectConversation(conversationId: string) {
    if (conversationId === activeId) {
      setSidebarOpen(false);
      return;
    }
    stopStream("stopped");
    autoScrollRef.current = true;
    setShowJumpToLatest(false);
    setActiveId(conversationId);
    setAttachedFiles([]);
    setFileError(null);
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
    const submittedAttachments = attachedFiles.map(messageAttachmentFromFile);
    const fileIds = parsedMessageAttachmentIds(submittedAttachments);

    const now = new Date().toISOString();
    const assistantMessageId = crypto.randomUUID();
    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: prompt,
      createdAt: now,
      status: "complete",
      attachments: submittedAttachments,
    };
    const assistantMessage: ChatMessage = {
      id: assistantMessageId,
      role: "assistant",
      createdAt: now,
      status: "streaming",
      parts: [],
      metrics: { startedAt: now },
    };

    setComposer("");
    setAttachedFiles([]);
    setFileError(null);
    autoScrollRef.current = true;
    setShowJumpToLatest(false);

    updateConversation(activeConversation.id, (conversation) => ({
      ...conversation,
      title: conversation.messages.length
        ? conversation.title
        : titleFromPrompt(prompt),
      updatedAt: now,
      messages: [...conversation.messages, userMessage, assistantMessage],
    }));

    startAssistantRun(
      activeConversation.id,
      assistantMessageId,
      prompt,
      history,
      fileIds,
    );
  }

  function retryMessage(message: ChatMessage) {
    if (!activeConversation || isRunning) return;

    const assistantIndex = activeConversation.messages.findIndex(
      (item) => item.id === message.id && item.role === "assistant",
    );
    if (assistantIndex < 0) return;

    const userIndex = findPreviousUserIndex(
      activeConversation.messages,
      assistantIndex,
    );
    if (userIndex < 0) return;

    const userMessage = activeConversation.messages[userIndex];
    const prompt = (userMessage.content || "").trim();
    if (!prompt) return;

    stopStream("stopped");

    const now = new Date().toISOString();
    const assistantMessageId = crypto.randomUUID();
    const history = buildChatHistory(
      activeConversation.messages.slice(0, userIndex),
    );
    const assistantMessage: ChatMessage = {
      id: assistantMessageId,
      role: "assistant",
      createdAt: now,
      status: "streaming",
      parts: [],
      metrics: { startedAt: now },
    };

    updateConversation(activeConversation.id, (conversation) => ({
      ...conversation,
      updatedAt: now,
      messages: [
        ...conversation.messages.slice(0, userIndex + 1),
        assistantMessage,
      ],
    }));

    const fileIds = parsedMessageAttachmentIds(userMessage.attachments ?? []);
    startAssistantRun(
      activeConversation.id,
      assistantMessageId,
      prompt,
      history,
      fileIds,
    );
  }

  function startAssistantRun(
    conversationId: string,
    assistantId: string,
    prompt: string,
    history: ChatHistoryMessage[],
    fileIds: string[],
  ) {
    activeAssistantIdRef.current = assistantId;
    setRunState("connecting");

    socketRef.current = connectChat(
      {
        type: "user.message",
        message: prompt,
        conversation_id: conversationId,
        history,
        options: {
          max_search_results: 5,
          file_ids: fileIds,
        },
      },
      (serverEvent) =>
        handleServerEvent(
          conversationId,
          assistantId,
          serverEvent,
        ),
      () => {
        socketRef.current = null;
      },
      (message) => {
        appendWarning(conversationId, assistantId, message);
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
      updateAssistantMetrics(conversationId, assistantId, {
        ttftMs: event.latency_ms,
        firstTokenAt: event.timestamp,
      });
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

    if (resultPreview?.length) {
      mergeAssistantSources(conversationId, assistantId, resultPreview, toolName);
    }
  }

  function mergeAssistantSources(
    conversationId: string,
    assistantId: string,
    previews: ToolResultPreview[],
    toolName?: string,
  ) {
    const incoming = previews
      .map((preview) => normalizeSourcePreview(preview, toolName))
      .filter((source): source is SourcePreview => Boolean(source));

    if (!incoming.length) return;

    updateConversation(conversationId, (conversation) => ({
      ...conversation,
      updatedAt: new Date().toISOString(),
      messages: conversation.messages.map((message) =>
        message.id === assistantId
          ? { ...message, sources: mergeSources(message.sources ?? [], incoming) }
          : message,
      ),
    }));
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

  function updateAssistantMetrics(
    conversationId: string,
    assistantId: string,
    metrics: Partial<NonNullable<ChatMessage["metrics"]>>,
  ) {
    updateConversation(conversationId, (conversation) => ({
      ...conversation,
      updatedAt: new Date().toISOString(),
      messages: conversation.messages.map((message) =>
        message.id === assistantId
          ? {
              ...message,
              metrics: {
                ...message.metrics,
                ...metrics,
              },
            }
          : message,
      ),
    }));
  }

  function completeAssistant(
    conversationId: string,
    assistantId: string,
    content: string,
    status: "complete" | "error" = "complete",
  ) {
    const completedAt = new Date().toISOString();
    updateConversation(conversationId, (conversation) => ({
      ...conversation,
      updatedAt: completedAt,
      messages: conversation.messages.map((message) => {
        if (message.id !== assistantId) {
          return message;
        }
        const finalContent = content || textFromParts(message.parts ?? []);
        return {
          ...message,
          content: finalContent,
          status,
          metrics: finalizeMessageMetrics(message, finalContent, completedAt),
          parts: (message.parts ?? []).map((part) =>
            part.type === "text" || part.type === "reasoning"
              ? { ...part, status: "complete" }
              : part,
          ),
        };
      }),
    }));
  }

  function stopStream(status: "stopped" | "complete" = "stopped") {
    const hadSocket = socketRef.current !== null;
    socketRef.current?.close();
    socketRef.current = null;

    if (hadSocket && activeConversation && activeAssistantIdRef.current) {
      const assistantId = activeAssistantIdRef.current;
      const completedAt = new Date().toISOString();
      updateConversation(activeConversation.id, (conversation) => ({
        ...conversation,
        updatedAt: completedAt,
        messages: conversation.messages.map((message) =>
          message.id === assistantId
            ? {
                ...message,
                status,
                metrics: finalizeMessageMetrics(
                  message,
                  message.content || textFromParts(message.parts ?? []),
                  completedAt,
                ),
              }
            : message,
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

  async function copyMessageWithSources(message: ChatMessage) {
    const text = message.content || textFromParts(message.parts ?? []);
    const sources = sourcesFromMessage(message);
    const sourceText = sources
      .map(
        (source) =>
          `[${source.citationIndex ?? ""}] ${source.title || source.domain || "Source"}\n${sourceReference(source)}`,
      )
      .join("\n\n");
    const combined = [text, sourceText ? `Sources\n${sourceText}` : ""]
      .filter(Boolean)
      .join("\n\n");
    if (combined) {
      await navigator.clipboard.writeText(combined);
    }
  }

  async function copyMessageSources(message: ChatMessage) {
    const sources = sourcesFromMessage(message);
    const text = sources
      .map(
        (source) =>
          `[${source.citationIndex ?? ""}] ${source.title || source.domain || "Source"}\n${sourceReference(source)}`,
      )
      .join("\n\n");
    if (text) {
      await navigator.clipboard.writeText(text);
    }
  }

  async function handleUploadFile(file: File) {
    if (!activeId) return;
    try {
      setFileError(null);
      const response = await uploadFile(file, activeId);
      setAttachedFiles((current) => mergeFiles(current, [response.file]));
    } catch (error) {
      setFileError(error instanceof Error ? error.message : "File upload failed.");
    }
  }

  async function handleRemoveFile(fileId: string) {
    setAttachedFiles((current) => current.filter((file) => file.id !== fileId));
    try {
      await deleteUploadedFile(fileId);
    } catch (error) {
      setFileError(error instanceof Error ? error.message : "File delete failed.");
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
          isWakingServices={
            serviceWakePhase === "checking" || serviceWakePhase === "waking"
          }
          onOpenSidebar={() => setSidebarOpen(true)}
          onNewChat={createNewChat}
        />

        {serviceError && (
          <ServiceAlert
            onRetry={() => void refreshServices()}
            retrying={serviceWakePhase === "checking"}
          >
            {serviceError}
          </ServiceAlert>
        )}

        <MessageList
          conversation={activeConversation}
          scrollRef={messageScrollRef}
          onScroll={updateScrollPin}
          showJumpToLatest={shouldShowJumpToLatest}
          onJumpToLatest={jumpToLatest}
          detailsOpen={detailsOpen}
          setDetailsOpen={setDetailsOpen}
          onCopyMessage={(message) => void copyMessage(message)}
          onCopyMessageWithSources={(message) =>
            void copyMessageWithSources(message)
          }
          onCopyMessageSources={(message) => void copyMessageSources(message)}
          onRetryMessage={retryMessage}
          isRunning={isRunning}
          onPickPrompt={setComposer}
        />

        <Composer
          composer={composer}
          isRunning={isRunning}
          setComposer={setComposer}
          onSubmit={submitMessage}
          onStop={() => stopStream("stopped")}
          attachedFiles={attachedFiles}
          fileError={fileError}
          onUploadFile={(file) => void handleUploadFile(file)}
          onRemoveFile={(fileId) => void handleRemoveFile(fileId)}
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

function parsedMessageAttachmentIds(attachments: MessageAttachment[]): string[] {
  return attachments
    .filter((attachment) => attachment.parse_status === "parsed")
    .map((attachment) => attachment.id);
}

function messageAttachmentFromFile(file: FileRecord): MessageAttachment {
  return {
    id: file.id,
    filename: file.filename,
    mime_type: file.mime_type,
    size_bytes: file.size_bytes,
    parse_status: file.parse_status,
    parse_error: file.parse_error,
  };
}

function mergeFiles(current: FileRecord[], incoming: FileRecord[]): FileRecord[] {
  const byId = new Map(current.map((file) => [file.id, file]));
  for (const file of incoming) {
    byId.set(file.id, file);
  }
  return Array.from(byId.values());
}

function sourceReference(source: SourcePreview): string {
  return (
    source.url ||
    source.locator ||
    source.domain ||
    source.file_id ||
    source.fileId ||
    source.chunk_id ||
    source.chunkId ||
    ""
  );
}

function findPreviousUserIndex(messages: ChatMessage[], beforeIndex: number) {
  for (let index = beforeIndex - 1; index >= 0; index -= 1) {
    if (messages[index].role === "user") {
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
  const content = message.content || "";
  const status = normalizeMessageStatus(message.status);
  const metrics =
    message.role === "assistant" && content
      ? finalizeMessageMetrics(
          {
            id: message.id,
            role: message.role,
            content,
            createdAt: message.created_at,
            metrics: { startedAt: message.created_at },
          },
          content,
          message.completed_at || message.created_at,
        )
      : undefined;

  return {
    id: message.id,
    role: message.role,
    content,
    createdAt: message.created_at,
    status,
    attachments: message.attachments ?? [],
    metrics,
    parts:
      message.role === "assistant" && content
        ? [
            {
              id: `text-${message.id}`,
              type: "text",
              text: content,
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

function finalizeMessageMetrics(
  message: ChatMessage,
  content: string,
  completedAt: string,
): ChatMessage["metrics"] {
  const current = message.metrics ?? {};
  const startedMs = current.startedAt ? Date.parse(current.startedAt) : NaN;
  const completedMs = Date.parse(completedAt);
  const firstTokenMs = current.firstTokenAt ? Date.parse(current.firstTokenAt) : NaN;
  const durationMs =
    Number.isFinite(startedMs) && Number.isFinite(completedMs)
      ? Math.max(0, completedMs - startedMs)
      : current.durationMs;
  const outputTokens = current.outputTokens ?? estimateTokenCount(content);
  const generationMs =
    Number.isFinite(firstTokenMs) && Number.isFinite(completedMs)
      ? Math.max(1, completedMs - firstTokenMs)
      : durationMs;
  const tps =
    current.tps ??
    (outputTokens && generationMs
      ? Number((outputTokens / (generationMs / 1000)).toFixed(1))
      : null);

  return {
    ...current,
    durationMs,
    outputTokens,
    tps,
    tokenSource: current.tokenSource ?? "estimated",
  };
}

function estimateTokenCount(text: string): number | null {
  const trimmed = text.trim();
  if (!trimmed) return null;
  return Math.max(1, Math.round(trimmed.length / 4));
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
