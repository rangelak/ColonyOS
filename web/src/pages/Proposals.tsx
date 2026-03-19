import { useEffect, useState } from "react";
import { fetchProposals } from "../api";
import type { ProposalEntry } from "../types";
import ArtifactPreview from "../components/ArtifactPreview";
import { formatTimestamp } from "../util";

export default function Proposals() {
  const [proposals, setProposals] = useState<ProposalEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchProposals()
      .then(setProposals)
      .catch((err) => setError(String(err)));
  }, []);

  if (error) {
    return (
      <div className="bg-red-900/30 border border-red-800 rounded-lg p-4 text-red-300">
        {error}
      </div>
    );
  }

  return (
    <div>
      <h2 className="text-xl font-bold text-gray-100 mb-4">CEO Proposals</h2>
      {proposals.length === 0 ? (
        <p className="text-gray-500 text-sm">No proposals found.</p>
      ) : (
        <div className="space-y-2">
          {proposals.map((p) => (
            <div key={p.path} className="bg-gray-900 border border-gray-800 rounded-lg p-4">
              <div className="flex items-center justify-between mb-1">
                <span className="text-sm font-medium text-gray-200">{p.filename}</span>
                <span className="text-xs text-gray-500">{formatTimestamp(p.modified_at)}</span>
              </div>
              <ArtifactPreview path={p.path} title="View content" />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
