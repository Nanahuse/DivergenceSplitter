import { useEffect, useState } from "react";
import {
  sharedUseName,
  type JsonValue,
  type Path,
  type ScenarioDocument,
} from "./model";
import { conditionUsageName } from "./conditionExposure";

export function ConditionUsageToolbar({
  document,
  selectedPath,
  selectedValue,
  editable,
  excludeName,
  onSelect,
  sendCommand,
}: {
  document: ScenarioDocument;
  selectedPath: Path;
  selectedValue: JsonValue | undefined;
  editable: boolean;
  excludeName?: string;
  onSelect: (path: Path) => void;
  sendCommand: (command: Record<string, unknown>) => void;
}) {
  const available = document.definitions.conditions.filter(
    (definition) => definition.name !== excludeName,
  );
  const currentName = conditionUsageName(selectedValue);
  const hasCurrent = available.some(
    (definition) => definition.name === currentName,
  );
  const [selected, setSelected] = useState(
    currentName || (available[0]?.name ?? ""),
  );
  useEffect(() => {
    if (currentName && hasCurrent) {
      setSelected(currentName);
    }
  }, [currentName, hasCurrent]);
  const active = available.some((definition) => definition.name === selected)
    ? selected
    : (available[0]?.name ?? "");
  const shared = currentName !== "";
  return (
    <div className="mode-toolbar">
      <div className="mode-current">
        現在: <strong>{shared ? `共通Condition ${sharedUseName(selectedValue)}` : "インライン"}</strong>
      </div>
      {editable ? (
        <>
          <select value={active} onChange={(event) => setSelected(event.target.value)}>
            {available.map((definition) => (
              <option key={definition.name} value={definition.name}>
                {definition.name}
              </option>
            ))}
          </select>
          <button
            disabled={!active}
            onClick={() => {
              sendCommand({ type: "use_condition", path: selectedPath, name: active });
              onSelect(selectedPath);
            }}
          >
            共通Conditionを使用
          </button>
          {shared ? (
            <button
              onClick={() => {
                sendCommand({ type: "inline_condition", path: selectedPath });
                onSelect(selectedPath);
              }}
            >
              独立したConditionにする
            </button>
          ) : null}
        </>
      ) : (
        <span className="muted">共通Conditionの構造は共通定義側で編集してください。</span>
      )}
    </div>
  );
}
