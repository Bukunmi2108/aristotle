import { useEffect, useMemo, useState } from "react";
import { Download, FileText, X } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { workspaceFileUrl } from "./api";
import type { PresentedArtifact } from "./types";
import { latestByPath } from "./workspaceUtils";

type ArtifactPanelProps = {
  conversationId: string;
  artifacts: PresentedArtifact[];
  activePath: string | null;
  onSelectPath: (path: string) => void;
  onClose: () => void;
};

export function ArtifactPanel({
  conversationId,
  artifacts,
  activePath,
  onSelectPath,
  onClose,
}: ArtifactPanelProps) {
  const files = useMemo(() => latestByPath(artifacts), [artifacts]);
  const active =
    files.find((file) => file.path === activePath) ?? files[files.length - 1];

  if (!active) {
    return null;
  }

  return (
    <aside className="artifact-panel" aria-label="Presented artifact">
      <header className="artifact-panel__header">
        <div className="artifact-panel__meta">
          <FileText size={14} strokeWidth={1.75} />
          <span className="artifact-panel__title">
            {active.title || fileName(active.path)}
          </span>
          {active.version > 1 && (
            <span className="artifact-panel__version">v{active.version}</span>
          )}
        </div>
        <div className="artifact-panel__actions">
          <a
            className="artifact-panel__download"
            href={workspaceFileUrl(conversationId, active.path, { download: true })}
            download={fileName(active.path)}
            title="Download"
          >
            <Download size={14} strokeWidth={1.75} />
          </a>
          <button
            type="button"
            className="artifact-panel__close"
            onClick={onClose}
            aria-label="Close panel"
          >
            <X size={16} strokeWidth={1.75} />
          </button>
        </div>
      </header>

      {files.length > 1 && (
        <nav className="artifact-panel__tabs">
          {files.map((file) => (
            <button
              key={file.path}
              type="button"
              className={
                file.path === active.path
                  ? "artifact-panel__tab artifact-panel__tab--active"
                  : "artifact-panel__tab"
              }
              onClick={() => onSelectPath(file.path)}
            >
              {file.title || fileName(file.path)}
            </button>
          ))}
        </nav>
      )}

      <div className="artifact-panel__body">
        <ArtifactPreview conversationId={conversationId} artifact={active} />
      </div>
    </aside>
  );
}

function ArtifactPreview({
  conversationId,
  artifact,
}: {
  conversationId: string;
  artifact: PresentedArtifact;
}) {
  const url = workspaceFileUrl(conversationId, artifact.path);
  const mime = artifact.mimeType;

  if (mime.startsWith("image/")) {
    return <img className="artifact-preview__image" src={url} alt={artifact.path} />;
  }
  if (mime === "application/pdf") {
    return (
      <iframe className="artifact-preview__frame" src={url} title={artifact.path} />
    );
  }
  if (mime === "text/html") {
    // Isolated via the preview origin + a sandbox that omits allow-same-origin,
    // so agent HTML gets an opaque origin with no app/API access.
    const previewUrl = workspaceFileUrl(conversationId, artifact.path, {
      preview: true,
    });
    return (
      <iframe
        className="artifact-preview__frame"
        src={previewUrl}
        title={artifact.path}
        sandbox="allow-scripts allow-popups allow-forms"
      />
    );
  }
  // key={url} remounts on file change so state initializes fresh.
  return <TextPreview key={url} url={url} mime={mime} />;
}

function TextPreview({ url, mime }: { url: string; mime: string }) {
  const [state, setState] = useState<{ status: string; text: string }>({
    status: "loading",
    text: "",
  });

  useEffect(() => {
    let cancelled = false;
    fetch(url)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Preview failed (${response.status})`);
        }
        return response.text();
      })
      .then((text) => {
        if (!cancelled) {
          setState({ status: "ready", text });
        }
      })
      .catch((error) => {
        if (!cancelled) {
          console.error("Preview failed", error);
          setState({ status: "error", text: "" });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [url]);

  if (state.status === "loading") {
    return <div className="artifact-preview__note">Loading preview…</div>;
  }
  if (state.status === "error") {
    return <div className="artifact-preview__note">Could not load preview.</div>;
  }
  if (mime === "text/markdown") {
    return (
      <div className="artifact-preview__markdown">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{state.text}</ReactMarkdown>
      </div>
    );
  }
  if (mime === "text/csv") {
    return <CsvTable text={state.text} />;
  }
  return (
    <pre className="artifact-preview__code">
      <code>{state.text}</code>
    </pre>
  );
}

// Minimal CSV render; does not handle quoted commas/newlines (papaparse later).
function CsvTable({ text }: { text: string }) {
  const rows = text
    .trim()
    .split(/\r?\n/)
    .slice(0, 200)
    .map((line) => line.split(","));
  if (rows.length === 0) {
    return <div className="artifact-preview__note">Empty file.</div>;
  }
  const [head, ...body] = rows;
  return (
    <div className="artifact-preview__table-wrap">
      <table className="artifact-preview__table">
        <thead>
          <tr>
            {head.map((cell, index) => (
              <th key={index}>{cell}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => (
                <td key={cellIndex}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function fileName(path: string): string {
  return path.split("/").pop() || path;
}
