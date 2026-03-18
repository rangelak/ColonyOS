import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { launchRun } from "../api";

export default function RunLauncher() {
  const [prompt, setPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showConfirm, setShowConfirm] = useState(false);
  const navigate = useNavigate();

  async function handleLaunch() {
    setShowConfirm(false);
    setLoading(true);
    setError(null);
    try {
      const result = await launchRun(prompt);
      setPrompt("");
      navigate(`/runs/${encodeURIComponent(result.run_id)}`);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-6">
      <h3 className="text-sm font-semibold text-gray-300 mb-2">Launch Run</h3>
      <div className="flex gap-2">
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Describe what you want to build..."
          className="flex-1 bg-gray-800 text-gray-200 text-sm rounded px-3 py-2 border border-gray-700 focus:border-emerald-600 focus:outline-none resize-none"
          rows={2}
          disabled={loading}
        />
        <button
          onClick={() => setShowConfirm(true)}
          disabled={loading || !prompt.trim()}
          className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm font-medium rounded transition-colors self-end"
        >
          {loading ? "Launching..." : "Launch Run"}
        </button>
      </div>
      {error && (
        <p className="text-red-400 text-xs mt-2">{error}</p>
      )}
      {showConfirm && (
        <div className="mt-3 bg-gray-800 border border-gray-700 rounded p-3">
          <p className="text-sm text-gray-300 mb-2">Launch a run with this prompt?</p>
          <p className="text-xs text-gray-400 mb-3 italic">{prompt}</p>
          <p className="text-xs text-amber-400 mb-3">This will incur API costs.</p>
          <div className="flex gap-2">
            <button
              onClick={handleLaunch}
              className="px-3 py-1 bg-emerald-600 hover:bg-emerald-500 text-white text-xs rounded"
            >
              Confirm
            </button>
            <button
              onClick={() => setShowConfirm(false)}
              className="px-3 py-1 bg-gray-700 hover:bg-gray-600 text-gray-300 text-xs rounded"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
