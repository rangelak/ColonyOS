import { useEffect, useState } from "react";
import { fetchReviews } from "../api";
import type { ReviewEntry } from "../types";
import ArtifactPreview from "../components/ArtifactPreview";
import { formatTimestamp } from "../util";

export default function Reviews() {
  const [reviews, setReviews] = useState<ReviewEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchReviews()
      .then(setReviews)
      .catch((err) => setError(String(err)));
  }, []);

  if (error) {
    return (
      <div className="bg-red-900/30 border border-red-800 rounded-lg p-4 text-red-300">
        {error}
      </div>
    );
  }

  // Group by subdirectory
  const grouped = reviews.reduce<Record<string, ReviewEntry[]>>((acc, r) => {
    const key = r.subdirectory || "root";
    if (!acc[key]) acc[key] = [];
    acc[key].push(r);
    return acc;
  }, {});

  return (
    <div>
      <h2 className="text-xl font-bold text-gray-100 mb-4">Reviews</h2>
      {reviews.length === 0 ? (
        <p className="text-gray-500 text-sm">No reviews found.</p>
      ) : (
        <div className="space-y-6">
          {Object.entries(grouped).map(([dir, entries]) => (
            <section key={dir}>
              <h3 className="text-sm font-semibold text-gray-300 mb-2 font-mono">{dir}</h3>
              <div className="space-y-2">
                {entries.map((r) => (
                  <div key={r.path} className="bg-gray-900 border border-gray-800 rounded-lg p-4">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-sm font-medium text-gray-200">{r.filename}</span>
                      <span className="text-xs text-gray-500">{formatTimestamp(r.modified_at)}</span>
                    </div>
                    <ArtifactPreview path={r.path} title="View content" />
                  </div>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
