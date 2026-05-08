"use client";

export default function OptionPills({ options, onSelect }) {
  if (!options || options.length === 0) return null;

  return (
    <div className="option-pills">
      {options.map((opt, i) => (
        <button
          key={i}
          className="option-pill"
          onClick={() => onSelect(opt)}
        >
          👉 {opt}
        </button>
      ))}
    </div>
  );
}
