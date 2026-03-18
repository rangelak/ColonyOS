import { useState } from "react";
import type { Persona } from "../types";

interface PersonaCardProps {
  persona: Persona;
  editable?: boolean;
  onSave?: (persona: Persona) => void;
  onRemove?: () => void;
}

export default function PersonaCard({ persona, editable = false, onSave, onRemove }: PersonaCardProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Persona>({ ...persona });

  function handleSave() {
    setEditing(false);
    onSave?.(draft);
  }

  function handleCancel() {
    setEditing(false);
    setDraft({ ...persona });
  }

  if (editing && editable) {
    return (
      <div className="bg-gray-900 border border-emerald-700 rounded-lg p-4">
        <div className="space-y-2">
          <div>
            <label className="text-xs text-gray-500">Role</label>
            <input
              value={draft.role}
              onChange={(e) => setDraft({ ...draft, role: e.target.value })}
              className="w-full bg-gray-800 text-gray-200 text-sm rounded px-2 py-1 border border-gray-700"
            />
          </div>
          <div>
            <label className="text-xs text-gray-500">Expertise</label>
            <textarea
              value={draft.expertise}
              onChange={(e) => setDraft({ ...draft, expertise: e.target.value })}
              className="w-full bg-gray-800 text-gray-200 text-sm rounded px-2 py-1 border border-gray-700"
              rows={2}
            />
          </div>
          <div>
            <label className="text-xs text-gray-500">Perspective</label>
            <textarea
              value={draft.perspective}
              onChange={(e) => setDraft({ ...draft, perspective: e.target.value })}
              className="w-full bg-gray-800 text-gray-200 text-sm rounded px-2 py-1 border border-gray-700"
              rows={2}
            />
          </div>
          <label className="flex items-center gap-2 text-xs text-gray-400">
            <input
              type="checkbox"
              checked={draft.reviewer}
              onChange={(e) => setDraft({ ...draft, reviewer: e.target.checked })}
            />
            Reviewer
          </label>
          <div className="flex gap-2 pt-1">
            <button
              onClick={handleSave}
              className="px-3 py-1 bg-emerald-600 hover:bg-emerald-500 text-white text-xs rounded"
            >
              Save
            </button>
            <button
              onClick={handleCancel}
              className="px-3 py-1 bg-gray-700 hover:bg-gray-600 text-gray-300 text-xs rounded"
            >
              Cancel
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className={`bg-gray-900 border border-gray-800 rounded-lg p-4 ${editable ? "cursor-pointer hover:border-gray-700" : ""}`}
      onClick={() => editable && setEditing(true)}
    >
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
      {editable && onRemove && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          className="mt-2 text-xs text-red-400 hover:text-red-300"
        >
          Remove
        </button>
      )}
    </div>
  );
}
