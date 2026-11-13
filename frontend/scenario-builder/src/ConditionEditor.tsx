import { useEffect, useMemo, useState } from "react";
import {
  childConditionKeys,
  conditionIds,
  conditionType,
  conditionTypes,
  definitionByName,
  formatPath,
  isAlias,
  isInheritanceUsage,
  isMapping,
  isSequence,
  pathEquals,
  resolvedRootAtPath,
  scalar,
  usageAnchor,
  valueAtPath,
  type JsonValue,
  type Path,
  type ScenarioDocument,
} from "./model";

const defaultCondition: JsonValue = { type: "elapsed", duration: "1s" };

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

function compactValue(value: JsonValue | undefined): string {
  if (value === undefined) {
    return "—";
  }
  if (isAlias(value)) {
    return `*${value.$alias}`;
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
}: {
  value: string;
  onCommit: (value: string) => void;
  placeholder?: string;
  multiline?: boolean;
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
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
      />
    );
  }
  return (
    <input
      value={draft}
      placeholder={placeholder}
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

function SettingRow({
  label,
  value,
  onCommit,
  onRemove,
}: {
  label: string;
  value: JsonValue | undefined;
  onCommit: (value: JsonValue) => void;
  onRemove?: () => void;
}) {
  return (
    <div className="setting-row">
      <span className="setting-label">{label}</span>
      <DraftInput
        value={value === undefined || value === null ? "" : compactValue(value)}
        onCommit={(text) => onCommit(parseInputValue(text))}
      />
      {onRemove ? (
        <button className="icon" title="設定を削除" onClick={onRemove}>
          ×
        </button>
      ) : null}
    </div>
  );
}

function NestedMappingEditor({
  value,
  valuePath,
  sendCommand,
  depth,
}: {
  value: Record<string, JsonValue>;
  valuePath: Path;
  sendCommand: (command: Record<string, unknown>) => void;
  depth: number;
}) {
  const [newKey, setNewKey] = useState("");
  const [newValue, setNewValue] = useState("");
  return (
    <div className={`nested-editor depth-${depth}`}>
      {Object.entries(value).map(([key, item]) => {
        if (isMapping(item)) {
          return (
            <div key={key} className="nested-group">
              <div className="nested-title">
                {key}
                <button
                  className="icon"
                  title="この設定を削除"
                  onClick={() =>
                    sendCommand({ type: "remove_setting", path: valuePath, key })
                  }
                >
                  ×
                </button>
              </div>
              <NestedMappingEditor
                value={item}
                valuePath={[...valuePath, key]}
                sendCommand={sendCommand}
                depth={depth + 1}
              />
            </div>
          );
        }
        if (isSequence(item)) {
          return (
            <div key={key} className="setting-row">
              <span className="setting-label">{key}</span>
              <DraftInput
                multiline
                value={JSON.stringify(item)}
                onCommit={(text) => {
                  const parsed = parseInputValue(text);
                  if (isSequence(parsed)) {
                    sendCommand({ type: "set_setting", path: valuePath, key, value: parsed });
                  }
                }}
              />
              <button
                className="icon"
                title="この設定を削除"
                onClick={() => sendCommand({ type: "remove_setting", path: valuePath, key })}
              >
                ×
              </button>
            </div>
          );
        }
        return (
          <SettingRow
            key={key}
            label={key}
            value={item}
            onCommit={(next) =>
              sendCommand({ type: "set_setting", path: valuePath, key, value: next })
            }
            onRemove={() => sendCommand({ type: "remove_setting", path: valuePath, key })}
          />
        );
      })}
      <div className="inline-form">
        <input
          value={newKey}
          placeholder="field"
          onChange={(event) => setNewKey(event.target.value)}
        />
        <input
          value={newValue}
          placeholder="value"
          onChange={(event) => setNewValue(event.target.value)}
        />
        <button
          onClick={() => {
            if (!newKey.trim()) {
              return;
            }
            sendCommand({
              type: "set_setting",
              path: valuePath,
              key: newKey.trim(),
              value: parseInputValue(newValue),
            });
            setNewKey("");
            setNewValue("");
          }}
        >
          追加
        </button>
      </div>
    </div>
  );
}

function SettingsEditor({
  document,
  value,
  valuePath,
  sendCommand,
}: {
  document: ScenarioDocument;
  value: JsonValue | undefined;
  valuePath: Path;
  sendCommand: (command: Record<string, unknown>) => void;
}) {
  const [newKey, setNewKey] = useState("");
  const [newValue, setNewValue] = useState("");

  if (isAlias(value)) {
    return (
      <div className="settings-editor">
        <div className="usage-banner">
          <strong>reference: *{value.$alias}</strong>
          <span>共通定義の内容は中央ペインに表示されます。</span>
        </div>
      </div>
    );
  }
  if (!isMapping(value)) {
    return <p className="muted">設定できる Condition mapping がありません。</p>;
  }
  if (isInheritanceUsage(value)) {
    return (
      <OverridesEditor
        document={document}
        value={value}
        valuePath={valuePath}
        sendCommand={sendCommand}
      />
    );
  }

  const type = conditionType(value);
  const childKeys = childConditionKeys(type);
  const settings = Object.entries(value).filter(([key]) => !childKeys.includes(key));

  return (
    <div className="settings-editor">
      <div className="setting-row">
        <span className="setting-label">type</span>
        <select
          value={type}
          onChange={(event) =>
            sendCommand({
              type: "set_setting",
              path: valuePath,
              key: "type",
              value: event.target.value,
            })
          }
        >
          {conditionTypes.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </div>
      {settings
        .filter(([key]) => key !== "type")
        .map(([key, item]) => {
          if (isMapping(item)) {
            return (
              <div key={key} className="nested-group">
                <div className="nested-title">
                  {key}
                  <button
                    className="icon"
                    title="この設定を削除"
                    onClick={() =>
                      sendCommand({ type: "remove_setting", path: valuePath, key })
                    }
                  >
                    ×
                  </button>
                </div>
                <NestedMappingEditor
                  value={item}
                  valuePath={[...valuePath, key]}
                  sendCommand={sendCommand}
                  depth={1}
                />
              </div>
            );
          }
          if (isSequence(item)) {
            return (
              <div key={key} className="setting-row">
                <span className="setting-label">{key}</span>
                <DraftInput
                  multiline
                  value={JSON.stringify(item)}
                  onCommit={(text) => {
                    const parsed = parseInputValue(text);
                    if (isSequence(parsed)) {
                      sendCommand({ type: "set_setting", path: valuePath, key, value: parsed });
                    }
                  }}
                />
                <button
                  className="icon"
                  title="この設定を削除"
                  onClick={() => sendCommand({ type: "remove_setting", path: valuePath, key })}
                >
                  ×
                </button>
              </div>
            );
          }
          return (
            <SettingRow
              key={key}
              label={key}
              value={item}
              onCommit={(next) =>
                sendCommand({ type: "set_setting", path: valuePath, key, value: next })
              }
              onRemove={() => sendCommand({ type: "remove_setting", path: valuePath, key })}
            />
          );
        })}
      <div className="inline-form">
        <input
          value={newKey}
          placeholder="setting"
          onChange={(event) => setNewKey(event.target.value)}
        />
        <input
          value={newValue}
          placeholder="value"
          onChange={(event) => setNewValue(event.target.value)}
        />
        <button
          onClick={() => {
            if (!newKey.trim()) {
              return;
            }
            sendCommand({
              type: "set_setting",
              path: valuePath,
              key: newKey.trim(),
              value: parseInputValue(newValue),
            });
            setNewKey("");
            setNewValue("");
          }}
        >
          設定を追加
        </button>
      </div>
      {childKeys.includes("condition")
      && !isMapping(value.condition)
      && !isAlias(value.condition) ? (
        <button
          onClick={() =>
            sendCommand({
              type: "set_setting",
              path: valuePath,
              key: "condition",
              value: defaultCondition,
            })
          }
        >
          子 Condition を追加
        </button>
      ) : null}
      {childKeys.includes("reset_condition") && !isMapping(value.reset_condition) ? (
        <button
          onClick={() =>
            sendCommand({
              type: "set_setting",
              path: valuePath,
              key: "reset_condition",
              value: defaultCondition,
            })
          }
        >
          Reset Condition を追加
        </button>
      ) : null}
    </div>
  );
}

function flattenLeaves(
  value: JsonValue,
  prefix: string[] = [],
  result: { path: string[]; value: JsonValue }[] = [],
): { path: string[]; value: JsonValue }[] {
  if (isMapping(value) && Object.keys(value).length > 0) {
    for (const [key, item] of Object.entries(value)) {
      flattenLeaves(item, [...prefix, key], result);
    }
    return result;
  }
  result.push({ path: prefix, value });
  return result;
}

function OverridesEditor({
  document,
  value,
  valuePath,
  sendCommand,
}: {
  document: ScenarioDocument;
  value: Record<string, JsonValue>;
  valuePath: Path;
  sendCommand: (command: Record<string, unknown>) => void;
}) {
  const anchor = usageAnchor(value) ?? "";
  const definition = definitionByName(document, anchor);
  const ids = useMemo(
    () => (definition ? conditionIds(definition.resolved) : []),
    [definition],
  );
  const overrides = isMapping(value.overrides) ? value.overrides : {};
  const [targetId, setTargetId] = useState(ids[0] ?? "");
  const [fieldPath, setFieldPath] = useState("");
  const [fieldValue, setFieldValue] = useState("");

  useEffect(() => {
    if (!ids.includes(targetId)) {
      setTargetId(ids[0] ?? "");
    }
  }, [ids, targetId]);

  if (!definition) {
    return <p className="error-text">継承元の共通定義が見つかりません: {anchor}</p>;
  }

  return (
    <div className="settings-editor">
      <div className="usage-banner">
        <strong>extends: *{anchor}</strong>
        <span>定義の変更は全使用箇所に反映されます。</span>
      </div>
      <div className="nested-group">
        <div className="nested-title">上書き済みの設定</div>
        {Object.keys(overrides).length === 0 ? (
          <p className="muted">上書きはありません。</p>
        ) : (
          Object.entries(overrides).map(([id, patch]) => (
            <div key={id} className="override-block">
              <div className="override-title">
                <code>{id}</code>
                <button
                  className="icon"
                  title="この Condition の上書きを解除"
                  onClick={() =>
                    sendCommand({
                      type: "remove_override",
                      path: valuePath,
                      condition_id: id,
                    })
                  }
                >
                  ×
                </button>
              </div>
              {isMapping(patch)
                ? flattenLeaves(patch).map((leaf, index) => (
                    <div key={`${id}-${index}`} className="setting-row">
                      <span className="setting-label">{leaf.path.join(".") || "(値)"}</span>
                      <span className="override-value">{compactValue(leaf.value)}</span>
                      <button
                        className="icon"
                        title="この上書きを解除"
                        onClick={() =>
                          sendCommand({
                            type: "remove_override",
                            path: valuePath,
                            condition_id: id,
                            setting_path: leaf.path,
                          })
                        }
                      >
                        ×
                      </button>
                    </div>
                  ))
                : null}
            </div>
          ))
        )}
      </div>
      <div className="override-form">
        <div className="nested-title">上書きを追加</div>
        <div className="inline-form">
          <select value={targetId} onChange={(event) => setTargetId(event.target.value)}>
            {ids.length === 0 ? <option value="">ID なし</option> : null}
            {ids.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
          <input
            value={fieldPath}
            placeholder="duration / detector.roi.x"
            onChange={(event) => setFieldPath(event.target.value)}
          />
          <input
            value={fieldValue}
            placeholder="value"
            onChange={(event) => setFieldValue(event.target.value)}
          />
          <button
            disabled={!targetId || !fieldPath.trim()}
            onClick={() => {
              const settingPath = fieldPath
                .split(".")
                .map((part) => part.trim())
                .filter(Boolean);
              sendCommand({
                type: "set_override",
                path: valuePath,
                condition_id: targetId,
                setting_path: settingPath,
                value: parseInputValue(fieldValue),
              });
            }}
          >
            追加
          </button>
        </div>
        <p className="muted">
          ID は継承元 Condition の <code>id</code> です。null を指定すると inherited
          値を解除できます。
        </p>
      </div>
      <div className="nested-group">
        <div className="nested-title">継承元の Condition</div>
        <pre>{JSON.stringify(definition.resolved, null, 2)}</pre>
      </div>
    </div>
  );
}

function ChildConditionList({
  document,
  parentValue,
  parentPath,
  selectedPath,
  onSelect,
  sendCommand,
  editable,
  overrideIds,
}: {
  document: ScenarioDocument;
  parentValue: Record<string, JsonValue>;
  parentPath: Path;
  selectedPath: Path;
  onSelect: (path: Path) => void;
  sendCommand: (command: Record<string, unknown>) => void;
  editable: boolean;
  overrideIds: Set<string>;
}) {
  const conditions = isSequence(parentValue.conditions) ? parentValue.conditions : [];
  const [dragIndex, setDragIndex] = useState<number | null>(null);

  return (
    <div className="child-list">
      {conditions.map((item, index) => (
        <div
          key={`${parentPath.join("/")}-${index}`}
          className="child-row"
          draggable={editable}
          onDragStart={() => setDragIndex(index)}
          onDragOver={(event) => {
            if (editable) {
              event.preventDefault();
            }
          }}
          onDrop={(event) => {
            event.preventDefault();
            if (editable && dragIndex !== null && dragIndex !== index) {
              sendCommand({
                type: "move_condition",
                path: parentPath,
                from: dragIndex,
                to: index,
              });
            }
            setDragIndex(null);
          }}
        >
          {editable ? <span className="drag-handle">⋮⋮</span> : null}
          <div className="child-content">
            <ConditionTree
              document={document}
              value={item}
              nodePath={[...parentPath, "conditions", index]}
              selectedPath={selectedPath}
              onSelect={onSelect}
              sendCommand={sendCommand}
              editable={editable}
              overrideIds={overrideIds}
              depth={0}
            />
          </div>
          {editable ? (
            <div className="child-actions">
              <button
                className="icon"
                title="上へ"
                disabled={index === 0}
                onClick={() =>
                  sendCommand({
                    type: "move_condition",
                    path: parentPath,
                    from: index,
                    to: index - 1,
                  })
                }
              >
                ↑
              </button>
              <button
                className="icon"
                title="下へ"
                disabled={index === conditions.length - 1}
                onClick={() =>
                  sendCommand({
                    type: "move_condition",
                    path: parentPath,
                    from: index,
                    to: index + 1,
                  })
                }
              >
                ↓
              </button>
              <button
                className="icon"
                title="削除"
                onClick={() =>
                  sendCommand({ type: "remove_condition", path: parentPath, index })
                }
              >
                ×
              </button>
            </div>
          ) : null}
        </div>
      ))}
      {editable ? (
        <button
          className="add-child"
          onClick={() =>
            sendCommand({
              type: "add_condition",
              path: parentPath,
              index: conditions.length,
              value: defaultCondition,
            })
          }
        >
          + 子 Condition を追加
        </button>
      ) : null}
    </div>
  );
}

function ConditionTree({
  document,
  value,
  nodePath,
  selectedPath,
  onSelect,
  sendCommand,
  editable,
  overrideIds,
  depth = 0,
}: {
  document: ScenarioDocument;
  value: JsonValue;
  nodePath: Path;
  selectedPath: Path;
  onSelect: (path: Path) => void;
  sendCommand: (command: Record<string, unknown>) => void;
  editable: boolean;
  overrideIds: Set<string>;
  depth?: number;
}) {
  const selected = pathEquals(nodePath, selectedPath);
  if (isAlias(value)) {
    return (
      <div
        className={`condition-card reference ${selected ? "selected" : ""}`}
        onClick={(event) => {
          event.stopPropagation();
          onSelect(nodePath);
        }}
      >
        <span className="condition-type">参照</span>
        <code>*{value.$alias}</code>
      </div>
    );
  }
  if (!isMapping(value)) {
    return <div className="condition-card scalar">{compactValue(value)}</div>;
  }
  const type = conditionType(value);
  const id = scalar(value.id);
  const anchor = usageAnchor(value);
  const childKeys = childConditionKeys(type);

  return (
    <div
      className={`condition-card ${selected ? "selected" : ""} depth-${Math.min(depth, 5)}`}
      onClick={(event) => {
        event.stopPropagation();
        onSelect(nodePath);
      }}
    >
      <div className="condition-header">
        <span className="condition-type">{type || "condition"}</span>
        {id ? <code className="condition-id">id: {id}</code> : null}
        {id && overrideIds.has(id) ? (
          <span className="override-badge">overridden</span>
        ) : null}
        {anchor ? (
          <code className="condition-anchor">
            {isInheritanceUsage(value) ? "extends: " : ""}*{anchor}
          </code>
        ) : null}
      </div>
      <div className="condition-summary">
        {value.minimum_score !== undefined ? (
          <span>score {compactValue(value.minimum_score)}</span>
        ) : null}
        {value.duration !== undefined ? <span>{compactValue(value.duration)}</span> : null}
        {value.within !== undefined ? <span>within {compactValue(value.within)}</span> : null}
        {value.count !== undefined ? <span>count {compactValue(value.count)}</span> : null}
        {isMapping(value.detector) ? (
          <span>
            detector {scalar(value.detector.type) ?? ""}
            {value.detector.reference !== undefined
              ? ` (${compactValue(value.detector.reference)})`
              : ""}
          </span>
        ) : null}
      </div>
      {childKeys.map((key) => {
        const child = value[key];
        if (key === "conditions") {
          if (!isSequence(child)) {
            return null;
          }
          return (
            <ChildConditionList
              key={key}
              document={document}
              parentValue={value}
              parentPath={nodePath}
              selectedPath={selectedPath}
              onSelect={onSelect}
              sendCommand={sendCommand}
              editable={editable && !anchor}
              overrideIds={overrideIds}
            />
          );
        }
        if (child === undefined) {
          return null;
        }
        return (
          <div key={key} className="slot">
            <div className="slot-title">{key}</div>
            <ConditionTree
              document={document}
              value={child}
              nodePath={[...nodePath, key]}
              selectedPath={selectedPath}
              onSelect={onSelect}
              sendCommand={sendCommand}
              editable={editable && !anchor}
              overrideIds={overrideIds}
              depth={depth + 1}
            />
          </div>
        );
      })}
    </div>
  );
}

function rootValueAtPath(
  document: ScenarioDocument,
  path: Path,
): JsonValue | undefined {
  if (path[0] === "definitions" && typeof path[1] === "string") {
    return definitionByName(document, path[1])?.value;
  }
  if (path[0] === "start_condition") {
    return document.start_condition ?? undefined;
  }
  if (path[0] === "reset_condition") {
    return document.reset_condition ?? undefined;
  }
  if (path[0] === "incomplete_condition") {
    return document.incomplete_condition ?? undefined;
  }
  if (path[0] === "splits" && typeof path[1] === "number" && typeof path[3] === "number") {
    return document.splits[path[1]]?.rules[path[3]]?.condition;
  }
  return undefined;
}

export function ConditionPane({
  document,
  usagePath,
  selectedPath,
  onSelect,
  sendCommand,
}: {
  document: ScenarioDocument;
  usagePath: Path;
  selectedPath: Path;
  onSelect: (path: Path) => void;
  sendCommand: (command: Record<string, unknown>) => void;
}) {
  const raw = rootValueAtPath(document, usagePath);
  if (raw === undefined || raw === null) {
    return <p className="muted">Condition が設定されていません。</p>;
  }
  const inheritance = isInheritanceUsage(raw);
  const reference = isAlias(raw);
  const display = inheritance || reference
    ? (resolvedRootAtPath(document, usagePath) ?? raw)
    : raw;
  const editable = !inheritance && !reference;
  const overrideIds = new Set<string>();
  if (inheritance && isMapping(raw) && isMapping(raw.overrides)) {
    for (const key of Object.keys(raw.overrides)) {
      overrideIds.add(key);
    }
  }

  return (
    <div className="condition-pane">
      <div className="condition-pane-header">
        <h2>{formatPath(document, usagePath)}</h2>
        <span
          className={`mode-badge ${
            inheritance ? "inherits" : reference ? "reference" : "inline"
          }`}
        >
          {inheritance
            ? `extends *${usageAnchor(raw)}`
            : reference
              ? `reference *${usageAnchor(raw)}`
              : "inline"}
        </span>
      </div>
      {inheritance || reference ? (
        <p className="muted">
          共通定義の内容を表示しています。プロパティペインで参照方法と上書きを編集できます。
        </p>
      ) : null}
      <ConditionTree
        document={document}
        value={display}
        nodePath={usagePath}
        selectedPath={selectedPath}
        onSelect={onSelect}
        sendCommand={sendCommand}
        editable={editable}
        overrideIds={overrideIds}
      />
    </div>
  );
}

export function UsageModeToolbar({
  document,
  selectedValue,
  selectedPath,
  sendCommand,
}: {
  document: ScenarioDocument;
  selectedValue: JsonValue | undefined;
  selectedPath: Path;
  sendCommand: (command: Record<string, unknown>) => void;
}) {
  const definitions = document.definitions.filter(
    (definition) => definition.kind === "condition",
  );
  const [anchor, setAnchor] = useState(definitions[0]?.name ?? "");
  const anchorValue = usageAnchor(selectedValue) ?? "";
  useEffect(() => {
    if (anchorValue) {
      setAnchor(anchorValue);
    } else if (!definitions.some((definition) => definition.name === anchor)) {
      setAnchor(definitions[0]?.name ?? "");
    }
  }, [anchorValue, anchor, definitions]);
  return (
    <div className="mode-toolbar">
      <div className="mode-current">
        現在:{" "}
        <strong>
          {isAlias(selectedValue)
            ? `参照 *${usageAnchor(selectedValue)}`
            : isInheritanceUsage(selectedValue)
              ? `継承 *${usageAnchor(selectedValue)}`
              : "インライン"}
        </strong>
      </div>
      <select value={anchor} onChange={(event) => setAnchor(event.target.value)}>
        {definitions.length === 0 ? <option value="">共通定義なし</option> : null}
        {definitions.map((definition) => (
          <option key={definition.name} value={definition.name}>
            {definition.name}
          </option>
        ))}
      </select>
      <button
        disabled={!anchor}
        onClick={() =>
          sendCommand({ type: "set_usage", path: selectedPath, mode: "reference", anchor })
        }
      >
        共通定義を参照
      </button>
      <button
        disabled={!anchor}
        onClick={() =>
          sendCommand({ type: "set_usage", path: selectedPath, mode: "inherits", anchor })
        }
      >
        継承して上書き
      </button>
      <button
        disabled={selectedValue === undefined}
        onClick={() => sendCommand({ type: "set_usage", path: selectedPath, mode: "inline" })}
      >
        インライン化
      </button>
    </div>
  );
}

export function ConditionInspector({
  document,
  usagePath,
  selectedPath,
  sendCommand,
}: {
  document: ScenarioDocument;
  usagePath: Path;
  selectedPath: Path;
  sendCommand: (command: Record<string, unknown>) => void;
}) {
  const rawRoot = rootValueAtPath(document, usagePath);
  if (rawRoot === undefined || rawRoot === null) {
    return <p className="muted">Condition を選択してください。</p>;
  }
  const rootInherits = isInheritanceUsage(rawRoot);
  const rootReference = isAlias(rawRoot);
  const fixedRoot = rootInherits || rootReference;
  const relative = selectedPath.slice(usagePath.length);
  const effectiveRoot = resolvedRootAtPath(document, usagePath) ?? rawRoot;
  const rawSelected = valueAtPath(rawRoot, relative);
  const effectiveSelected = valueAtPath(effectiveRoot, relative);
  const modeValue = fixedRoot
    ? relative.length === 0
      ? rawRoot
      : effectiveSelected
    : rawSelected;
  const showModeToolbar = !fixedRoot || relative.length === 0;

  return (
    <div className="inspector">
      <h2>Properties</h2>
      <p className="muted">{formatPath(document, selectedPath)}</p>
      {showModeToolbar ? (
        <UsageModeToolbar
          document={document}
          selectedValue={modeValue}
          selectedPath={selectedPath}
          sendCommand={sendCommand}
        />
      ) : null}
      {rootInherits ? (
        <>
          <p className="muted">
            extends 使用箇所の子 Condition は構造変更できません。上書きは Condition ID
            単位で追加してください。
          </p>
          <SettingsEditor
            document={document}
            value={rawRoot}
            valuePath={usagePath}
            sendCommand={sendCommand}
          />
        </>
      ) : rootReference ? (
        relative.length === 0 ? (
          <SettingsEditor
            document={document}
            value={rawSelected}
            valuePath={selectedPath}
            sendCommand={sendCommand}
          />
        ) : (
          <div className="nested-group">
            <div className="nested-title">参照先の Condition</div>
            <p className="muted">
              共通定義を参照している使用箇所では子 Condition を直接編集できません。
            </p>
            <pre>{JSON.stringify(effectiveSelected, null, 2)}</pre>
          </div>
        )
      ) : (
        <SettingsEditor
          document={document}
          value={rawSelected}
          valuePath={selectedPath}
          sendCommand={sendCommand}
        />
      )}
    </div>
  );
}
