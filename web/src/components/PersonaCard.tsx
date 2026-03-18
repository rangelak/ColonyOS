import type { Persona } from "../types";

export default function PersonaCard({ persona }: { persona: Persona }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
      <div className="flex items-center gap-2 mb-2">
        <h3 className="font-semibold text-gray-200 text-sm">{persona.role}</h3>
        {persona.reviewer && (
          <span className="text-[10px] bg-emerald-900/50 text-emerald-400 px-1.5 py-0.5 rounded font-medium uppercase tracking-wider">
            Reviewer
          </span>
        )}
      </div>
      <p className="text-xs text-gray-400 mb-1">
        <span className="text-gray-500">Expertise:</span> {persona.expertise}
      </p>
      <p className="text-xs text-gray-400">
        <span className="text-gray-500">Perspective:</span> {persona.perspective}
      </p>
    </div>
  );
}
