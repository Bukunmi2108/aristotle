import {
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  Download,
  ExternalLink,
  FileText,
  Loader2,
  Menu,
  MoreHorizontal,
  Pause,
  Paperclip,
  Pencil,
  Plus,
  RotateCcw,
  Search,
  Send,
  TriangleAlert,
  Trash2,
  Wrench,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Dispatch, FormEvent, RefObject, SetStateAction } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { artifactDownloadUrl, serviceSummary } from "./api";
import { isDocumentSource, sameSourceUrl, sourcesFromMessage } from "./sourceUtils";
import type {
  ArtifactRef,
  ChatMessage,
  Conversation,
  FileRecord,
  MessageAttachment,
  MessagePart,
  ModelProviderState,
  RunState,
  SourcePreview,
  ServicesResponse,
} from "./types";

const iconStroke = 1.8;

function AristotleMark({ className = "" }: { className?: string }) {
  return (
    <img
      className={className}
      src="/aristotle-mark.png"
      alt="Aristotle"
      decoding="async"
      draggable={false}
    />
  );
}

type AppHeaderProps = {
  runState: RunState;
  services: ServicesResponse | null;
  modelProvider: ModelProviderState | null;
  isWakingServices?: boolean;
  onOpenSidebar: () => void;
  onNewChat: () => void;
};

export function AppHeader({
  runState,
  services,
  modelProvider,
  isWakingServices,
  onOpenSidebar,
  onNewChat,
}: AppHeaderProps) {
  return (
    <header className="app-header">
      <div className="app-header__identity">
        <button
          className="icon-button"
          type="button"
          onClick={onOpenSidebar}
          title="Open conversation history"
        >
          <Menu size={18} strokeWidth={iconStroke} />
        </button>
        <div className="app-header__title-block">
          <h1 className="app-header__title">Aristotle</h1>
        </div>
      </div>

      <div className="app-header__actions">
        <div className="status-cluster">
          <HealthBeat
            runState={runState}
            services={services}
            isWakingServices={isWakingServices}
          />
          <ModelProviderTag provider={modelProvider} />
        </div>
        <button
          className="icon-button icon-button--primary"
          type="button"
          onClick={onNewChat}
          title="New chat"
        >
          <Plus size={18} strokeWidth={iconStroke} />
        </button>
      </div>
    </header>
  );
}

type HistorySidebarProps = {
  isOpen: boolean;
  conversations: Conversation[];
  activeConversationId: string;
  onClose: () => void;
  onNewChat: () => void;
  onSelectConversation: (conversationId: string) => void;
  onRenameConversation: (conversationId: string, title: string) => void;
  onDeleteConversation: (conversationId: string) => void;
};

