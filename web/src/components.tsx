import {
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  Loader2,
  Pause,
  Plus,
  Send,
  TriangleAlert,
  Wrench,
} from "lucide-react";
import { useEffect, useRef } from "react";
import type { Dispatch, FormEvent, SetStateAction } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { serviceSummary } from "./api";
import type {
  ChatMessage,
  Conversation,
  MessagePart,
  ModelProviderState,
  RunState,
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
  onNewChat: () => void;
};

export function AppHeader({
  runState,
  services,
  modelProvider,
  onNewChat,
}: AppHeaderProps) {
  return (
    <header className="app-header">
      <div className="app-header__identity">
        <div className="app-header__title-block">
          <h1 className="app-header__title">Aristotle</h1>
        </div>
      </div>

      <div className="app-header__actions">
        <div className="status-cluster">
          <HealthBeat runState={runState} services={services} />
          <ModelProviderTag provider={modelProvider} />
        </div>
        <button
          className="icon-button icon-button--primary"
          onClick={onNewChat}
          title="New chat"
        >
          <Plus size={18} strokeWidth={iconStroke} />
        </button>
      </div>
    </header>
  );
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
};

export function ServiceAlert({ children }: ServiceAlertProps) {
  return <div className="service-alert">{children}</div>;
}

type MessageListProps = {
  conversation?: Conversation;
  detailsOpen: Record<string, boolean>;
  setDetailsOpen: Dispatch<SetStateAction<Record<string, boolean>>>;
  onCopyMessage: (message: ChatMessage) => void;
  onPickPrompt: (prompt: string) => void;
};

export function MessageList({
  conversation,
  detailsOpen,
  setDetailsOpen,
  onCopyMessage,
  onPickPrompt,
}: MessageListProps) {
  return (
    <div className="message-scroll">
      {conversation?.messages.length ? (
        conversation.messages.map((message) => (
          <MessageBubble
            key={message.id}
            message={message}
            detailsOpen={detailsOpen}
            setDetailsOpen={setDetailsOpen}
            onCopy={() => onCopyMessage(message)}
          />
        ))
      ) : (
        <EmptyState onPickPrompt={onPickPrompt} />
      )}
      <div id="conversation-end" />
    </div>
  );
}

type ComposerProps = {
  composer: string;
  isRunning: boolean;
  setComposer: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
  onStop: () => void;
};

export function Composer({
  composer,
  isRunning,
  setComposer,
  onSubmit,
  onStop,
}: ComposerProps) {
  return (
    <form className="composer" onSubmit={onSubmit}>
      <div className="composer__input-row">
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
}: {
  runState: RunState;
  services: ServicesResponse | null;
}) {
  const state = healthState(runState, services);

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
}: {
  message: ChatMessage;
  detailsOpen: Record<string, boolean>;
  setDetailsOpen: Dispatch<SetStateAction<Record<string, boolean>>>;
  onCopy: () => void;
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

  if (message.role === "user") {
    return <div className="message message--user">{message.content}</div>;
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
            />
          ))}
          {message.status === "streaming" && <span className="stream-caret" />}
        </div>

        <button className="copy-button" onClick={onCopy} type="button">
          <Copy size={14} strokeWidth={iconStroke} />
          Copy
        </button>
      </div>
    </article>
  );
}

type MessagePartGroup =
  | { id: string; type: "single"; part: MessagePart }
  | { id: string; type: "tools"; parts: Extract<MessagePart, { type: "tool" }>[] };

function MessagePartGroupView({
  group,
  toolTraceOpen,
}: {
  group: MessagePartGroup;
  toolTraceOpen: boolean;
}) {
  if (group.type === "tools") {
    return <ToolTrace parts={group.parts} defaultOpen={toolTraceOpen} />;
  }

  return <MessagePartView part={group.part} />;
}

function MessagePartView({ part }: { part: MessagePart }) {
  if (part.type === "text") {
    return (
      <div className="message-text">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{part.text}</ReactMarkdown>
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
      )}
    >
      <summary className="tool-trace__header">
        <span className="tool-trace__chevron" aria-hidden="true">
          <ChevronRight size={13} strokeWidth={iconStroke} />
        </span>
        <Wrench size={13} strokeWidth={iconStroke} />
        <span>Tool activity</span>
      </summary>
      <ol className="tool-trace__list">
        {parts.map((part) => (
          <ToolTraceItem key={part.id} part={part} />
        ))}
      </ol>
    </details>
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
                    result.source ? `source: ${result.source}` : "",
                  ]
                    .filter(Boolean)
                    .join("\n"),
                )
                .join("\n\n")}
            </code>
          </details>
        ) : null}
      </div>
    </li>
  );
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
): { label: string; tone: "ready" | "busy" | "warn"; detail: string } {
  if (runState === "connecting" || runState === "warming") {
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
