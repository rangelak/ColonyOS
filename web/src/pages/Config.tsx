import { useEffect, useState } from "react";
import { fetchConfig, fetchHealth, updateConfig, updatePersonas } from "../api";
import type { ConfigResult, Persona } from "../types";
import PersonaCard from "../components/PersonaCard";
import InlineEdit from "../components/InlineEdit";

export default function Config() {
  const [config, setConfig] = useState<ConfigResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [writeEnabled, setWriteEnabled] = useState(false);

  useEffect(() => {
    fetchConfig()
      .then(setConfig)
      .catch((err) => setError(String(err)));
    fetchHealth()
      .then((h) => setWriteEnabled(h.write_enabled === "true"))
      .catch(() => {});
  }, []);

  async function handleConfigUpdate(updates: Partial<ConfigResult>) {
    try {
      const updated = await updateConfig(updates);
      setConfig(updated);
      setError(null);
    } catch (err) {
      setError(String(err));
    }
  }

  async function handlePersonasSave(personas: Persona[]) {
    try {
      const updated = await updatePersonas(personas);
      setConfig(updated);
      setError(null);
    } catch (err) {
      setError(String(err));
    }
  }

  function handleAddPersona() {
    if (!config) return;
    const newPersona: Persona = { role: "New Role", expertise: "", perspective: "", reviewer: false };
    handlePersonasSave([...config.personas, newPersona]);
  }

  function handleRemovePersona(index: number) {
    if (!config) return;
    const updated = config.personas.filter((_, i) => i !== index);
    handlePersonasSave(updated);
  }

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
            <dd className="text-gray-200">
              <InlineEdit
                value={config.project.name}
                onSave={(v) => handleConfigUpdate({ project: { ...config.project!, name: v } })}
                disabled={!writeEnabled}
              />
            </dd>
            <dt className="text-gray-500">Description</dt>
            <dd className="text-gray-200">
              <InlineEdit
                value={config.project.description}
                onSave={(v) => handleConfigUpdate({ project: { ...config.project!, description: v } })}
                disabled={!writeEnabled}
              />
            </dd>
            <dt className="text-gray-500">Stack</dt>
            <dd className="text-gray-200">
              <InlineEdit
                value={config.project.stack}
                onSave={(v) => handleConfigUpdate({ project: { ...config.project!, stack: v } })}
                disabled={!writeEnabled}
              />
            </dd>
          </dl>
        </section>
      )}

      {/* Model settings */}
      <section className="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-6">
        <h3 className="text-sm font-semibold text-gray-300 mb-2">Model Settings</h3>
        <dl className="grid grid-cols-2 gap-2 text-sm">
          <dt className="text-gray-500">Default model</dt>
          <dd className="text-gray-200 font-mono">
            {writeEnabled ? (
              <select
                value={config.model}
                onChange={(e) => handleConfigUpdate({ model: e.target.value as ConfigResult["model"] })}
                className="bg-gray-800 text-gray-200 text-sm rounded px-2 py-1 border border-gray-700"
              >
                <option value="opus">opus</option>
                <option value="sonnet">sonnet</option>
                <option value="haiku">haiku</option>
              </select>
            ) : (
              config.model
            )}
          </dd>
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
          <dd className="text-gray-200 font-mono">
            <InlineEdit
              value={config.budget.per_phase.toFixed(2)}
              onSave={(v) => handleConfigUpdate({ budget: { ...config.budget, per_phase: parseFloat(v) } })}
              type="number"
              disabled={!writeEnabled}
            />
          </dd>
          <dt className="text-gray-500">Per run</dt>
          <dd className="text-gray-200 font-mono">
            <InlineEdit
              value={config.budget.per_run.toFixed(2)}
              onSave={(v) => handleConfigUpdate({ budget: { ...config.budget, per_run: parseFloat(v) } })}
              type="number"
              disabled={!writeEnabled}
            />
          </dd>
          <dt className="text-gray-500">Max total</dt>
          <dd className="text-gray-200 font-mono">
            <InlineEdit
              value={config.budget.max_total_usd.toFixed(2)}
              onSave={(v) => handleConfigUpdate({ budget: { ...config.budget, max_total_usd: parseFloat(v) } })}
              type="number"
              disabled={!writeEnabled}
            />
          </dd>
          <dt className="text-gray-500">Max duration</dt>
          <dd className="text-gray-200">
            <InlineEdit
              value={String(config.budget.max_duration_hours)}
              onSave={(v) => handleConfigUpdate({ budget: { ...config.budget, max_duration_hours: parseFloat(v) } })}
              type="number"
              disabled={!writeEnabled}
            />
          </dd>
        </dl>
      </section>

      {/* Phases */}
      <section className="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-6">
        <h3 className="text-sm font-semibold text-gray-300 mb-2">Phase Toggles</h3>
        <div className="flex gap-4 text-sm">
          {Object.entries(config.phases).map(([phase, enabled]) => (
            <button
              key={phase}
              onClick={() => {
                if (writeEnabled) {
                  handleConfigUpdate({ phases: { ...config.phases, [phase]: !enabled } });
                }
              }}
              className={`px-2 py-1 rounded text-xs font-medium transition-colors ${
                enabled
                  ? "bg-emerald-900/40 text-emerald-400"
                  : "bg-gray-800 text-gray-500"
              } ${writeEnabled ? "cursor-pointer hover:opacity-80" : "cursor-default"}`}
            >
              {phase}
            </button>
          ))}
        </div>
      </section>

      {/* Personas */}
      <section className="mb-6">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-gray-300">Personas</h3>
          {writeEnabled && (
            <button
              onClick={handleAddPersona}
              className="px-3 py-1 bg-emerald-600 hover:bg-emerald-500 text-white text-xs rounded"
            >
              + Add Persona
            </button>
          )}
        </div>
        {config.personas.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {config.personas.map((p, i) => (
              <PersonaCard
                key={i}
                persona={p}
                editable={writeEnabled}
                onSave={(updated) => {
                  const personas = [...config.personas];
                  personas[i] = updated;
                  handlePersonasSave(personas);
                }}
                onRemove={() => handleRemovePersona(i)}
              />
            ))}
          </div>
        ) : (
          <p className="text-gray-500 text-sm">No personas configured.</p>
        )}
      </section>
    </div>
  );
}
