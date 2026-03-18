import { useState, useEffect } from "react";
import { getAuthToken, setAuthToken, fetchHealth } from "../api";

/**
 * Verify a token by making a GET to /api/auth/verify which requires auth.
 * A 200 means the token is valid; 401 means invalid.
 */
async function verifyToken(token: string): Promise<boolean> {
  try {
    const resp = await fetch("/api/auth/verify", {
      headers: { Authorization: `Bearer ${token}` },
    });
    return resp.status === 200;
  } catch {
    // Network error — assume valid to avoid blocking the user
    return true;
  }
}

/**
 * Prompts the user for a bearer token on first load when write mode is enabled.
 * Validates the token against the server before storing it.
 * Stores the token in localStorage for subsequent requests.
 */
export default function AuthTokenPrompt() {
  const [writeEnabled, setWriteEnabled] = useState(false);
  const [hasToken, setHasToken] = useState(false);
  const [input, setInput] = useState("");
  const [visible, setVisible] = useState(false);
  const [validating, setValidating] = useState(false);
  const [tokenError, setTokenError] = useState<string | null>(null);

  useEffect(() => {
    // Check if write mode is enabled and whether we already have a token
    const token = getAuthToken();
    if (token) {
      setHasToken(true);
      return;
    }

    fetchHealth()
      .then((health) => {
        if (health.write_enabled === "true") {
          setWriteEnabled(true);
          setVisible(true);
        }
      })
      .catch(() => {
        // Health check failed — don't prompt
      });
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed) return;

    setValidating(true);
    setTokenError(null);

    const valid = await verifyToken(trimmed);
    setValidating(false);

    if (!valid) {
      setTokenError("Invalid token — please check the token from the server terminal.");
      return;
    }

    setAuthToken(trimmed);
    setHasToken(true);
    setVisible(false);
  }

  function handleDismiss() {
    setVisible(false);
  }

  if (!visible || hasToken || !writeEnabled) return null;

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-gray-900 border border-gray-700 rounded-lg p-6 max-w-md w-full mx-4">
        <h2 className="text-sm font-bold text-gray-200 mb-2">Authentication Required</h2>
        <p className="text-xs text-gray-400 mb-4">
          Write mode is enabled. Enter the bearer token displayed in the server terminal to
          enable config editing, persona management, and run launching.
        </p>
        <form onSubmit={handleSubmit}>
          <input
            type="password"
            value={input}
            onChange={(e) => { setInput(e.target.value); setTokenError(null); }}
            placeholder="Paste bearer token here..."
            className="w-full bg-gray-800 text-gray-200 text-sm rounded px-3 py-2 border border-gray-700 focus:border-emerald-600 focus:outline-none mb-3"
            autoFocus
          />
          {tokenError && (
            <p className="text-red-400 text-xs mb-2">{tokenError}</p>
          )}
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={!input.trim() || validating}
              className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-700 disabled:text-gray-500 text-white text-xs font-medium rounded transition-colors"
            >
              {validating ? "Validating..." : "Save Token"}
            </button>
            <button
              type="button"
              onClick={handleDismiss}
              className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-gray-300 text-xs rounded transition-colors"
            >
              Skip (read-only)
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
