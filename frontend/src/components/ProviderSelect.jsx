"use client";

export default function ProviderSelect({ value, onChange, disabled }) {
  return (
    <label className="provider-select">
      <span>Retrieval</span>
      <select
        aria-label="Retrieval provider"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        title={disabled ? "Available between responses and calls" : "Choose a retrieval provider"}
      >
        <option value="decisions">OpenAI Decisions</option>
        <option value="jev">Jev</option>
      </select>
    </label>
  );
}
