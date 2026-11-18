import { useEffect, useState } from "react";
import {
  isMapping,
  isParameterReference,
  isSequence,
  isSharedUse,
  sharedUseName,
  type JsonValue,
} from "./model";

function parseInputValue(text: string): JsonValue {
  const trimmed = text.trim();
  if (trimmed === "null") {
    return null;
  }
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    try {
      return JSON.parse(trimmed) as JsonValue;
    } catch {
      return text;
    }
  }
  return text;
}

export function compactValue(value: JsonValue | undefined): string {
  if (value === undefined) {
    return "—";
  }
  if (isParameterReference(value)) {
    return `param: ${value.$param}`;
  }
  if (isSharedUse(value)) {
    return `use: ${sharedUseName(value)}`;
  }
  if (isMapping(value) || isSequence(value)) {
    return JSON.stringify(value);
  }
  return String(value);
}

function DraftInput({
  value,
  onCommit,
  placeholder,
  multiline = false,
  disabled = false,
}: {
  value: string;
  onCommit: (value: string) => void;
  placeholder?: string;
  multiline?: boolean;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = () => {
    if (draft !== value) {
      onCommit(draft);
    }
  };
  if (multiline) {
    return (
      <textarea
        value={draft}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
      />
    );
  }
  return (
    <input
      value={draft}
      placeholder={placeholder}
      disabled={disabled}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          event.currentTarget.blur();
        }
      }}
    />
  );
}

export function SettingRow({
  label,
  value,
  onCommit,
  onRemove,
  onReset,
  overridden = false,
  readOnly = false,
  expose,
}: {
  label: string;
  value: JsonValue | undefined;
  onCommit: (value: JsonValue) => void;
  onRemove?: () => void;
  onReset?: () => void;
  overridden?: boolean;
  readOnly?: boolean;
  expose?: {
    exposed: boolean;
    disabled: boolean;
    onChange: (exposed: boolean) => void;
  };
}) {
  return (
    <div className="setting-row">
      <span className="setting-label">
        {label}
        {overridden ? <span className="override-badge">この使用箇所</span> : null}
        {expose ? (
          <label className="expose-toggle" title="使用箇所から変更できるようにする">
            <input
              type="checkbox"
              checked={expose.exposed}
              disabled={expose.disabled}
              onChange={(event) => expose.onChange(event.target.checked)}
            />
            公開
          </label>
        ) : null}
      </span>
      <DraftInput
        value={value === undefined || value === null ? "" : compactValue(value)}
        disabled={readOnly}
        onCommit={(text) => onCommit(parseInputValue(text))}
      />
      {onReset ? (
        <button className="icon" title="共通定義の値に戻す" onClick={onReset}>
          ↺
        </button>
      ) : null}
      {onRemove ? (
        <button className="icon" title="設定を削除" onClick={onRemove}>
          ×
        </button>
      ) : null}
    </div>
  );
}
