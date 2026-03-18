import { useEffect, useState } from "react";
import { fetchArtifact } from "../api";

interface ArtifactPreviewProps {
  path: string;
  title?: string;
}

export default function ArtifactPreview({ path, title }: ArtifactPreviewProps) {
  const [content, setContent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (!expanded) return;

    fetchArtifact(path)
      .then((result) => setContent(result.content))
      .catch((err) => setError(String(err)));
  }, [path, expanded]);

  return (
    <div className="border border-gray-800 rounded mt-2">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full text-left px-3 py-2 text-xs text-gray-400 hover:text-gray-200 hover:bg-gray-800/50 transition-colors flex items-center gap-2"
      >
        <span className="text-gray-600">{expanded ? "▼" : "▶"}</span>
        {title || path}
      </button>
      {expanded && (
        <div className="px-3 pb-3">
          {error && (
            <p className="text-red-400 text-xs">{error}</p>
          )}
          {content === null && !error && (
            <p className="text-gray-500 text-xs">Loading...</p>
          )}
          {content !== null && (
            <pre className="text-xs text-gray-300 bg-gray-800/50 rounded p-3 overflow-auto max-h-96 whitespace-pre-wrap">
              {content}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
