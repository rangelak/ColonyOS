import { useEffect, useState, useMemo } from "react";
import { fetchArtifact } from "../api";

interface ArtifactPreviewProps {
  path: string;
  title?: string;
}

/**
 * Allowlisted HTML tags that renderMarkdown is permitted to produce.
 * sanitizeHtml strips everything else as defense-in-depth against XSS.
 */
const ALLOWED_TAGS = new Set([
  "h1", "h2", "h3", "h4", "h5", "h6",
  "strong", "em", "code", "pre",
  "ul", "li", "div", "br",
]);

/**
 * Strip any HTML tag not on the allowlist. Attributes are preserved only for
 * tags we create ourselves (class names for Tailwind styling). This acts as a
 * second layer of protection on top of HTML-entity escaping in renderMarkdown.
 */
function sanitizeHtml(html: string): string {
  // Match opening/closing tags; keep only those whose tag name is allowlisted.
  return html.replace(/<\/?([a-zA-Z][a-zA-Z0-9]*)\b[^>]*\/?>/g, (match, tag) => {
    return ALLOWED_TAGS.has(tag.toLowerCase()) ? match : "";
  });
}

/**
 * Convert a subset of markdown to HTML for rendering artifact content.
 * Handles headings, bold, italic, inline code, code blocks, and lists.
 *
 * Security: input is HTML-entity-escaped first so user content cannot inject
 * tags. The output is further filtered through sanitizeHtml (allowlisted tags
 * only) before being set via dangerouslySetInnerHTML.
 */
function renderMarkdown(md: string): string {
  // Escape HTML entities first to neutralize any raw HTML in the source
  let html = md
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  // Fenced code blocks (```...```)
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_match, _lang, code) => {
    return `<pre class="bg-gray-900 rounded p-2 my-2 overflow-auto"><code>${code.trim()}</code></pre>`;
  });

  // Process line-by-line for headings, lists, and paragraphs
  const lines = html.split("\n");
  const processed: string[] = [];
  let inList = false;

  for (const line of lines) {
    // Skip if inside a <pre> block (already handled)
    if (line.includes("<pre") || line.includes("</pre>")) {
      if (inList) {
        processed.push("</ul>");
        inList = false;
      }
      processed.push(line);
      continue;
    }

    // Headings
    const headingMatch = line.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      if (inList) {
        processed.push("</ul>");
        inList = false;
      }
      const level = headingMatch[1].length;
      const sizes: Record<number, string> = {
        1: "text-base font-bold mt-3 mb-1",
        2: "text-sm font-bold mt-2 mb-1",
        3: "text-sm font-semibold mt-2 mb-1",
        4: "text-xs font-semibold mt-1",
        5: "text-xs font-medium mt-1",
        6: "text-xs font-medium mt-1",
      };
      processed.push(`<h${level} class="${sizes[level] || ""}">${headingMatch[2]}</h${level}>`);
      continue;
    }

    // Unordered list items
    const listMatch = line.match(/^[-*]\s+(.+)$/);
    if (listMatch) {
      if (!inList) {
        processed.push('<ul class="list-disc list-inside my-1">');
        inList = true;
      }
      processed.push(`<li>${listMatch[1]}</li>`);
      continue;
    }

    // End list if we hit a non-list line
    if (inList && line.trim() === "") {
      processed.push("</ul>");
      inList = false;
    }

    // Regular line
    processed.push(line);
  }
  if (inList) {
    processed.push("</ul>");
  }

  html = processed.join("\n");

  // Inline formatting (applied after block-level processing)
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");
  html = html.replace(/`([^`]+)`/g, '<code class="bg-gray-900 px-1 rounded text-emerald-300">$1</code>');

  // Convert double newlines to paragraph breaks
  html = html.replace(/\n\n/g, '<div class="my-2"></div>');
  // Convert single newlines to line breaks (except inside pre)
  html = html.replace(/\n/g, "<br/>");

  // Defense-in-depth: strip any tags not in the allowlist
  return sanitizeHtml(html);
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

  const renderedHtml = useMemo(() => {
    if (content === null) return "";
    return renderMarkdown(content);
  }, [content]);

  return (
    <div className="border border-gray-800 rounded mt-2">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full text-left px-3 py-2 text-xs text-gray-400 hover:text-gray-200 hover:bg-gray-800/50 transition-colors flex items-center gap-2"
      >
        <span className="text-gray-600">{expanded ? "\u25BC" : "\u25B6"}</span>
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
            <div
              className="text-xs text-gray-300 bg-gray-800/50 rounded p-3 overflow-auto max-h-96 prose prose-invert prose-xs"
              dangerouslySetInnerHTML={{ __html: renderedHtml }}
            />
          )}
        </div>
      )}
    </div>
  );
}
