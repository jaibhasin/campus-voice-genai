"use client";

export default function ProviderSelect({ value, onChange, disabled }) {
  return (
    <label className="provider-select">
      <select
        aria-label="Retrieval provider"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        title={disabled ? "Available between responses and calls" : "Choose a retrieval provider"}
      >
        <option value="decisions">Decisions</option>
        <option value="jev">Jev</option>
      </select>
    </label>
  );
}
