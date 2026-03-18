import { useEffect, useState } from "react";
import { fetchConfig } from "../api";
import type { ConfigResult } from "../types";
import PersonaCard from "../components/PersonaCard";

export default function Config() {
  const [config, setConfig] = useState<ConfigResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchConfig()
      .then(setConfig)
      .catch((err) => setError(String(err)));
  }, []);

  if (error) {
    return (
      <div className="bg-red-900/30 border border-red-800 rounded-lg p-4 text-red-300">
        {error}
      </div>
    );
  }

  if (!config) return <p className="text-gray-500">Loading...</p>;

  return (
    <div>
      <h2 className="text-xl font-bold text-gray-100 mb-4">Configuration</h2>

      {/* Project info */}
      {config.project && (
        <section className="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-6">
          <h3 className="text-sm font-semibold text-gray-300 mb-2">Project</h3>
          <dl className="grid grid-cols-2 gap-2 text-sm">
            <dt className="text-gray-500">Name</dt>
            <dd className="text-gray-200">{config.project.name}</dd>
            <dt className="text-gray-500">Description</dt>
            <dd className="text-gray-200">{config.project.description}</dd>
            <dt className="text-gray-500">Stack</dt>
            <dd className="text-gray-200">{config.project.stack}</dd>
          </dl>
        </section>
      )}

      {/* Model settings */}
      <section className="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-6">
        <h3 className="text-sm font-semibold text-gray-300 mb-2">Model Settings</h3>
        <dl className="grid grid-cols-2 gap-2 text-sm">
          <dt className="text-gray-500">Default model</dt>
          <dd className="text-gray-200 font-mono">{config.model}</dd>
          {Object.entries(config.phase_models).map(([phase, model]) => (
            <div key={phase} className="contents">
              <dt className="text-gray-500">{phase} model</dt>
              <dd className="text-gray-200 font-mono">{model}</dd>
            </div>
          ))}
        </dl>
      </section>

      {/* Budget */}
      <section className="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-6">
        <h3 className="text-sm font-semibold text-gray-300 mb-2">Budget</h3>
        <dl className="grid grid-cols-2 gap-2 text-sm">
          <dt className="text-gray-500">Per phase</dt>
          <dd className="text-gray-200 font-mono">${config.budget.per_phase.toFixed(2)}</dd>
          <dt className="text-gray-500">Per run</dt>
          <dd className="text-gray-200 font-mono">${config.budget.per_run.toFixed(2)}</dd>
          <dt className="text-gray-500">Max total</dt>
          <dd className="text-gray-200 font-mono">${config.budget.max_total_usd.toFixed(2)}</dd>
          <dt className="text-gray-500">Max duration</dt>
          <dd className="text-gray-200">{config.budget.max_duration_hours}h</dd>
        </dl>
      </section>

      {/* Phases */}
      <section className="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-6">
        <h3 className="text-sm font-semibold text-gray-300 mb-2">Phase Toggles</h3>
        <div className="flex gap-4 text-sm">
          {Object.entries(config.phases).map(([phase, enabled]) => (
            <span
              key={phase}
              className={`px-2 py-1 rounded text-xs font-medium ${
                enabled
                  ? "bg-emerald-900/40 text-emerald-400"
                  : "bg-gray-800 text-gray-500"
              }`}
            >
              {phase}
            </span>
          ))}
        </div>
      </section>

      {/* Personas */}
      {config.personas.length > 0 && (
        <section className="mb-6">
          <h3 className="text-sm font-semibold text-gray-300 mb-3">Personas</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {config.personas.map((p, i) => (
              <PersonaCard key={i} persona={p} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
