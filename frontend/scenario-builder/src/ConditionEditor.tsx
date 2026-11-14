import { useEffect, useMemo, useState } from "react";
import {
  childConditionKeys,
  conditionId,
  conditionType,
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
  type EditorSchema,
  type FieldSchema,
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

function MissingOptionalFields({
  fields,
  value,
  valuePath,
  sendCommand,
}: {
  fields: FieldSchema[];
  value: Record<string, JsonValue>;
  valuePath: Path;
  sendCommand: (command: Record<string, unknown>) => void;
}) {
  const [selected, setSelected] = useState("");
  const present = new Set(Object.keys(value));
  const missing = fields.filter((field) => !field.required && !present.has(field.name));
  if (missing.length === 0) {
    return null;
  }
  const current = missing.some((field) => field.name === selected)
    ? selected
    : missing[0].name;
  return (
    <div className="inline-form">
      <select value={current} onChange={(event) => setSelected(event.target.value)}>
        {missing.map((field) => (
          <option key={field.name} value={field.name}>
            {field.name}
          </option>
        ))}
      </select>
      <button
        onClick={() => {
          const field = missing.find((item) => item.name === current);
          if (!field) {
            return;
          }
          sendCommand({
            type: "set_setting",
            path: valuePath,
            key: field.name,
            value: structuredClone(field.default),
          });
        }}
      >
        任意項目を追加
      </button>
    </div>
  );
}

function RoiFieldsEditor({
  value,
  valuePath,
  sendCommand,
  onRemove,
}: {
  value: JsonValue | undefined;
  valuePath: Path;
  sendCommand: (command: Record<string, unknown>) => void;
  onRemove?: () => void;
}) {
  if (!isMapping(value)) {
    return <p className="error-text">roi は mapping である必要があります。</p>;
  }
  return (
    <div className="nested-group">
      <div className="nested-title">
        roi
        {onRemove ? (
          <button className="icon" title="roi を削除" onClick={onRemove}>
            ×
          </button>
        ) : null}
      </div>
      {(["x", "y", "width", "height"] as const).map((key) => (
        <SettingRow
          key={key}
          label={key}
          value={value[key]}
          onCommit={(next) =>
            sendCommand({ type: "set_setting", path: valuePath, key, value: next })
          }
        />
      ))}
    </div>
  );
}

function DetectorFieldsEditor({
  schema,
  value,
  valuePath,
  sendCommand,
  onRemove,
}: {
  schema: EditorSchema;
  value: JsonValue | undefined;
  valuePath: Path;
  sendCommand: (command: Record<string, unknown>) => void;
  onRemove?: () => void;
}) {
  if (!isMapping(value)) {
    return <p className="error-text">detector は mapping である必要があります。</p>;
  }
  const type = scalar(value.type) ?? "";
  const fields = schema.detectorFields[type];
  if (!fields) {
    return <p className="error-text">未対応の Detector 型です: {type}</p>;
  }
  return (
    <div className="nested-group">
      <div className="nested-title">
        detector
        {onRemove ? (
          <button className="icon" title="detector を削除" onClick={onRemove}>
            ×
          </button>
        ) : null}
      </div>
      <div className="setting-row">
        <span className="setting-label">type</span>
        <select
          value={type}
          onChange={(event) =>
            sendCommand({
              type: "set_detector_type",
              path: valuePath,
              value: event.target.value,
            })
          }
        >
          {Object.keys(schema.detectorFields).map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </div>
      {fields.map((field) => {
        const item = value[field.name];
        if (item === undefined) {
          return null;
        }
        return (
          <SchemaFieldEditor
            key={field.name}
            schema={schema}
            field={field}
            value={item}
            valuePath={valuePath}
            sendCommand={sendCommand}
          />
        );
      })}
      <MissingOptionalFields
        fields={fields}
        value={value}
        valuePath={valuePath}
        sendCommand={sendCommand}
      />
    </div>
  );
}

function SchemaFieldEditor({
  schema,
  field,
  value,
  valuePath,
  sendCommand,
}: {
  schema: EditorSchema;
  field: FieldSchema;
  value: JsonValue;
  valuePath: Path;
  sendCommand: (command: Record<string, unknown>) => void;
}) {
  const remove = field.required
    ? undefined
    : () =>
        sendCommand({
          type: "remove_setting",
          path: valuePath,
          key: field.name,
        });
  if (isAlias(value)) {
    return (
      <div className="setting-row">
        <span className="setting-label">{field.name}</span>
        <code>*{value.$alias}</code>
      </div>
    );
  }
  switch (field.kind) {
  case "detector":
    return (
      <DetectorFieldsEditor
        schema={schema}
        value={value}
        valuePath={[...valuePath, field.name]}
        sendCommand={sendCommand}
        onRemove={remove}
      />
    );
  case "roi":
    return (
      <RoiFieldsEditor
        value={value}
        valuePath={[...valuePath, field.name]}
        sendCommand={sendCommand}
        onRemove={remove}
      />
    );
  case "condition":
    return (
      <div className="setting-row">
        <span className="setting-label">{field.name}</span>
        <span className="muted">中央ペインで編集</span>
      </div>
    );
  case "condition_list": {
    const count = isSequence(value) ? value.length : 0;
    return (
      <div className="setting-row">
        <span className="setting-label">{field.name}</span>
        <span className="muted">{count} 件（中央ペインで編集）</span>
      </div>
    );
  }
  case "number_list":
    return (
      <SettingRow
        label={field.name}
        value={value}
        onCommit={(next) => {
          if (isSequence(next)) {
            sendCommand({
              type: "set_setting",
              path: valuePath,
              key: field.name,
              value: next,
            });
          }
        }}
        onRemove={remove}
      />
    );
  default:
    return (
      <SettingRow
        label={field.name}
        value={value}
        onCommit={(next) =>
          sendCommand({
            type: "set_setting",
            path: valuePath,
            key: field.name,
            value: next,
          })
        }
        onRemove={remove}
      />
    );
  }
}

function SettingsEditor({
  document,
  schema,
  value,
  valuePath,
  sendCommand,
}: {
  document: ScenarioDocument;
  schema: EditorSchema;
  value: JsonValue | undefined;
  valuePath: Path;
  sendCommand: (command: Record<string, unknown>) => void;
}) {
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
        schema={schema}
        value={value}
        valuePath={valuePath}
        sendCommand={sendCommand}
      />
    );
  }

  const type = conditionType(value);
  if (!schema.conditionFields[type]) {
    if (schema.detectorFields[type]) {
      return (
        <div className="settings-editor">
          <DetectorFieldsEditor
            schema={schema}
            value={value}
            valuePath={valuePath}
            sendCommand={sendCommand}
          />
        </div>
      );
    }
    return <p className="error-text">未対応の Condition 型です: {type}</p>;
  }

  const fields = schema.conditionFields[type];
  const missingRequired = fields.filter(
    (field) => field.required && value[field.name] === undefined,
  );

  return (
    <div className="settings-editor">
      <div className="setting-row">
        <span className="setting-label">type</span>
        <select
          value={type}
          onChange={(event) =>
            sendCommand({
              type: "set_condition_type",
              path: valuePath,
              value: event.target.value,
            })
          }
        >
          {Object.keys(schema.conditionFields).map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </div>
      <SettingRow
        label="id"
        value={value.id}
        onCommit={(next) =>
          sendCommand({ type: "set_setting", path: valuePath, key: "id", value: next })
        }
        onRemove={() =>
          sendCommand({ type: "remove_setting", path: valuePath, key: "id" })
        }
      />
      {missingRequired.map((field) => (
        <div key={field.name} className="setting-row">
          <span className="setting-label">{field.name}</span>
          <span className="error-text">必須項目がありません</span>
          <button
            className="icon"
            title="既定値を追加"
            onClick={() =>
              sendCommand({
                type: "set_setting",
                path: valuePath,
                key: field.name,
                value: structuredClone(field.default),
              })
            }
          >
            +
          </button>
        </div>
      ))}
      {fields.map((field) => {
        const item = value[field.name];
        if (item === undefined) {
          return null;
        }
        return (
          <SchemaFieldEditor
            key={field.name}
            schema={schema}
            field={field}
            value={item}
            valuePath={valuePath}
            sendCommand={sendCommand}
          />
        );
      })}
      <MissingOptionalFields
        fields={fields}
        value={value}
        valuePath={valuePath}
        sendCommand={sendCommand}
      />
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

function collectConditionIdNodes(
  value: JsonValue,
  result: { id: string; value: JsonValue }[] = [],
): { id: string; value: JsonValue }[] {
  if (!isMapping(value)) {
    return result;
  }
  const id = conditionId(value);
  if (id) {
    result.push({ id, value });
  }
  const type = conditionType(value);
  for (const key of childConditionKeys(type)) {
    const child = value[key];
    if (key === "conditions" && isSequence(child)) {
      child.forEach((item) => collectConditionIdNodes(item, result));
    } else if (child !== undefined) {
      collectConditionIdNodes(child, result);
    }
  }
  return result;
}

function overrideFieldPaths(value: JsonValue, schema: EditorSchema): string[][] {
  if (!isMapping(value)) {
    return [];
  }
  const fields = schema.conditionFields[conditionType(value)] ?? [];
  const paths: string[][] = [];
  for (const field of fields) {
    if (field.kind === "condition" || field.kind === "condition_list") {
      continue;
    }
    const item = value[field.name];
    if (field.kind === "detector" && isMapping(item)) {
      const detectorFields = schema.detectorFields[scalar(item.type) ?? ""] ?? [];
      for (const detectorField of detectorFields) {
        if (detectorField.kind === "roi" && isMapping(item[detectorField.name])) {
          for (const key of ["x", "y", "width", "height"]) {
            paths.push([field.name, detectorField.name, key]);
          }
        } else {
          paths.push([field.name, detectorField.name]);
        }
      }
      continue;
    }
    if (field.kind === "roi" && isMapping(item)) {
      for (const key of ["x", "y", "width", "height"]) {
        paths.push([field.name, key]);
      }
      continue;
    }
    paths.push([field.name]);
  }
  return paths;
}

function overrideOptions(
  resolved: JsonValue,
  schema: EditorSchema,
): { id: string; paths: string[][] }[] {
  const seen = new Set<string>();
  const result: { id: string; paths: string[][] }[] = [];
  for (const node of collectConditionIdNodes(resolved)) {
    if (seen.has(node.id)) {
      continue;
    }
    seen.add(node.id);
    result.push({ id: node.id, paths: overrideFieldPaths(node.value, schema) });
  }
  return result;
}

function OverridesEditor({
  document,
  schema,
  value,
  valuePath,
  sendCommand,
}: {
  document: ScenarioDocument;
  schema: EditorSchema;
  value: Record<string, JsonValue>;
  valuePath: Path;
  sendCommand: (command: Record<string, unknown>) => void;
}) {
  const anchor = usageAnchor(value) ?? "";
  const definition = definitionByName(document, anchor);
  const options = useMemo(
    () => (definition ? overrideOptions(definition.resolved, schema) : []),
    [definition, schema],
  );
  const ids = options.map((option) => option.id);
  const overrides = isMapping(value.overrides) ? value.overrides : {};
  const [targetId, setTargetId] = useState(ids[0] ?? "");
  const [fieldPath, setFieldPath] = useState("");
  const [fieldValue, setFieldValue] = useState("");
  const availablePaths = options.find((option) => option.id === targetId)?.paths ?? [];
  const activeFieldPath = availablePaths.some(
    (path) => path.join(".") === fieldPath,
  )
    ? fieldPath
    : (availablePaths[0]?.join(".") ?? "");

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
          <select
            value={activeFieldPath}
            onChange={(event) => setFieldPath(event.target.value)}
          >
            {availablePaths.length === 0 ? <option value="">項目なし</option> : null}
            {availablePaths.map((path) => {
              const value = path.join(".");
              return (
                <option key={value} value={value}>
                  {value}
                </option>
              );
            })}
          </select>
          <input
            value={fieldValue}
            placeholder="value"
            onChange={(event) => setFieldValue(event.target.value)}
          />
          <button
            disabled={!targetId || !activeFieldPath}
            onClick={() => {
              sendCommand({
                type: "set_override",
                path: valuePath,
                condition_id: targetId,
                setting_path: activeFieldPath.split("."),
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
  schema,
  usagePath,
  selectedPath,
  sendCommand,
}: {
  document: ScenarioDocument;
  schema: EditorSchema;
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
  const rootType = isMapping(rawRoot) ? conditionType(rawRoot) : "";
  const rootDetector =
    !rootInherits &&
    !rootReference &&
    !schema.conditionFields[rootType] &&
    Boolean(schema.detectorFields[rootType]);
  const fixedRoot = rootInherits || rootReference || rootDetector;
  const relative = selectedPath.slice(usagePath.length);
  const effectiveRoot = resolvedRootAtPath(document, usagePath) ?? rawRoot;
  const rawSelected = valueAtPath(rawRoot, relative);
  const effectiveSelected = valueAtPath(effectiveRoot, relative);
  const modeValue = fixedRoot
    ? relative.length === 0
      ? rawRoot
      : effectiveSelected
    : rawSelected;
  const showModeToolbar = !rootDetector && (!fixedRoot || relative.length === 0);

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
            schema={schema}
            value={rawRoot}
            valuePath={usagePath}
            sendCommand={sendCommand}
          />
        </>
      ) : rootReference ? (
        relative.length === 0 ? (
          <SettingsEditor
            document={document}
            schema={schema}
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
          schema={schema}
          value={rawSelected}
          valuePath={selectedPath}
          sendCommand={sendCommand}
        />
      )}
    </div>
  );
}
