import {
  Download,
  ExternalLink,
  FileCode2,
  FileImage,
  FileText,
  Files,
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
  const files = useMemo(() => latestByPath(artifacts), [artifacts]);
  const active =
    artifacts.find((artifact) => artifact.id === activeId) ??
    files[files.length - 1];
  const versions = active
    ? artifacts
        .filter((artifact) => artifact.path === active.path)
        .sort((left, right) => right.version - left.version)
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
        onClose();
      }}
    >
      <header className="artifact-workspace__header">
        <div className="artifact-workspace__identity">
          <span className="artifact-workspace__file-icon" aria-hidden="true">
            <ArtifactIcon mimeType={active.mimeType} />
          </span>
          <div className="artifact-workspace__title-block">
            <h2 id="artifact-workspace-title">
              {active.title || fileName(active.path)}
            </h2>
            <p>
              {fileTypeLabel(active.mimeType)}
              {active.sizeBytes !== undefined
                ? ` · ${formatFileSize(active.sizeBytes)}`
                : ""}
            </p>
          </div>
        </div>
        <div className="artifact-workspace__actions">
          <a
            className="artifact-action"
            href={presentationContentUrl(active.id, { preview: isHtml(active) })}
            target="_blank"
            rel="noreferrer"
            aria-label={`Open ${fileName(active.path)} in a new tab`}
            title="Open in new tab"
          >
            <ExternalLink size={17} strokeWidth={1.8} />
          </a>
          <a
            className="artifact-action"
            href={presentationContentUrl(active.id, { download: true })}
            download={fileName(active.path)}
            aria-label={`Download ${fileName(active.path)}`}
            title="Download file"
          >
            <Download size={17} strokeWidth={1.8} />
          </a>
          <button
            className="artifact-action"
            type="button"
            onClick={onClose}
            aria-label="Close artifact workspace"
            title="Close artifact workspace"
          >
            <X size={18} strokeWidth={1.8} />
          </button>
        </div>
      </header>

      <div
        className={
          files.length > 1
            ? "artifact-workspace__content"
            : "artifact-workspace__content artifact-workspace__content--single"
        }
      >
        {files.length > 1 && (
          <nav className="artifact-navigator" aria-label="Artifacts in this conversation">
            <div className="artifact-navigator__label">
              <Files size={14} strokeWidth={1.8} aria-hidden="true" />
              <span>{files.length} files</span>
            </div>
            <div className="artifact-navigator__items">
              {files.map((file) => {
                const selected = file.path === active.path;
                return (
                  <button
                    key={file.path}
                    type="button"
                    className={
                      selected
                        ? "artifact-navigator__item artifact-navigator__item--active"
                        : "artifact-navigator__item"
                    }
                    aria-current={selected ? "true" : undefined}
                    onClick={() => onSelect(file.id)}
                  >
                    <span aria-hidden="true">
                      <ArtifactIcon mimeType={file.mimeType} />
                    </span>
                    <span>
                      <strong>{file.title || fileName(file.path)}</strong>
                      <small>{fileTypeLabel(file.mimeType)}</small>
                    </span>
                  </button>
                );
              })}
            </div>
          </nav>
        )}

        <section className="artifact-stage" aria-label="Artifact preview">
          {versions.length > 1 && (
            <div className="artifact-version">
              <label htmlFor="artifact-version-select">Version</label>
              <select
                id="artifact-version-select"
                value={active.id}
                onChange={(event) => onSelect(event.target.value)}
              >
                {versions.map((version) => (
                  <option key={version.id} value={version.id}>
                    v{version.version}
                    {version.createdAt
                      ? ` · ${formatTimestamp(version.createdAt)}`
                      : ""}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="artifact-stage__viewport">
            <ArtifactPreview key={active.id} artifact={active} />
          </div>
        </section>
      </div>
    </dialog>
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
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{state.text}</ReactMarkdown>
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

function formatTimestamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat(undefined, {
        hour: "numeric",
        minute: "2-digit",
      }).format(date);
}