export function HistorySidebar({
  isOpen,
  conversations,
  activeConversationId,
  onClose,
  onNewChat,
  onSelectConversation,
  onRenameConversation,
  onDeleteConversation,
}: HistorySidebarProps) {
  const [query, setQuery] = useState("");
  const [editingConversationId, setEditingConversationId] = useState<string | null>(
    null,
  );
  const [renameDraft, setRenameDraft] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  const renameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!isOpen) return undefined;

    function handleShortcut(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchRef.current?.focus();
      }
    }

    window.addEventListener("keydown", handleShortcut);
    return () => {
      window.removeEventListener("keydown", handleShortcut);
    };
  }, [isOpen]);

  useEffect(() => {
    if (!editingConversationId) return;
    renameRef.current?.focus();
    renameRef.current?.select();
  }, [editingConversationId]);

  const visibleConversations = useMemo(() => {
    const sorted = [...conversations].sort(
      (first, second) =>
        dateTime(second.updatedAt || second.createdAt) -
        dateTime(first.updatedAt || first.createdAt),
    );
    const normalizedQuery = query.trim().toLowerCase();
    if (!normalizedQuery) return sorted;
    return sorted.filter((conversation) =>
      conversationMatchesSearch(conversation, normalizedQuery),
    );
  }, [conversations, query]);

  if (!isOpen) return null;

  function beginRename(conversation: Conversation) {
    setEditingConversationId(conversation.id);
    setRenameDraft(conversation.title);
  }

  function cancelRename() {
    setEditingConversationId(null);
    setRenameDraft("");
  }

  function commitRename(conversation: Conversation) {
    const cleaned = renameDraft.trim();
    if (!cleaned || cleaned === conversation.title) {
      cancelRename();
      return;
    }

    onRenameConversation(conversation.id, cleaned);
    cancelRename();
  }

  return (
    <>
      <button
        className="history-backdrop"
        type="button"
        aria-label="Close conversation history"
        onClick={onClose}
      />
      <aside className="history-sidebar" aria-label="Conversation history">
        <div className="history-sidebar__header">
          <strong>Aristotle</strong>
          <button
            className="icon-button"
            type="button"
            onClick={onClose}
            title="Close"
          >
            <X size={18} strokeWidth={iconStroke} />
          </button>
        </div>

        <button className="history-new-button" type="button" onClick={onNewChat}>
          <Plus size={16} strokeWidth={iconStroke} />
          New chat
        </button>

        <label className="history-search">
          <Search size={15} strokeWidth={iconStroke} />
          <input
            ref={searchRef}
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search chats"
          />
          <span>Ctrl K</span>
        </label>

        <nav className="history-list" aria-label="Conversations">
          <section className="history-section">
            <h2>{query.trim() ? "Results" : "Recent"}</h2>
            {visibleConversations.length ? (
              <div className="history-section__items">
                {visibleConversations.map((conversation) => {
                  const isActive = conversation.id === activeConversationId;
                  return (
                    <div
                      key={conversation.id}
                      className={cx(
                        "history-row",
                        isActive && "history-row--active",
                        editingConversationId === conversation.id &&
                          "history-row--editing",
                      )}
                    >
                      {editingConversationId === conversation.id ? (
                        <form
                          className="history-row__rename"
                          onSubmit={(event) => {
                            event.preventDefault();
                            commitRename(conversation);
                          }}
                        >
                          <input
                            ref={renameRef}
                            value={renameDraft}
                            onChange={(event) => setRenameDraft(event.target.value)}
                            onKeyDown={(event) => {
                              if (event.key === "Escape") {
                                event.preventDefault();
                                cancelRename();
                              }
                            }}
                          />
                          <button
                            className="history-row__rename-action"
                            type="submit"
                            title="Save name"
                          >
                            <Check size={14} strokeWidth={iconStroke} />
                          </button>
                          <button
                            className="history-row__rename-action"
                            type="button"
                            onClick={cancelRename}
                            title="Cancel rename"
                          >
                            <X size={14} strokeWidth={iconStroke} />
                          </button>
                        </form>
                      ) : (
                        <>
                          <button
                            className="history-row__main"
                            type="button"
                            onClick={() => onSelectConversation(conversation.id)}
                            title={conversation.title}
                          >
                            <span className="history-row__title">
                              {conversation.title}
                            </span>
                          </button>
                          <details className="history-row__menu">
                            <summary
                              aria-label={`Conversation actions for ${conversation.title}`}
                            >
                              <MoreHorizontal
                                size={16}
                                strokeWidth={iconStroke}
                              />
                            </summary>
                            <div className="history-row__menu-popover">
                              <button
                                type="button"
                                onClick={() => beginRename(conversation)}
                              >
                                <Pencil size={14} strokeWidth={iconStroke} />
                                Rename
                              </button>
                              <button
                                className="history-row__menu-danger"
                                type="button"
                                onClick={() => onDeleteConversation(conversation.id)}
                              >
                                <Trash2 size={14} strokeWidth={iconStroke} />
                                Delete
                              </button>
                            </div>
                          </details>
                        </>
                      )}
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="history-empty">No chats found</div>
            )}
          </section>
        </nav>
      </aside>
    </>
  );
}

function dateTime(value: string): number {
  const time = new Date(value).getTime();
  return Number.isNaN(time) ? 0 : time;
}

function conversationMatchesSearch(
  conversation: Conversation,
  normalizedQuery: string,
): boolean {
  return conversation.title.toLowerCase().includes(normalizedQuery);
}

function ModelProviderTag({
  provider,
}: {
  provider: ModelProviderState | null;
}) {
  if (!provider) return null;

  const isFallback = provider.provider === "fallback";
  const label = providerLabel(provider);
  const latency = provider.firstTokenLatencyMs ?? provider.selectedLatencyMs;
  const title = [
    isFallback ? "Fallback provider" : "Primary provider",
    provider.model ? `Model: ${provider.model}` : null,
    provider.url ? `URL: ${provider.url}` : null,
    latency ? `Latency: ${latency} ms` : null,
    provider.reason ? `Reason: ${provider.reason}` : null,
  ]
    .filter(Boolean)
    .join("\n");

  return (
    <span
      className={cx(
        "model-provider-tag",
        isFallback && "model-provider-tag--fallback",
      )}
      title={title}
    >
      {label}
    </span>
  );
}

type ServiceAlertProps = {
  children: string;
  onRetry?: () => void;
  retrying?: boolean;
};

export function ServiceAlert({ children, onRetry, retrying }: ServiceAlertProps) {
  return (
    <div className="service-alert">
      <span>{children}</span>
      {onRetry && (
        <button
          type="button"
          className="service-alert__retry"
          onClick={onRetry}
          disabled={retrying}
        >
          {retrying ? "Retrying…" : "Retry"}
        </button>
      )}
    </div>
  );
}

type MessageListProps = {
  conversation?: Conversation;
  scrollRef: RefObject<HTMLDivElement | null>;
  onScroll: () => void;
  showJumpToLatest: boolean;
  onJumpToLatest: () => void;
  detailsOpen: Record<string, boolean>;
  setDetailsOpen: Dispatch<SetStateAction<Record<string, boolean>>>;
  onCopyMessage: (message: ChatMessage) => void | Promise<void>;
  onCopyMessageWithSources: (message: ChatMessage) => void | Promise<void>;
  onCopyMessageSources: (message: ChatMessage) => void | Promise<void>;
  onRetryMessage: (message: ChatMessage) => void;
  isRunning: boolean;
  onPickPrompt: (prompt: string) => void;
};

export function MessageList({
  conversation,
  scrollRef,
  onScroll,
  showJumpToLatest,
  onJumpToLatest,
  detailsOpen,
  setDetailsOpen,
  onCopyMessage,
  onCopyMessageWithSources,
  onCopyMessageSources,
  onRetryMessage,
  isRunning,
  onPickPrompt,
}: MessageListProps) {
  return (
    <div className="message-scroll-shell">
      <div ref={scrollRef} className="message-scroll" onScroll={onScroll}>
        {conversation?.messages.length ? (
          conversation.messages.map((message, index) => (
            <MessageBubble
              key={message.id}
              message={message}
              detailsOpen={detailsOpen}
              setDetailsOpen={setDetailsOpen}
              onCopy={() => onCopyMessage(message)}
              onCopyWithSources={() => onCopyMessageWithSources(message)}
              onCopySources={() => onCopyMessageSources(message)}
              onRetry={() => onRetryMessage(message)}
              canRetry={canRetryAssistantMessage(
                conversation.messages,
                index,
                isRunning,
              )}
            />
          ))
        ) : (
          <EmptyState onPickPrompt={onPickPrompt} />
        )}
      </div>
      {showJumpToLatest && (
        <button
          className="latest-button"
          type="button"
          onClick={onJumpToLatest}
          title="Jump to latest"
          aria-label="Jump to latest"
        >
          <ChevronDown size={18} strokeWidth={iconStroke} />
        </button>
      )}
    </div>
  );
}

type ComposerProps = {
  composer: string;
  isRunning: boolean;
  attachedFiles: FileRecord[];
  fileError: string | null;
  setComposer: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
  onStop: () => void;
  onUploadFile: (file: File) => void;
  onRemoveFile: (fileId: string) => void;
};

export function Composer({
  composer,
  isRunning,
  attachedFiles,
  fileError,
  setComposer,
  onSubmit,
  onStop,
  onUploadFile,
  onRemoveFile,
}: ComposerProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);

  return (
    <form className="composer" onSubmit={onSubmit}>
      {attachedFiles.length > 0 && (
        <div className="composer-files" aria-label="Attached files">
          {attachedFiles.map((file) => (
            <span
              key={file.id}
              className={cx(
                "composer-file",
                file.parse_status === "failed" && "composer-file--failed",
              )}
              title={file.parse_error || file.filename}
            >
              <FileText size={13} strokeWidth={iconStroke} />
              <span>{file.filename}</span>
              {file.parse_status !== "parsed" && <em>{file.parse_status}</em>}
              <button
                type="button"
                onClick={() => onRemoveFile(file.id)}
                title={`Remove ${file.filename}`}
                disabled={isRunning}
              >
                <X size={12} strokeWidth={iconStroke} />
              </button>
            </span>
          ))}
        </div>
      )}
      {fileError && <div className="composer-file-error">{fileError}</div>}
      <div className="composer__input-row">
        <button
          className="composer-tool-button"
          type="button"
          onClick={() => fileInputRef.current?.click()}
          title="Attach file"
          disabled={isRunning}
        >
          <Paperclip size={17} strokeWidth={iconStroke} />
        </button>
        <input
          ref={fileInputRef}
          className="composer-file-input"
          type="file"
          accept=".txt,.md,.markdown,.json,.csv,.html,.htm,.pdf,.docx"
          onChange={(event) => {
            const file = event.currentTarget.files?.[0];
            event.currentTarget.value = "";
            if (file) onUploadFile(file);
          }}
        />
        <textarea
          className="composer__textarea"
          value={composer}
          onChange={(event) => setComposer(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
          placeholder="Ask Aristotle anything"
          rows={1}
          disabled={isRunning}
        />
        {isRunning ? (
          <button
            className="send-button send-button--stop"
            type="button"
            onClick={onStop}
            title="Stop"
          >
            <Pause size={18} strokeWidth={iconStroke} />
          </button>
        ) : (
          <button
            className="send-button"
            type="submit"
            disabled={!composer.trim()}
            title="Send"
          >
            <Send size={18} strokeWidth={iconStroke} />
          </button>
        )}
      </div>
    </form>
  );
}

function HealthBeat({
  runState,
  services,
  isWakingServices,
}: {
  runState: RunState;
  services: ServicesResponse | null;
  isWakingServices?: boolean;
}) {
  const state = healthState(runState, services, isWakingServices);

  return (
    <div className={cx("health-beat", `health-beat--${state.tone}`)} title={state.detail}>
      <span aria-hidden="true" />
      <strong>{state.label}</strong>
    </div>
  );
}

function MessageBubble({
  message,
  detailsOpen,
  setDetailsOpen,
  onCopy,
  onCopyWithSources,
  onCopySources,
  onRetry,
  canRetry,
}: {
  message: ChatMessage;
  detailsOpen: Record<string, boolean>;
  setDetailsOpen: Dispatch<SetStateAction<Record<string, boolean>>>;
  onCopy: () => void | Promise<void>;
  onCopyWithSources: () => void | Promise<void>;
  onCopySources: () => void | Promise<void>;
  onRetry: () => void;
  canRetry: boolean;
}) {
  const reasoning =
    message.parts?.filter((part) => part.type === "reasoning") ?? [];
  const bodyParts =
    message.parts?.filter((part) => part.type !== "reasoning") ?? [];
  const hasText = bodyParts.some(
    (part) => part.type === "text" && part.text.trim().length > 0,
  );
  const isDetailsOpen = detailsOpen[message.id] ?? message.status === "streaming";
  const toolTraceOpen = !hasText;
  const sources = sourcesFromMessage(message);
  const visibleSources = message.status === "streaming" ? [] : sources;
  const showFooter = message.status !== "streaming";

  if (message.role === "user") {
    return (
      <div className="message user-message">
        {message.content && (
          <div className="message--user">
            <div className="message--user__text">{message.content}</div>
          </div>
        )}
        {message.attachments?.length ? (
          <MessageAttachments attachments={message.attachments} />
        ) : null}
      </div>
    );
  }

  return (
    <article className="assistant-message">
      <div className="assistant-message__avatar">
        <AristotleMark className="assistant-message__mark" />
      </div>
      <div className="assistant-message__content">
        {reasoning.length > 0 && (
          <section className="reasoning-panel">
            <button
              className={cx(
                "reasoning-panel__trigger",
                isDetailsOpen && "reasoning-panel__trigger--open",
              )}
              type="button"
              aria-expanded={isDetailsOpen}
              onClick={() =>
                setDetailsOpen((current) => ({
                  ...current,
                  [message.id]: !isDetailsOpen,
                }))
              }
            >
              <span className="reasoning-panel__glyph" aria-hidden="true">
                {isDetailsOpen ? (
                  <ChevronDown size={13} strokeWidth={iconStroke} />
                ) : (
                  <ChevronRight size={13} strokeWidth={iconStroke} />
                )}
              </span>
              <span className="reasoning-panel__label">Thinking</span>
            </button>
            {isDetailsOpen && (
              <div className="reasoning-panel__body">
                {reasoning
                  .map((part) => (part.type === "reasoning" ? part.text : ""))
                  .join("")}
              </div>
            )}
          </section>
        )}

        <div className="assistant-message__parts">
          {groupMessageParts(bodyParts).map((group) => (
            <MessagePartGroupView
              key={group.id}
              group={group}
              toolTraceOpen={toolTraceOpen}
              sources={visibleSources}
            />
          ))}
          {message.status === "streaming" && <span className="stream-caret" />}
        </div>

        {showFooter && (
          <MessageFooter
            message={message}
            sources={visibleSources}
            onCopy={onCopy}
            onCopyWithSources={onCopyWithSources}
            onCopySources={onCopySources}
            onRetry={onRetry}
            canRetry={canRetry}
          />
        )}
      </div>
    </article>
  );
}

function MessageAttachments({
  attachments,
}: {
  attachments: MessageAttachment[];
}) {
  return (
    <div className="message-attachments" aria-label="Message attachments">
      {attachments.map((attachment) => {
        const meta = [
          fileTypeLabel(attachment.mime_type),
          formatFileSize(attachment.size_bytes),
          attachment.parse_status !== "parsed" ? attachment.parse_status : null,
        ]
          .filter(Boolean)
          .join(" · ");

        return (
          <span
            key={attachment.id}
            className={cx(
              "message-attachment",
              attachment.parse_status === "failed" && "message-attachment--failed",
            )}
            title={attachment.parse_error || attachment.filename}
          >
            <span className="message-attachment__icon" aria-hidden="true">
              <FileText size={16} strokeWidth={iconStroke} />
            </span>
            <span className="message-attachment__body">
              <strong>{attachment.filename}</strong>
              <small>{meta}</small>
            </span>
          </span>
        );
      })}
    </div>
  );
}

function fileTypeLabel(mimeType: string): string {
  if (mimeType.includes("pdf")) return "PDF";
  if (mimeType.includes("wordprocessingml")) return "DOCX";
  if (mimeType.includes("json")) return "JSON";
  if (mimeType.includes("csv")) return "CSV";
  if (mimeType.includes("html")) return "HTML";
  if (mimeType.startsWith("text/")) return "Text";
  return "File";
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

type MessagePartGroup =
  | { id: string; type: "single"; part: MessagePart }
  | { id: string; type: "tools"; parts: Extract<MessagePart, { type: "tool" }>[] };

function MessagePartGroupView({
  group,
  toolTraceOpen,
  sources,
}: {
  group: MessagePartGroup;
  toolTraceOpen: boolean;
  sources: SourcePreview[];
}) {
  if (group.type === "tools") {
    return <ToolTrace parts={group.parts} defaultOpen={toolTraceOpen} />;
  }

  return <MessagePartView part={group.part} sources={sources} />;
}

function MessagePartView({
  part,
  sources,
}: {
  part: MessagePart;
  sources: SourcePreview[];
}) {
  if (part.type === "text") {
    const cleanedText = stripDuplicateCitationList(part.text);
    const markdown = sources.length
      ? linkCitationMarkers(cleanedText, sources)
      : cleanedText;
    return (
      <div className="message-text">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            a: ({ href, children, ...props }) => {
              const source = sourceForHref(href, sources);
              const isCitation = Boolean(source) && citationText(children);
              if (source && isCitation) {
                return (
                  <CitationMarker
                    href={citationHref(source)}
                    source={source}
                  />
                );
              }
              return (
                <a
                  {...props}
                  href={href}
                  rel="noreferrer"
                  target={href?.startsWith("http") ? "_blank" : undefined}
                  title={source ? sourceTitle(source) : undefined}
                >
                  {children}
                </a>
              );
            },
          }}
        >
          {markdown}
        </ReactMarkdown>
      </div>
    );
  }

  if (part.type === "warning") {
    return <div className="inline-alert inline-alert--danger">{part.text}</div>;
  }

  return null;
}

function ToolTrace({
  parts,
  defaultOpen,
}: {
  parts: Extract<MessagePart, { type: "tool" }>[];
  defaultOpen: boolean;
}) {
  const hasRunning = parts.some((part) => part.status === "running");
  const hasError = parts.some((part) => part.status === "error");
  const summary = toolTraceSummary(parts);
  const detailsRef = useRef<HTMLDetailsElement>(null);

  useEffect(() => {
    if (detailsRef.current) {
      detailsRef.current.open = defaultOpen;
    }
  }, [defaultOpen]);

  return (
    <details
      ref={detailsRef}
      className={cx(
        "tool-trace",
        hasRunning && "tool-trace--running",
        hasError && "tool-trace--error",
        `tool-trace--${summary.tone}`,
      )}
    >
      <summary className="tool-trace__header">
        <span className="tool-trace__chevron" aria-hidden="true">
          <ChevronRight size={13} strokeWidth={iconStroke} />
        </span>
        <span className="tool-trace__status-icon" aria-hidden="true">
          <Wrench size={13} strokeWidth={iconStroke} />
        </span>
        <span className="tool-trace__summary">{summary.label}</span>
        {summary.count > 1 && (
          <span className="tool-trace__count" aria-label={`${summary.count} tool steps`}>
            {summary.count}
          </span>
        )}
      </summary>
      <ol className="tool-trace__list">
        {parts.map((part) => (
          <ToolTraceItem key={part.id} part={part} />
        ))}
      </ol>
    </details>
  );
}

type ToolTraceSummary = {
  label: string;
  tone: "idle" | "running" | "complete" | "warning" | "error";
  count: number;
};

function toolTraceSummary(
  parts: Extract<MessagePart, { type: "tool" }>[],
): ToolTraceSummary {
  const count = parts.length;
  if (!count) {
    return { label: "Tool activity", tone: "idle", count: 0 };
  }

  const latestRunning = [...parts]
    .reverse()
    .find((part) => part.status === "running");
  if (latestRunning) {
    return {
      label: `${activeToolLabel(latestRunning.label)}...`,
      tone: "running",
      count,
    };
  }

  const hasError = parts.some((part) => part.status === "error");
  if (hasError) {
    return {
      label: "Some checks could not be completed",
      tone: "warning",
      count,
    };
  }

  const categories = new Set(parts.map((part) => toolCategory(part.label)));
  const hasDocument = categories.has("document");
  const hasWeb = categories.has("web") || categories.has("fetch");
  const hasSourceReview = categories.has("review");

  if (hasDocument && hasWeb) {
    return { label: "Used document + web sources", tone: "complete", count };
  }
  if (hasDocument) {
    return { label: "Used document sources", tone: "complete", count };
  }
  if (hasWeb) {
    return { label: "Used web sources", tone: "complete", count };
  }
  if (hasSourceReview) {
    return { label: "Reviewed sources", tone: "complete", count };
  }
  return { label: `Used ${count} tool${count === 1 ? "" : "s"}`, tone: "complete", count };
}

function activeToolLabel(toolName: string): string {
  const normalized = toolName.toLowerCase();
  if (normalized.includes("service checking")) return "Checking service";
  if (normalized.includes("service waking")) return "Waking service";

  switch (normalized) {
    case "list_files":
      return "Reading attachments";
    case "read_file":
      return "Reading attached file";
    case "search_document":
      return "Searching document";
    case "quote_document":
      return "Checking document evidence";
    case "summarize_document":
      return "Summarizing document";
    case "compare_documents":
      return "Comparing documents";
    case "search_web":
    case "search_multi_query":
      return "Searching the web";
    case "fetch_url":
      return "Opening source";
    case "rank_sources":
      return "Reviewing sources";
    case "extract_source_facts":
      return "Extracting facts";
    case "build_citations":
      return "Building citations";
    case "get_datetime":
      return "Checking the date";
    case "calculate":
      return "Calculating";
    default:
      return humanizeToolName(toolName);
  }
}

function toolCategory(toolName: string): "document" | "web" | "fetch" | "review" | "utility" | "service" | "other" {
  const normalized = toolName.toLowerCase();
  if (
    normalized.includes("document") ||
    normalized === "list_files" ||
    normalized === "read_file" ||
    normalized === "quote_document" ||
    normalized === "summarize_document" ||
    normalized === "compare_documents"
  ) {
    return "document";
  }
  if (normalized === "search_web" || normalized === "search_multi_query") {
    return "web";
  }
  if (normalized === "fetch_url") {
    return "fetch";
  }
  if (
    normalized === "rank_sources" ||
    normalized === "extract_source_facts" ||
    normalized === "build_citations"
  ) {
    return "review";
  }
  if (normalized === "get_datetime" || normalized === "calculate") {
    return "utility";
  }
  if (normalized.includes("service ")) {
    return "service";
  }
  return "other";
}

function humanizeToolName(toolName: string): string {
  const words = toolName
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!words) return "Using tool";
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function CitationMarker({
  href,
  source,
}: {
  href: string;
  source: SourcePreview;
}) {
  const label = source.citationIndex
    ? isDocumentSource(source)
      ? `file:${source.citationIndex}`
      : String(source.citationIndex)
    : "";
  const title = source.title || source.domain || "Source";
  const isDocument = isDocumentSource(source);

  return (
    <span className="inline-citation">
      <a
        className={cx("citation-link", isDocument && "citation-link--document")}
        href={href}
        target={isDocument ? undefined : "_blank"}
        rel="noreferrer"
        aria-label={`Open source ${label}: ${title}`}
      >
        {label}
      </a>
      <span className="citation-popover" role="tooltip">
        <a href={href} target={isDocument ? undefined : "_blank"} rel="noreferrer">
          <span>{label}</span>
          <strong>{title}</strong>
          {(source.locator || source.domain) && (
            <em>{source.locator || source.domain}</em>
          )}
          {source.snippet && <small>{source.snippet}</small>}
        </a>
      </span>
    </span>
  );
}

function MessageSources({ sources }: { sources: SourcePreview[] }) {
  const usableSources = sources.filter(
    (source) => source.url || isDocumentSource(source),
  );
  if (!usableSources.length) return null;
  const sourceLabel = usableSources.every(isDocumentSource)
    ? "Document sources"
    : "Sources";

  return (
    <details className="message-sources">
      <summary className="message-sources__header">
        <span>{sourceLabel}</span>
        <strong>{usableSources.length}</strong>
      </summary>
      <ol className="source-list">
        {usableSources.map((source) => (
          <li key={source.id || source.url} id={sourceAnchorId(source)}>
            <a
              className={cx(isDocumentSource(source) && "source-list__item--document")}
              href={source.url || `#${sourceAnchorId(source)}`}
              target={source.url ? "_blank" : undefined}
              rel="noreferrer"
            >
              <span className="source-list__index">
                {isDocumentSource(source)
                  ? `file:${source.citationIndex ?? ""}`
                  : source.citationIndex ?? ""}
              </span>
              <span className="source-list__body">
                <strong>{source.title || source.domain || source.url}</strong>
                <span>{source.locator || source.domain || source.url}</span>
                {source.snippet && <em>{source.snippet}</em>}
              </span>
              {source.url ? <ExternalLink size={13} strokeWidth={iconStroke} /> : null}
            </a>
          </li>
        ))}
      </ol>
    </details>
  );
}

function MessageFooter({
  message,
  sources,
  onCopy,
  onCopyWithSources,
  onCopySources,
  onRetry,
  canRetry,
}: {
  message: ChatMessage;
  sources: SourcePreview[];
  onCopy: () => void | Promise<void>;
  onCopyWithSources: () => void | Promise<void>;
  onCopySources: () => void | Promise<void>;
  onRetry: () => void;
  canRetry: boolean;
}) {
  return (
    <footer className="assistant-message__footer">
      {sources.length > 0 && <MessageSources sources={sources} />}
      <div className="message-actions-row">
        <MessageActions
          hasSources={sources.length > 0}
          onCopy={onCopy}
          onCopyWithSources={onCopyWithSources}
          onCopySources={onCopySources}
          onRetry={onRetry}
          canRetry={canRetry}
        />
        <MessageMetrics metrics={message.metrics} />
      </div>
    </footer>
  );
}

function MessageActions({
  hasSources,
  onCopy,
  onCopyWithSources,
  onCopySources,
  onRetry,
  canRetry,
}: {
  hasSources: boolean;
  onCopy: () => void | Promise<void>;
  onCopyWithSources: () => void | Promise<void>;
  onCopySources: () => void | Promise<void>;
  onRetry: () => void;
  canRetry: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const moreRef = useRef<HTMLDetailsElement>(null);

  useEffect(() => {
    function handlePointerDown(event: PointerEvent) {
      const element = moreRef.current;
      if (!element?.open || !event.target) return;
      if (!element.contains(event.target as Node)) {
        element.open = false;
      }
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && moreRef.current?.open) {
        moreRef.current.open = false;
      }
    }

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, []);

  async function copy() {
    await onCopy();
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  }

  return (
    <div className="message-actions" aria-label="Message actions">
      <button
        className="message-action-button"
        onClick={() => void copy()}
        type="button"
        title={copied ? "Copied" : "Copy"}
        aria-label={copied ? "Copied" : "Copy"}
      >
        {copied ? (
          <Check size={14} strokeWidth={iconStroke} />
        ) : (
          <Copy size={14} strokeWidth={iconStroke} />
        )}
      </button>
      <button
        className="message-action-button"
        onClick={onRetry}
        type="button"
        title="Retry"
        aria-label="Retry"
        disabled={!canRetry}
      >
        <RotateCcw size={14} strokeWidth={iconStroke} />
      </button>
      <details className="message-more" ref={moreRef}>
        <summary
          className="message-action-button"
          title="More"
          aria-label="More message actions"
        >
          <MoreHorizontal size={15} strokeWidth={iconStroke} />
        </summary>
        <div className="message-more__popover">
          <button type="button" onClick={() => void onCopy()}>
            Copy markdown
          </button>
          <button type="button" onClick={() => void onCopyWithSources()}>
            Copy with sources
          </button>
          {hasSources && (
            <button type="button" onClick={() => void onCopySources()}>
              Copy sources
            </button>
          )}
        </div>
      </details>
    </div>
  );
}

function MessageMetrics({ metrics }: { metrics: ChatMessage["metrics"] }) {
  const items = messageMetricItems(metrics);
  if (!items.length) return null;

  return (
    <dl className="message-metrics" aria-label="Message metrics">
      {items.map((item) => (
        <div key={item.label}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function ToolTraceItem({
  part,
}: {
  part: Extract<MessagePart, { type: "tool" }>;
}) {
  return (
    <li className={cx("tool-trace__item", `tool-trace__item--${part.status}`)}>
      <span className="tool-trace__icon" aria-hidden="true">
        {part.status === "running" && <Loader2 size={12} strokeWidth={iconStroke} />}
        {part.status === "complete" && <Check size={12} strokeWidth={iconStroke} />}
        {part.status === "error" && (
          <TriangleAlert size={12} strokeWidth={iconStroke} />
        )}
      </span>
      <div className="tool-trace__content">
        <div className="tool-trace__line">
          <strong>{toolLabel(part.label)}</strong>
          <span>{toolStatus(part)}</span>
        </div>
        {part.input && (
          <details className="tool-trace__details">
            <summary>Input</summary>
            <code>{JSON.stringify(part.input, null, 2)}</code>
          </details>
        )}
        {part.resultPreview?.length ? (
          <details className="tool-trace__details" open>
            <summary>Results</summary>
            <code>
              {part.resultPreview
                .map((result, index) =>
                  [
                    `${index + 1}. ${result.title || "Untitled"}`,
                    result.url,
                    result.domain ? `domain: ${result.domain}` : "",
                    result.source ? `source: ${result.source}` : "",
                    result.status ? `status: ${result.status}` : "",
                    result.snippet,
                  ]
                    .filter(Boolean)
                    .join("\n"),
                )
                .join("\n\n")}
            </code>
          </details>
        ) : null}
        {part.output && (part.output.stdout || part.output.stderr) ? (
          <details className="tool-trace__details" open>
            <summary>Output</summary>
            {part.output.stdout && <code>{part.output.stdout}</code>}
            {part.output.stderr && (
              <code className="tool-trace__stderr">{part.output.stderr}</code>
            )}
            {part.output.timed_out && (
              <code className="tool-trace__stderr">Execution timed out.</code>
            )}
          </details>
        ) : null}
        {part.artifacts?.length ? <ArtifactList artifacts={part.artifacts} /> : null}
      </div>
    </li>
  );
}

function ArtifactList({ artifacts }: { artifacts: ArtifactRef[] }) {
  return (
    <ul className="artifact-list">
      {artifacts.map((artifact) => (
        <li key={artifact.id} className="artifact-list__item">
          <a
            className="artifact-list__link"
            href={artifactDownloadUrl(artifact.id)}
            download={artifact.filename}
          >
            <Download size={13} strokeWidth={iconStroke} />
            <span className="artifact-list__name">{artifact.filename}</span>
            <span className="artifact-list__size">{formatArtifactSize(artifact.size_bytes)}</span>
          </a>
        </li>
      ))}
    </ul>
  );
}

function formatArtifactSize(sizeBytes: number): string {
  if (sizeBytes < 1024) return `${sizeBytes} B`;
  if (sizeBytes < 1024 * 1024) return `${(sizeBytes / 1024).toFixed(1)} KB`;
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`;
}

function EmptyState({ onPickPrompt }: { onPickPrompt: (prompt: string) => void }) {
  const prompts = [
    {
      label: "Research",
      text: "Research the latest reliable sources on a topic and summarize the practical takeaways.",
    },
    {
      label: "Compare",
      text: "Compare two products, tools, or ideas with clear tradeoffs and source links.",
    },
    {
      label: "Troubleshoot",
      text: "Investigate a problem, identify likely causes, and give me a step-by-step debug path.",
    },
  ];

  return (
    <section className="empty-state">
      <div className="empty-state__mark">
        <AristotleMark className="empty-state__mark-image" />
      </div>
      <h2>Ask Aristotle.</h2>
      <p>
        A focused agent console for questions that need reasoning, tools, and
        source-backed search.
      </p>
      <div className="prompt-grid">
        {prompts.map((prompt) => (
          <button
            key={prompt.label}
            className="prompt-card"
            type="button"
            onClick={() => onPickPrompt(prompt.text)}
          >
            <span className="prompt-card__label">{prompt.label}</span>
            <span className="prompt-card__text">{prompt.text}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

function humanize(value: string): string {
  return value.replace(/[_-]/g, " ");
}

function groupMessageParts(parts: MessagePart[]): MessagePartGroup[] {
  const groups: MessagePartGroup[] = [];
  let toolParts: Extract<MessagePart, { type: "tool" }>[] = [];

  function flushTools() {
    if (!toolParts.length) return;
    groups.push({
      id: `tools-${toolParts[0].id}-${toolParts.length}`,
      type: "tools",
      parts: toolParts,
    });
    toolParts = [];
  }

  for (const part of parts) {
    if (part.type === "tool") {
      toolParts.push(part);
      continue;
    }

    flushTools();
    groups.push({ id: part.id, type: "single", part });
  }

  flushTools();
  return groups;
}

function toolLabel(label: string): string {
  const normalized = humanize(label).toLowerCase();
  if (normalized.includes("search")) {
    if (normalized.includes("ready")) return "Search ready";
    if (normalized.includes("waking")) return "Waking search";
    if (normalized.includes("checking")) return "Checking search";
    return "Search web";
  }
  if (normalized.includes("model")) {
    if (normalized.includes("ready")) return "Model ready";
    if (normalized.includes("waking")) return "Waking model";
    if (normalized.includes("checking")) return "Checking model";
    return "Model";
  }
  if (normalized.includes("ready")) return "Service ready";
  if (normalized.includes("waking")) return "Waking service";
  if (normalized.includes("checking")) return "Checking service";
  return humanize(label);
}

function toolStatus(part: Extract<MessagePart, { type: "tool" }>): string {
  if (part.status === "running") return "Running";
  if (part.status === "error") return part.message || "Failed";
  if (part.resultCount === undefined) return "Done";
  return `${part.resultCount} result${part.resultCount === 1 ? "" : "s"}`;
}

function canRetryAssistantMessage(
  messages: ChatMessage[],
  index: number,
  isRunning: boolean,
) {
  if (isRunning) return false;
  const message = messages[index];
  if (message.role !== "assistant" || message.status === "streaming") {
    return false;
  }
  return messages
    .slice(0, index)
    .some((item) => item.role === "user" && item.content?.trim());
}

function messageMetricItems(metrics: ChatMessage["metrics"]) {
  if (!metrics) return [];

  const estimatedPrefix = metrics.tokenSource === "estimated" ? "~" : "";
  return [
    metrics.ttftMs !== null && metrics.ttftMs !== undefined
      ? { label: "TTFT", value: formatDuration(metrics.ttftMs) }
      : null,
    metrics.tps !== null && metrics.tps !== undefined
      ? { label: "TPS", value: `${estimatedPrefix}${formatNumber(metrics.tps)}` }
      : null,
    metrics.outputTokens !== null && metrics.outputTokens !== undefined
      ? {
          label: "TOK",
          value: `${estimatedPrefix}${formatNumber(metrics.outputTokens)}`,
        }
      : null,
    metrics.durationMs !== null && metrics.durationMs !== undefined
      ? { label: "TIME", value: formatDuration(metrics.durationMs) }
      : null,
  ].filter((item): item is { label: string; value: string } => Boolean(item));
}

function formatDuration(ms: number) {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 10_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms / 1000)}s`;
}

function formatNumber(value: number) {
  if (Number.isInteger(value)) return String(value);
  return value.toFixed(1);
}

function stripDuplicateCitationList(text: string): string {
  return text
    .replace(
      /\n{1,3}(?:#{1,4}\s*)?(?:citations|references|sources)\s*:?\s*\n(?:\s*(?:[-*]\s*)?\[\d{1,2}\]\s+https?:\/\/\S+\s*)+$/i,
      "",
    )
    .trimEnd();
}

function linkCitationMarkers(text: string, sources: SourcePreview[]): string {
  return text
    .replace(/\[file:(\d{1,2})\](?!\()/gi, (match, rawIndex: string) => {
      const source = sources.find(
        (item) => item.citationIndex === Number(rawIndex) && isDocumentSource(item),
      );
      if (!source) return match;
      return `[file:${rawIndex}](${citationHref(source)})`;
    })
    .replace(/\[(\d{1,2})\](?!\()/g, (match, rawIndex: string) => {
      const source = sources.find(
        (item) => item.citationIndex === Number(rawIndex) && item.url,
      );
      if (!source?.url) return match;
      return `[${rawIndex}](${source.url})`;
    });
}

function sourceForHref(
  href: string | undefined,
  sources: SourcePreview[],
): SourcePreview | undefined {
  if (!href) return undefined;
  if (href.startsWith("#source-")) {
    return sources.find((source) => citationHref(source) === href);
  }
  return sources.find((source) => source.url && sameSourceUrl(source.url, href));
}

function citationText(children: unknown): boolean {
  const text = childrenText(children).trim();
  return /^\[?(?:file:)?\d{1,2}\]?$/.test(text);
}

function childrenText(children: unknown): string {
  if (typeof children === "string" || typeof children === "number") {
    return String(children);
  }
  if (Array.isArray(children)) {
    return children.map(childrenText).join("");
  }
  return "";
}

function sourceTitle(source: SourcePreview): string {
  return [
    source.title || source.domain || "Source",
    source.locator || source.domain,
    source.snippet,
  ]
    .filter(Boolean)
    .join("\n");
}

function citationHref(source: SourcePreview): string {
  if (source.url) return source.url;
  return `#${sourceAnchorId(source)}`;
}

function sourceAnchorId(source: SourcePreview): string {
  const key =
    source.chunk_id ||
    source.chunkId ||
    source.id ||
    source.file_id ||
    source.fileId ||
    String(source.citationIndex || "source");
  return `source-${key.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
}

function providerLabel(provider: ModelProviderState): string {
  if (provider.provider === "fallback") return "Fallback";
  if (provider.model?.includes("GLM-5.2")) return "GLM-5.2";
  if (provider.model) return provider.model.split("/").pop() || provider.model;
  if (provider.provider === "primary") return "Primary";
  return "Model";
}

function healthState(
  runState: RunState,
  services: ServicesResponse | null,
  isWakingServices?: boolean,
): { label: string; tone: "ready" | "busy" | "warn"; detail: string } {
  if (runState === "connecting" || runState === "warming" || isWakingServices) {
    return {
      label: "Waking",
      tone: "busy",
      detail: "Aristotle is connecting to its services.",
    };
  }

  if (runState === "streaming") {
    return {
      label: "Running",
      tone: "busy",
      detail: "Aristotle is responding.",
    };
  }

  if (runState === "error") {
    return {
      label: "Check",
      tone: "warn",
      detail: "The last run needs attention.",
    };
  }

  if (!services) {
    return {
      label: "Checking",
      tone: "busy",
      detail: "Checking service health.",
    };
  }

  if (!services.model.ok || !services.search.ok) {
    return {
      label: "Degraded",
      tone: "warn",
      detail: `Model: ${serviceSummary(services.model)}. Search: ${serviceSummary(services.search)}.`,
    };
  }

  return {
    label: "Healthy",
    tone: "ready",
    detail: `Model: ${serviceSummary(services.model)}. Search: ${serviceSummary(services.search)}.`,
  };
}

function cx(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}
