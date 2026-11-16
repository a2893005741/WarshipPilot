import { useEffect, useState } from "react";
import type { Field, Value } from "../api/types";
function localDate(value: Value) {
  if (!value) return "";
  const d = new Date(String(value));
  if (Number.isNaN(d.getTime())) return String(value);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
}
export function FieldInput({
  id,
  field,
  value,
  onChange,
  invalid,
}: {
  id: string;
  field: Field;
  value: Value;
  onChange: (value: Value) => void;
  invalid?: boolean;
}) {
  const display =
    field.type === "datetime-local" ? localDate(value) : String(value ?? "");
  const [text, setText] = useState(display);
  useEffect(() => setText(display), [display]);
  const disabled = field.display === "readonly";
  const shared = {
    id,
    disabled,
    "aria-label": field.name,
    "aria-invalid": invalid || undefined,
  };
  if (field.type === "checkbox")
    return (
      <button
        {...shared}
        type="button"
        role="switch"
        aria-checked={!!value}
        className={`toggle ${value ? "on" : ""}`}
        onClick={() => onChange(!value)}
      >
        <span />
      </button>
    );
  if (field.type === "select")
    return (
      <select
        {...shared}
        value={String(value)}
        onChange={(e) =>
          onChange(
            field.option!.find((o) => String(o.value) === e.target.value)!
              .value,
          )
        }
      >
        {field.option?.map((option) => (
          <option key={String(option.value)} value={String(option.value)}>
            {option.label}
          </option>
        ))}
      </select>
    );
  const submit = () => {
    const next = field.type === "number" ? Number(text) : text;
    if (next !== value) onChange(next);
  };
  return (
    <input
      {...shared}
      type={
        ["number", "time", "datetime-local"].includes(field.type)
          ? field.type
          : "text"
      }
      min={field.min}
      max={field.max}
      value={text}
      onChange={(e) => setText(e.target.value)}
      onBlur={submit}
      onKeyDown={(e) => {
        if (e.key === "Enter") e.currentTarget.blur();
      }}
    />
  );
}
