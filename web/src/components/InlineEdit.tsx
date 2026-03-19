import { useState, useRef, useEffect } from "react";

interface InlineEditProps {
  value: string;
  onSave: (value: string) => void;
  type?: "text" | "number" | "textarea";
  className?: string;
  disabled?: boolean;
}

export default function InlineEdit({
  value,
  onSave,
  type = "text",
  className = "",
  disabled = false,
}: InlineEditProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement>(null);

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
    }
  }, [editing]);

  useEffect(() => {
    setDraft(value);
  }, [value]);

  function handleSave() {
    setEditing(false);
    if (draft !== value) {
      onSave(draft);
    }
  }

  function handleCancel() {
    setEditing(false);
    setDraft(value);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && type !== "textarea") {
      handleSave();
    } else if (e.key === "Escape") {
      handleCancel();
    }
  }

  if (disabled || !editing) {
    return (
      <span
        className={`cursor-pointer hover:bg-gray-800 rounded px-1 -mx-1 ${className}`}
        onClick={() => !disabled && setEditing(true)}
        title={disabled ? undefined : "Click to edit"}
      >
        {value || <span className="text-gray-600 italic">empty</span>}
      </span>
    );
  }

  if (type === "textarea") {
    return (
      <textarea
        ref={inputRef as React.RefObject<HTMLTextAreaElement>}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={handleSave}
        onKeyDown={handleKeyDown}
        className="bg-gray-800 text-gray-200 text-sm rounded px-2 py-1 w-full border border-emerald-600 focus:outline-none"
        rows={3}
      />
    );
  }

  return (
    <input
      ref={inputRef as React.RefObject<HTMLInputElement>}
      type={type}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={handleSave}
      onKeyDown={handleKeyDown}
      className="bg-gray-800 text-gray-200 text-sm rounded px-2 py-1 w-full border border-emerald-600 focus:outline-none"
    />
  );
}
