import {
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Download,
  ExternalLink,
  FileCode2,
  FileImage,
  FileText,
  RefreshCw,
  X,
} from "lucide-react";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { presentationContentUrl } from "./api";
import type { PresentedArtifact } from "./types";
import { latestByPath, parseCsv } from "./workspaceUtils";

type ArtifactPanelProps = {
  artifacts: PresentedArtifact[];
  activeId: string | null;
  onSelect: (artifactId: string) => void;
  onClose: () => void;
};

export function ArtifactPanel({
  artifacts,
  activeId,
  onSelect,
  onClose,
}: ArtifactPanelProps) {
  const isMobile = useMediaQuery("(max-width: 820px)");
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const files = useMemo(() => latestByPath(artifacts), [artifacts]);
  const active =
    artifacts.find((artifact) => artifact.id === activeId) ??
    files[files.length - 1];
  // Oldest first, so the version stepper reads left-to-right as time moving forward.
  const versions = active
    ? artifacts
        .filter((artifact) => artifact.path === active.path)
        .sort((left, right) => left.version - right.version)
    : [];

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (isMobile && !dialog.open) {
      dialog.showModal();
    } else if (!isMobile && dialog.open) {
      dialog.close();
    }
  }, [isMobile]);

  if (!active) return null;

  return (
    <dialog
      ref={dialogRef}
      className="artifact-workspace"
      open={!isMobile}
      aria-labelledby="artifact-workspace-title"
      onCancel={(event) => {
        event.preventDefault();
        // Escape peels one layer at a time: the file menu before the panel.
        if (menuOpen) {
          setMenuOpen(false);
          return;
        }
        onClose();
      }}
    >
      <header className="artifact-workspace__header">
        {files.length > 1 ? (
          <FileSwitcher
            files={files}
            active={active}
            open={menuOpen}
            onOpenChange={setMenuOpen}
            onSelect={onSelect}
          />
        ) : (
          <div className="artifact-workspace__identity">
            <span aria-hidden="true">
              <ArtifactIcon mimeType={active.mimeType} />
            </span>
            <h2 id="artifact-workspace-title">
              {active.title || fileName(active.path)}
            </h2>
          </div>
        )}
        <div className="artifact-workspace__actions">
          <a
            className="artifact-action"
            href={presentationContentUrl(active.id, { preview: isHtml(active) })}
            target="_blank"
            rel="noreferrer"
            aria-label={`Open ${fileName(active.path)} in a new tab`}
            title="Open in new tab"
          >
            <ExternalLink size={16} strokeWidth={1.8} />
          </a>
          <a
            className="artifact-action"
            href={presentationContentUrl(active.id, { download: true })}
            download={fileName(active.path)}
            aria-label={`Download ${fileName(active.path)}`}
            title="Download file"
          >
            <Download size={16} strokeWidth={1.8} />
          </a>
          <button
            className="artifact-action"
            type="button"
            onClick={onClose}
            aria-label="Close artifact workspace"
            title="Close artifact workspace"
          >
            <X size={17} strokeWidth={1.8} />
          </button>
        </div>
      </header>

      <div className="artifact-stage" aria-label="Artifact preview">
        <ArtifactPreview key={active.id} artifact={active} />
      </div>

      <footer className="artifact-workspace__footer">
        <p className="artifact-workspace__meta">
          {fileTypeLabel(active.mimeType)}
          {active.sizeBytes !== undefined &&
            ` · ${formatFileSize(active.sizeBytes)}`}
        </p>
        {versions.length > 1 && (
          <VersionStepper
            versions={versions}
            active={active}
            onSelect={onSelect}
          />
        )}
      </footer>
    </dialog>
  );
}

function FileSwitcher({
  files,
  active,
  open,
  onOpenChange,
  onSelect,
}: {
  files: PresentedArtifact[];
  active: PresentedArtifact;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSelect: (artifactId: string) => void;
}) {
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) onOpenChange(false);
    };
    // Non-modal on desktop, so the dialog's own cancel never fires — close here.
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onOpenChange(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open, onOpenChange]);

  return (
    <div className="artifact-switcher" ref={rootRef}>
      <button
        type="button"
        className="artifact-switcher__trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => onOpenChange(!open)}
      >
        <span aria-hidden="true">
          <ArtifactIcon mimeType={active.mimeType} />
        </span>
        <h2 id="artifact-workspace-title">
          {active.title || fileName(active.path)}
        </h2>
        <ChevronDown size={14} strokeWidth={2} aria-hidden="true" />
      </button>
      {open && (
        <div className="artifact-switcher__menu" role="menu">
          {files.map((file) => {
            const selected = file.path === active.path;
            return (
              <button
                key={file.path}
                type="button"
                role="menuitem"
                className="artifact-switcher__item"
                aria-current={selected ? "true" : undefined}
                onClick={() => {
                  onSelect(file.id);
                  onOpenChange(false);
                }}
              >
                <span aria-hidden="true">
                  <ArtifactIcon mimeType={file.mimeType} />
                </span>
                <span className="artifact-switcher__item-name">
                  {file.title || fileName(file.path)}
                </span>
                {selected && (
                  <Check size={14} strokeWidth={2.2} aria-hidden="true" />
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function VersionStepper({
  versions,
  active,
  onSelect,
}: {
  versions: PresentedArtifact[];
  active: PresentedArtifact;
  onSelect: (artifactId: string) => void;
}) {
  const index = versions.findIndex((version) => version.id === active.id);
  const older = versions[index - 1];
  const newer = versions[index + 1];
  return (
    <div className="artifact-versions">
      <button
        type="button"
        className="artifact-step"
        disabled={!older}
        onClick={() => older && onSelect(older.id)}
        aria-label="Previous version"
      >
        <ChevronLeft size={15} strokeWidth={2} aria-hidden="true" />
      </button>
      <span aria-live="polite">
        Version {index + 1} of {versions.length}
      </span>
      <button
        type="button"
        className="artifact-step"
        disabled={!newer}
        onClick={() => newer && onSelect(newer.id)}
        aria-label="Next version"
      >
        <ChevronRight size={15} strokeWidth={2} aria-hidden="true" />
      </button>
    </div>
  );
}

function ArtifactPreview({ artifact }: { artifact: PresentedArtifact }) {
  const mime = artifact.mimeType;
  if (mime.startsWith("image/")) {
    return <ImagePreview artifact={artifact} />;
  }
  if (mime === "application/pdf") {
    return <FramePreview artifact={artifact} title="PDF preview" />;
  }
  if (isHtml(artifact)) {
    return <FramePreview artifact={artifact} title="Interactive HTML preview" html />;
  }
  if (
    mime.startsWith("text/") ||
    mime.includes("json") ||
    mime.includes("javascript")
  ) {
    return <TextPreview artifact={artifact} />;
  }
  return <UnsupportedPreview artifact={artifact} />;
}

function FramePreview({
  artifact,
  title,
  html = false,
}: {
  artifact: PresentedArtifact;
  title: string;
  html?: boolean;
}) {
  const [loaded, setLoaded] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const url = presentationContentUrl(artifact.id, { preview: html });
  return (
    <div className="artifact-frame-shell">
      {!loaded && <PreviewSkeleton label={`Loading ${fileName(artifact.path)}`} />}
      <iframe
        key={retryKey}
        className={loaded ? "artifact-frame" : "artifact-frame artifact-frame--loading"}
        src={url}
        title={`${title}: ${artifact.title || fileName(artifact.path)}`}
        sandbox={html ? "allow-scripts allow-popups allow-forms" : undefined}
        onLoad={() => setLoaded(true)}
      />
      {!loaded && (
        <button
          className="artifact-frame-shell__retry"
          type="button"
          onClick={() => {
            setLoaded(false);
            setRetryKey((current) => current + 1);
          }}
        >
          <RefreshCw size={15} strokeWidth={1.8} />
          Retry preview
        </button>
      )}
    </div>
  );
}

function ImagePreview({ artifact }: { artifact: PresentedArtifact }) {
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [retryKey, setRetryKey] = useState(0);
  const url = presentationContentUrl(artifact.id);
  if (state === "error") {
    return (
      <PreviewError
        artifact={artifact}
        detail="The image could not be loaded. The file may be missing or unavailable."
        onRetry={() => {
          setState("loading");
          setRetryKey((current) => current + 1);
        }}
      />
    );
  }
  return (
    <div className="artifact-image-shell">
      {state === "loading" && (
        <PreviewSkeleton label={`Loading ${fileName(artifact.path)}`} />
      )}
      <img
        key={retryKey}
        className={state === "ready" ? "artifact-image" : "artifact-image is-loading"}
        src={url}
        alt={artifact.title || `Preview of ${fileName(artifact.path)}`}
        onLoad={() => setState("ready")}
        onError={() => setState("error")}
      />
    </div>
  );
}

function TextPreview({ artifact }: { artifact: PresentedArtifact }) {
  const [retry, setRetry] = useState(0);
  const [state, setState] = useState<{
    status: "loading" | "ready" | "error";
    text: string;
  }>({ status: "loading", text: "" });
  const url = presentationContentUrl(artifact.id);

  useEffect(() => {
    const controller = new AbortController();
    fetch(url, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`Preview failed (${response.status})`);
        return response.text();
      })
      .then((text) => setState({ status: "ready", text }))
      .catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setState({ status: "error", text: "" });
      });
    return () => controller.abort();
  }, [retry, url]);

  if (state.status === "loading") {
    return <PreviewSkeleton label={`Loading ${fileName(artifact.path)}`} />;
  }
  if (state.status === "error") {
    return (
      <PreviewError
        artifact={artifact}
        detail="The preview could not be loaded. The workspace may be temporarily unavailable."
        onRetry={() => {
          setState({ status: "loading", text: "" });
          setRetry((current) => current + 1);
        }}
      />
    );
  }
  if (!state.text) {
    return (
      <div className="artifact-empty">
        <FileText size={24} strokeWidth={1.6} aria-hidden="true" />
        <h3>This file is empty</h3>
        <p>There is no content to preview yet.</p>
      </div>
    );
  }
  if (artifact.mimeType === "text/markdown") {
    return (
      <article className="artifact-markdown">
        <div className="artifact-markdown__body">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              a: ({ href, title, children }) => (
                <a
                  href={href}
                  title={title}
                  target={href?.startsWith("http") ? "_blank" : undefined}
                  rel={href?.startsWith("http") ? "noreferrer" : undefined}
                >
                  {children}
                </a>
              ),
              table: ({ children }) => (
                <div className="artifact-markdown__table-wrap">
                  <table>{children}</table>
                </div>
              ),
              img: ({ src, alt, title }) => (
                <figure>
                  <img src={src} alt={alt || ""} title={title} loading="lazy" />
                  {title && <figcaption>{title}</figcaption>}
                </figure>
              ),
              input: ({ type, checked }) =>
                type === "checkbox" ? (
                  <input
                    type="checkbox"
                    checked={checked}
                    readOnly
                    tabIndex={-1}
                    aria-hidden="true"
                  />
                ) : null,
            }}
          >
            {state.text}
          </ReactMarkdown>
        </div>
      </article>
    );
  }
  if (artifact.mimeType === "text/csv") {
    return <CsvTable text={state.text} />;
  }
  return (
    <pre className="artifact-code">
      <code>{state.text}</code>
    </pre>
  );
}

function CsvTable({ text }: { text: string }) {
  const rows = parseCsv(text).slice(0, 201);
  if (rows.length === 0 || (rows.length === 1 && rows[0].every((cell) => !cell))) {
    return <div className="artifact-empty">This dataset has no rows.</div>;
  }
  const [head, ...body] = rows;
  return (
    <div className="artifact-table-wrap">
      <table className="artifact-table">
        <caption>
          {body.length === 200 ? "Showing the first 200 rows" : `${body.length} rows`}
        </caption>
        <thead>
          <tr>
            {head.map((cell, index) => (
              <th key={`${cell}-${index}`} scope="col">
                {cell || `Column ${index + 1}`}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {head.map((_, cellIndex) => (
                <td key={cellIndex}>{row[cellIndex] ?? ""}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function UnsupportedPreview({ artifact }: { artifact: PresentedArtifact }) {
  return (
    <div className="artifact-empty">
      <FileText size={26} strokeWidth={1.5} aria-hidden="true" />
      <h3>Preview unavailable</h3>
      <p>Download this file to open it with an app on your device.</p>
      <a
        className="artifact-primary-action"
        href={presentationContentUrl(artifact.id, { download: true })}
        download={fileName(artifact.path)}
      >
        <Download size={16} strokeWidth={1.8} />
        Download file
      </a>
    </div>
  );
}

function PreviewError({
  artifact,
  detail,
  onRetry,
}: {
  artifact: PresentedArtifact;
  detail: string;
  onRetry: () => void;
}) {
  return (
    <div className="artifact-empty artifact-empty--error" role="alert">
      <h3>Preview failed</h3>
      <p>{detail}</p>
      <div className="artifact-empty__actions">
        <button type="button" onClick={onRetry}>
          <RefreshCw size={16} strokeWidth={1.8} />
          Retry preview
        </button>
        <a
          href={presentationContentUrl(artifact.id, { download: true })}
          download={fileName(artifact.path)}
        >
          <Download size={16} strokeWidth={1.8} />
          Download file
        </a>
      </div>
    </div>
  );
}

function PreviewSkeleton({ label }: { label: string }) {
  return (
    <div className="artifact-skeleton" role="status" aria-label={label}>
      <span />
      <span />
      <span />
    </div>
  );
}

function ArtifactIcon({ mimeType }: { mimeType: string }) {
  if (mimeType.startsWith("image/")) {
    return <FileImage size={17} strokeWidth={1.7} />;
  }
  if (mimeType.includes("html") || mimeType.includes("javascript")) {
    return <FileCode2 size={17} strokeWidth={1.7} />;
  }
  return <FileText size={17} strokeWidth={1.7} />;
}

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const media = window.matchMedia(query);
    const update = () => setMatches(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [query]);
  return matches;
}

function isHtml(artifact: PresentedArtifact): boolean {
  return artifact.mimeType === "text/html";
}

function fileName(path: string): string {
  return path.split("/").pop() || path;
}

function fileTypeLabel(mimeType: string): string {
  if (mimeType === "application/pdf") return "PDF";
  if (mimeType === "text/markdown") return "Markdown";
  if (mimeType === "text/csv") return "CSV";
  if (mimeType === "text/html") return "HTML";
  if (mimeType.includes("json")) return "JSON";
  if (mimeType.startsWith("image/")) return "Image";
  if (mimeType.startsWith("text/")) return "Text";
  return "File";
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
