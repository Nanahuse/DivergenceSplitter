import { useEffect, useState } from "react";
import {
  childConditionKeys,
  conditionDefinitionByName,
  conditionType,
  detectorDefinitionByName,
  formatPath,
  isMapping,
  isParameterReference,
  isSequence,
  isSharedUse,
  pathEquals,
  pathKey,
  resolvedRootAtPath,
  scalar,
  sharedUseName,
  sharedUseWith,
  valueAtPath,
  definitionExposureInfo,
  isNestedExposurePath,
  type DefinitionExposureInfo,
  type EditorSchema,
  type FieldSchema,
  type JsonValue,
  type Path,
  type ScenarioDocument,
  type SharedDetectorDefinition,
  type WorkspaceInfo,
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

function SettingRow({
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

interface PropertyActions {
  schema: EditorSchema;
  detectorDefinitions: SharedDetectorDefinition[];
  assets: string[];
  addAsset?: (apply: (asset: string) => void) => void;
  overrides: Set<string>;
  exposure: DefinitionExposureInfo | null;
  document: ScenarioDocument;
  usageMode: boolean;
  definitionMode: boolean;
  rawValue: (path: Path) => JsonValue | undefined;
  set: (path: Path, value: JsonValue) => void;
  remove?: (path: Path) => void;
  reset?: (path: Path) => void;
  readOnly: (path: Path) => boolean;
  isExposed: (path: Path) => boolean;
  canExpose: (path: Path) => boolean;
  toggleExposure?: (path: Path, exposed: boolean) => void;
  structureEditable: (path: Path) => boolean;
  changeConditionType?: (type: string) => void;
  changeDetectorType?: (path: Path, type: string) => void;
  useDetector?: (path: Path, name: string) => void;
  inlineDetector?: (path: Path) => void;
  setDetectorUsage?: (path: Path, settingPath: Path, value: JsonValue) => void;
  resetDetectorUsage?: (path: Path, settingPath: Path) => void;
}

function exposureControl(actions: PropertyActions, path: Path) {
  if (!actions.toggleExposure) {
    return undefined;
  }
  const exposed = actions.isExposed(path);
  return {
    exposed,
    disabled: !exposed && !actions.canExpose(path),
    onChange: (next: boolean) => actions.toggleExposure?.(path, next),
  };
}

function MissingOptionalFields({
  actions,
  path,
  value,
  fields,
}: {
  actions: PropertyActions;
  path: Path;
  value: Record<string, JsonValue>;
  fields: FieldSchema[];
}) {
  const [selected, setSelected] = useState("");
  const present = new Set(Object.keys(value));
  const missing = fields.filter((field) => !field.required && !present.has(field.name));
  if (missing.length === 0) {
    return null;
  }
  if (actions.usageMode) {
    const exposedMissing = missing.filter((field) =>
      actions.isExposed([...path, field.name]),
    );
    if (exposedMissing.length === 0) {
      return null;
    }
    return (
      <div className="nested-group">
        <div className="nested-title">公開パラメーター</div>
        {exposedMissing.map((field) => (
          <SettingRow
            key={field.name}
            label={field.name}
            value={undefined}
            onCommit={(next) => actions.set([...path, field.name], next)}
          />
        ))}
      </div>
    );
  }
  if (isNestedExposurePath(actions.exposure, path)) {
    const exposableMissing = missing.filter((field) =>
      actions.canExpose([...path, field.name]),
    );
    if (exposableMissing.length === 0) {
      return null;
    }
    return (
      <div className="nested-group">
        <div className="nested-title">公開できるパラメーター</div>
        {exposableMissing.map((field) => (
          <SettingRow
            key={field.name}
            label={field.name}
            value={undefined}
            readOnly={actions.readOnly([...path, field.name])}
            expose={exposureControl(actions, [...path, field.name])}
            onCommit={(next) => actions.set([...path, field.name], next)}
          />
        ))}
      </div>
    );
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
          if (field) {
            actions.set([...path, field.name], structuredClone(field.default));
          }
        }}
      >
        任意項目を追加
      </button>
    </div>
  );
}

function RoiFieldsEditor({
  actions,
  path,
  value,
  field,
}: {
  actions: PropertyActions;
  path: Path;
  value: JsonValue | undefined;
  field: FieldSchema;
}) {
  if (!isMapping(value)) {
    return <p className="error-text">roi は mapping である必要があります。</p>;
  }
  return (
    <div className="nested-group">
      <div className="nested-title">
        roi
        {!field.required && actions.remove && !actions.readOnly(path) ? (
          <button className="icon" title="roi を削除" onClick={() => actions.remove?.(path)}>
            ×
          </button>
        ) : null}
      </div>
      {(["x", "y", "width", "height"] as const).map((key) => (
        <SettingRow
          key={key}
          label={key}
          value={value[key]}
          overridden={actions.overrides.has(pathKey([...path, key]))}
          readOnly={actions.readOnly([...path, key])}
          expose={exposureControl(actions, [...path, key])}
          onReset={
            actions.reset && actions.overrides.has(pathKey([...path, key]))
              ? () => actions.reset?.([...path, key])
              : undefined
          }
          onCommit={(next) => actions.set([...path, key], next)}
        />
      ))}
    </div>
  );
}

function DetectorFieldsEditor({
  actions,
  path,
  value,
  raw,
  optional = false,
}: {
  actions: PropertyActions;
  path: Path;
  value: JsonValue | undefined;
  raw: JsonValue | undefined;
  optional?: boolean;
}) {
  const [selectedDefinition, setSelectedDefinition] = useState(
    actions.detectorDefinitions[0]?.name ?? "",
  );
  if (isSharedUse(raw)) {
    const name = sharedUseName(raw);
    const definition = actions.detectorDefinitions.find((item) => item.name === name);
    if (!definition) {
      return <p className="error-text">共通Detectorが見つかりません: {name}</p>;
    }
    if (!isMapping(value)) {
      return <p className="error-text">Detector の解決結果がありません。</p>;
    }
    const fields = actions.schema.detectorFields[conditionType(value)] ?? [];
    const nestedExposure = definitionExposureInfo(actions.document, "detector", name);
    const useParentActions = actions.usageMode || actions.definitionMode;
    if (useParentActions) {
      return (
        <div className="nested-group">
          <div className="nested-title">
            共通Detector: {name}
            {actions.inlineDetector && actions.structureEditable(path) ? (
              <button
                className="icon"
                title="インライン化"
                onClick={() => actions.inlineDetector?.(path)}
              >
                ↧
              </button>
            ) : null}
          </div>
          {fields.map((field) => {
            const item = value[field.name];
            if (item === undefined) {
              return null;
            }
            return (
              <SchemaFieldEditor
                key={field.name}
                actions={actions}
                field={field}
                path={[...path, field.name]}
                value={item}
                raw={actions.rawValue([...path, field.name])}
              />
            );
          })}
          <MissingOptionalFields
            actions={actions}
            path={path}
            value={value}
            fields={fields}
          />
        </div>
      );
    }
    const overrides = new Set<string>();
    for (const [exposedPath, parameter] of nestedExposure.exposed) {
      if (sharedUseWith(raw)[parameter] !== undefined) {
        overrides.add(exposedPath);
      }
    }
    const nested: PropertyActions = {
      schema: actions.schema,
      detectorDefinitions: actions.detectorDefinitions,
      assets: actions.assets,
      addAsset: actions.addAsset,
      overrides,
      exposure: nestedExposure,
      usageMode: true,
      definitionMode: false,
      document: actions.document,
      rawValue: (itemPath) => valueAtPath(value, itemPath),
      set: (itemPath, next) => actions.setDetectorUsage?.(path, itemPath, next),
      reset: actions.resetDetectorUsage
        ? (itemPath) => actions.resetDetectorUsage?.(path, itemPath)
        : undefined,
      readOnly: (itemPath) => !nestedExposure.exposed.has(pathKey(itemPath)),
      isExposed: (itemPath) => nestedExposure.exposed.has(pathKey(itemPath)),
      canExpose: () => false,
      structureEditable: () => false,
      inlineDetector: actions.inlineDetector
        ? () => actions.inlineDetector?.(path)
        : undefined,
    };
    if (!actions.setDetectorUsage) {
      return (
        <div className="usage-banner">
          <strong>共通Detector: {name}</strong>
          <span>共通Detectorの公開済みパラメーターをここで変更できます。</span>
        </div>
      );
    }
    return (
      <div className="nested-group">
        <div className="nested-title">
          共通Detector: {name}
          {actions.inlineDetector ? (
            <button
              className="icon"
              title="インライン化"
              onClick={() => actions.inlineDetector?.(path)}
            >
              ↧
            </button>
          ) : null}
        </div>
        {fields.map((field) => {
          const item = value[field.name];
          if (item === undefined) {
            return null;
          }
          return (
            <SchemaFieldEditor
              key={field.name}
              actions={nested}
              field={field}
              path={[field.name]}
              value={item}
              raw={valueAtPath(value, [field.name])}
            />
          );
        })}
        <MissingOptionalFields actions={nested} path={[]} value={value} fields={fields} />
      </div>
    );
  }
  if (!isMapping(value)) {
    return <p className="error-text">detector は mapping である必要があります。</p>;
  }
  const type = scalar(value.type) ?? "";
  const fields = actions.schema.detectorFields[type] ?? [];
  return (
    <div className="nested-group">
      <div className="nested-title">
        detector
        {optional && actions.remove && !actions.readOnly(path) ? (
          <button
            className="icon"
            title="detector を削除"
            onClick={() => actions.remove?.(path)}
          >
            ×
          </button>
        ) : null}
      </div>
      <div className="setting-row">
        <span className="setting-label">type</span>
        {actions.changeDetectorType && actions.structureEditable(path) ? (
          <select
            value={type}
            onChange={(event) => actions.changeDetectorType?.(path, event.target.value)}
          >
            {Object.keys(actions.schema.detectorFields).map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        ) : (
          <span>{type}</span>
        )}
      </div>
      {fields.map((field) => {
        const item = value[field.name];
        if (item === undefined) {
          return null;
        }
        return (
          <SchemaFieldEditor
            key={field.name}
            actions={actions}
            field={field}
            path={[...path, field.name]}
            value={item}
            raw={actions.rawValue([...path, field.name])}
          />
        );
      })}
      <MissingOptionalFields actions={actions} path={path} value={value} fields={fields} />
      {actions.useDetector
        && actions.structureEditable(path)
        && actions.detectorDefinitions.length > 0 ? (
        <div className="inline-form">
          <select
            value={selectedDefinition}
            onChange={(event) => setSelectedDefinition(event.target.value)}
          >
            {actions.detectorDefinitions.map((definition) => (
              <option key={definition.name} value={definition.name}>
                {definition.name}
              </option>
            ))}
          </select>
          <button
            disabled={!selectedDefinition}
            onClick={() => actions.useDetector?.(path, selectedDefinition)}
          >
            共通Detectorを使用
          </button>
        </div>
      ) : null}
    </div>
  );
}
function AssetSelect({
  actions,
  path,
  value,
  overridden,
  reset,
  readOnly = false,
  expose,
}: {
  actions: PropertyActions;
  path: Path;
  value: JsonValue | undefined;
  overridden: boolean;
  reset?: () => void;
  readOnly?: boolean;
  expose?: {
    exposed: boolean;
    disabled: boolean;
    onChange: (exposed: boolean) => void;
  };
}) {
  const current = scalar(value) ?? "";
  const known = actions.assets.includes(current);
  return (
    <div className="setting-row">
      <span className="setting-label">
        reference
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
      <select
        value={current}
        disabled={readOnly}
        onChange={(event) => actions.set(path, event.target.value)}
      >
        {current === "" ? <option value="">選択してください</option> : null}
        {current !== "" && !known ? (
          <option value={current}>{current} (見つかりません)</option>
        ) : null}
        {actions.assets.map((asset) => (
          <option key={asset} value={asset}>
            {asset}
          </option>
        ))}
      </select>
      <div className="child-actions">
        {current ? (
          <button
            className="icon"
            title="参照パスをコピー"
            onClick={() => void navigator.clipboard?.writeText(current)}
          >
            ⧉
          </button>
        ) : null}
        {reset ? (
          <button className="icon" title="共通定義の値に戻す" onClick={reset}>
            ↺
          </button>
        ) : null}
        {actions.addAsset ? (
          <button
            onClick={() =>
              actions.addAsset?.((asset) => actions.set(path, asset))
            }
          >
            新規追加
          </button>
        ) : null}
      </div>
    </div>
  );
}

function SchemaFieldEditor({
  actions,
  field,
  path,
  value,
  raw,
}: {
  actions: PropertyActions;
  field: FieldSchema;
  path: Path;
  value: JsonValue | undefined;
  raw: JsonValue | undefined;
}) {
  const overridden = actions.overrides.has(pathKey(path));
  const readOnly = actions.readOnly(path);
  const nested = isNestedExposurePath(actions.exposure, path);
  const exposed = actions.isExposed(path);
  const remove = field.required || readOnly || nested || exposed
    ? undefined
    : () => actions.remove?.(path);
  const reset = actions.reset && overridden && !readOnly
    ? () => actions.reset?.(path)
    : undefined;
  const expose = exposureControl(actions, path);
  if (field.kind === "detector") {
    return (
      <DetectorFieldsEditor
        actions={actions}
        path={path}
        value={value}
        raw={raw}
        optional={!field.required}
      />
    );
  }
  if (field.kind === "roi") {
    return <RoiFieldsEditor actions={actions} path={path} value={value} field={field} />;
  }
  if (field.kind === "condition") {
    return (
      <div className="setting-row">
        <span className="setting-label">{field.name}</span>
        <span className="muted">中央ペインで編集</span>
      </div>
    );
  }
  if (field.kind === "condition_list") {
    return (
      <div className="setting-row">
        <span className="setting-label">{field.name}</span>
        <span className="muted">
          {isSequence(value) ? value.length : 0} 件（中央ペインで編集）
        </span>
      </div>
    );
  }
  if (field.name === "reference" && field.kind === "text") {
    return (
      <AssetSelect
        actions={actions}
        path={path}
        value={value}
        overridden={overridden}
        reset={reset}
        readOnly={readOnly}
        expose={expose}
      />
    );
  }
  if (field.kind === "number_list") {
    return (
      <SettingRow
        label={field.name}
        value={value}
        overridden={overridden}
        readOnly={readOnly}
        expose={expose}
        onCommit={(next) => {
          if (isSequence(next)) {
            actions.set(path, next);
          }
        }}
        onReset={reset}
        onRemove={remove}
      />
    );
  }
  return (
    <SettingRow
      label={field.name}
      value={value}
      overridden={overridden}
      readOnly={readOnly}
      expose={expose}
      onCommit={(next) => actions.set(path, next)}
      onReset={reset}
      onRemove={remove}
    />
  );
}

function SettingsEditor({
  value,
  basePath,
  actions,
}: {
  value: JsonValue | undefined;
  basePath: Path;
  actions: PropertyActions;
}) {
  if (isParameterReference(value)) {
    return <p className="muted">共通定義のパラメーターです: {value.$param}</p>;
  }
  if (isSharedUse(value)) {
    return (
      <div className="usage-banner">
        <strong>共通Condition: {sharedUseName(value)}</strong>
        <span>この使用箇所の値は共通定義から取得しています。</span>
      </div>
    );
  }
  if (!isMapping(value)) {
    return <p className="muted">設定できる Condition mapping がありません。</p>;
  }
  const type = conditionType(value);
  const fields = actions.schema.conditionFields[type];
  if (!fields) {
    const detectorFields = actions.schema.detectorFields[type];
    if (detectorFields) {
      return (
        <DetectorFieldsEditor
          actions={actions}
          path={basePath}
          value={value}
          raw={actions.rawValue(basePath)}
        />
      );
    }
    return <p className="error-text">未対応の Condition 型です: {type}</p>;
  }
  const missingRequired = fields.filter(
    (field) => field.required && value[field.name] === undefined,
  );
  return (
    <div className="settings-editor">
      <div className="setting-row">
        <span className="setting-label">type</span>
        {actions.changeConditionType && actions.structureEditable(basePath) ? (
          <select
            value={type}
            onChange={(event) => actions.changeConditionType?.(event.target.value)}
          >
            {Object.keys(actions.schema.conditionFields).map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        ) : (
          <span>{type}</span>
        )}
      </div>
      {missingRequired.map((field) => (
        <div key={field.name} className="setting-row">
          <span className="setting-label">{field.name}</span>
          <span className="error-text">必須項目がありません</span>
          {!actions.readOnly([...basePath, field.name]) ? (
            <button
              className="icon"
              onClick={() =>
                actions.set([...basePath, field.name], structuredClone(field.default))
              }
            >
              +
            </button>
          ) : null}
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
            actions={actions}
            field={field}
            path={[...basePath, field.name]}
            value={item}
            raw={actions.rawValue([...basePath, field.name])}
          />
        );
      })}
      <MissingOptionalFields
        actions={actions}
        path={basePath}
        value={value}
        fields={fields}
      />
      <div className="muted">
        {actions.usageMode
          ? "共通定義で公開された項目だけ変更できます。"
          : actions.definitionMode
            ? "各項目の「公開」を選ぶと、使用箇所から値を変更できます。"
            : null}
      </div>
    </div>
  );
}

function ConditionTree({
  document,
  value,
  nodePath,
  selectedPath,
  onSelect,
  editable,
  sendCommand,
  depth = 0,
}: {
  document: ScenarioDocument;
  value: JsonValue;
  nodePath: Path;
  selectedPath: Path;
  onSelect: (path: Path) => void;
  editable: boolean;
  sendCommand: (command: Record<string, unknown>) => void;
  depth?: number;
}) {
  const selected = pathEquals(nodePath, selectedPath);
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  if (isParameterReference(value)) {
    return (
      <div className="condition-card reference">
        <span className="condition-type">parameter</span>
        <code>{value.$param}</code>
      </div>
    );
  }
  if (isSharedUse(value)) {
    return (
      <div
        className={`condition-card reference ${selected ? "selected" : ""}`}
        onClick={(event) => {
          event.stopPropagation();
          onSelect(nodePath);
        }}
      >
        <span className="condition-type">共通Condition</span>
        <code>{sharedUseName(value)}</code>
        <span className="condition-summary">
          {Object.keys(sharedUseWith(value)).length} overrides
        </span>
      </div>
    );
  }
  if (!isMapping(value)) {
    return <div className="condition-card scalar">{compactValue(value)}</div>;
  }
  const type = conditionType(value);
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
      </div>
      <div className="condition-summary">
        {value.minimum_score !== undefined ? (
          <span>score {compactValue(value.minimum_score)}</span>
        ) : null}
        {value.duration !== undefined ? <span>{compactValue(value.duration)}</span> : null}
        {value.within !== undefined ? <span>within {compactValue(value.within)}</span> : null}
        {value.count !== undefined ? <span>count {compactValue(value.count)}</span> : null}
        {isSharedUse(value.detector) ? (
          <span>detector use {sharedUseName(value.detector)}</span>
        ) : isMapping(value.detector) ? (
          <span>detector {scalar(value.detector.type) ?? ""}</span>
        ) : null}
      </div>
      {childKeys.map((key) => {
        const child = value[key];
        if (key === "conditions") {
          if (!isSequence(child)) {
            return null;
          }
          return (
            <div key={key} className="child-list">
              {child.map((item, index) => (
                <div
                  key={index}
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
                        path: nodePath,
                        from: dragIndex,
                        to: index,
                      });
                    }
                    setDragIndex(null);
                  }}
                >
                  <div className="child-content">
                    <ConditionTree
                      document={document}
                      value={item}
                      nodePath={[...nodePath, "conditions", index]}
                      selectedPath={selectedPath}
                      onSelect={onSelect}
                      editable={editable}
                      sendCommand={sendCommand}
                      depth={depth + 1}
                    />
                  </div>
                  {editable ? (
                    <div className="child-actions">
                      <button
                        className="icon"
                        title="上へ"
                        disabled={index === 0}
                        onClick={(event) => {
                          event.stopPropagation();
                          sendCommand({
                            type: "move_condition",
                            path: nodePath,
                            from: index,
                            to: index - 1,
                          });
                        }}
                      >
                        ↑
                      </button>
                      <button
                        className="icon"
                        title="下へ"
                        disabled={index === child.length - 1}
                        onClick={(event) => {
                          event.stopPropagation();
                          sendCommand({
                            type: "move_condition",
                            path: nodePath,
                            from: index,
                            to: index + 1,
                          });
                        }}
                      >
                        ↓
                      </button>
                      <button
                        className="icon"
                        title="削除"
                        onClick={(event) => {
                          event.stopPropagation();
                          sendCommand({
                            type: "remove_condition",
                            path: nodePath,
                            index,
                          });
                        }}
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
                  onClick={(event) => {
                    event.stopPropagation();
                    sendCommand({
                      type: "add_condition",
                      path: nodePath,
                      index: child.length,
                      value: defaultCondition,
                    });
                  }}
                >
                  + 子 Condition を追加
                </button>
              ) : null}
            </div>
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
              editable={editable}
              sendCommand={sendCommand}
              depth={depth + 1}
            />
          </div>
        );
      })}
    </div>
  );
}

export function ConditionPane({
  document,
  rootPath,
  selectedPath,
  definition,
  onSelect,
  sendCommand,
}: {
  document: ScenarioDocument;
  rootPath: Path;
  selectedPath: Path;
  definition: boolean;
  onSelect: (path: Path) => void;
  sendCommand: (command: Record<string, unknown>) => void;
}) {
  const raw = valueAtPath(conditionRootValue(document, rootPath), []);
  if (raw === undefined || raw === null) {
    return <p className="muted">Condition が設定されていません。</p>;
  }
  const shared = !definition && isSharedUse(raw);
  const display = shared
    ? (resolvedRootAtPath(document, rootPath) ?? raw)
    : raw;
  return (
    <div className="condition-pane">
      <div className="condition-pane-header">
        <h2>{formatPath(document, rootPath)}</h2>
        <span className={`mode-badge ${shared ? "inherits" : "inline"}`}>
          {shared ? `use ${sharedUseName(raw)}` : definition ? "共通定義" : "inline"}
        </span>
      </div>
      {definition ? (
        <p className="muted">共通定義を編集しています。変更はすべての使用箇所に反映されます。</p>
      ) : shared ? (
        <>
          <p className="muted">共通定義の内容を表示しています。構造変更は共通定義側で行います。</p>
          <button
            onClick={() => sendCommand({ type: "inline_condition", path: rootPath })}
          >
            この使用箇所を独立したConditionにする
          </button>
        </>
      ) : null}
      <ConditionTree
        document={document}
        value={display}
        nodePath={rootPath}
        selectedPath={selectedPath}
        onSelect={onSelect}
        editable={!shared && !isSharedUse(raw)}
        sendCommand={sendCommand}
      />
    </div>
  );
}

function conditionRootValue(document: ScenarioDocument, rootPath: Path): JsonValue | undefined {
  return valueAtPathRawRoot(document, rootPath);
}

function valueAtPathRawRoot(
  document: ScenarioDocument,
  rootPath: Path,
): JsonValue | undefined {
  if (rootPath[0] === "definitions" && rootPath[1] === "conditions") {
    return conditionDefinitionByName(document, String(rootPath[2]))?.condition;
  }
  if (rootPath[0] === "start_condition") {
    return document.start_condition ?? undefined;
  }
  if (rootPath[0] === "reset_condition") {
    return document.reset_condition ?? undefined;
  }
  if (rootPath[0] === "incomplete_condition") {
    return document.incomplete_condition ?? undefined;
  }
  if (rootPath[0] === "splits" && typeof rootPath[1] === "number") {
    return document.splits[rootPath[1]]?.rules[rootPath[3] as number]?.condition;
  }
  return undefined;
}

export function DetectorPane({
  document,
  rootPath,
}: {
  document: ScenarioDocument;
  rootPath: Path;
}) {
  const definition = detectorDefinitionByName(document, String(rootPath[2]));
  if (!definition) {
    return <p className="muted">Detector 定義が見つかりません。</p>;
  }
  const detector = definition.detector_resolved;
  return (
    <div className="condition-pane">
      <div className="condition-pane-header">
        <h2>{formatPath(document, rootPath)}</h2>
        <span className="mode-badge inherits">共通Detector</span>
      </div>
      <div className="condition-card">
        <div className="condition-header">
          <span className="condition-type">{conditionType(detector) || "detector"}</span>
        </div>
        <div className="condition-summary">
          {isMapping(detector) && detector.reference !== undefined ? (
            <span>reference {compactValue(detector.reference)}</span>
          ) : null}
          {isMapping(detector) && detector.roi !== undefined ? <span>roi</span> : null}
        </div>
      </div>
      <pre>{JSON.stringify(detector, null, 2)}</pre>
    </div>
  );
}

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
  const [selected, setSelected] = useState(available[0]?.name ?? "");
  const active = available.some((definition) => definition.name === selected)
    ? selected
    : (available[0]?.name ?? "");
  const shared = isSharedUse(selectedValue);
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

function buildActions(
  document: ScenarioDocument,
  schema: EditorSchema,
  workspace: WorkspaceInfo | null,
  mode: "inline" | "definition-condition" | "usage-condition" | "definition-detector",
  rootPath: Path,
  basePath: Path,
  sendCommand: (command: Record<string, unknown>) => void,
  onAddAsset?: (apply: (asset: string) => void) => void,
): PropertyActions {
  const definitionName = String(rootPath[2] ?? "");
  const usageName = isSharedUse(valueAtPathRawRoot(document, rootPath))
    ? sharedUseName(valueAtPathRawRoot(document, rootPath))
    : "";
  const overrideDefinition = mode === "usage-condition"
    ? conditionDefinitionByName(document, usageName)
    : undefined;
  const rawRoot = mode === "definition-detector"
    ? detectorDefinitionByName(document, definitionName)?.detector
    : mode === "usage-condition"
      ? overrideDefinition?.condition
      : valueAtPathRawRoot(document, rootPath);
  const usageMode = mode === "usage-condition";
  const definitionMode = mode === "definition-condition" || mode === "definition-detector";
  const exposure = mode === "definition-condition"
    ? definitionExposureInfo(document, "condition", definitionName)
    : mode === "definition-detector"
      ? definitionExposureInfo(document, "detector", definitionName)
      : usageMode
        ? definitionExposureInfo(document, "condition", usageName)
        : null;
  const overridden = new Set<string>();
  if (usageMode && exposure) {
    const withValues = sharedUseWith(valueAtPathRawRoot(document, rootPath));
    for (const [pathKeyValue, parameter] of exposure.exposed) {
      if (Object.prototype.hasOwnProperty.call(withValues, parameter)) {
        overridden.add(pathKeyValue);
      }
    }
  }
  const absolute = (path: Path) => [...rootPath, ...path];
  const readOnly = (path: Path) => {
    const exposed = exposure?.exposed.has(pathKey(path)) ?? false;
    if (usageMode) {
      return !exposed;
    }
    if (definitionMode && isNestedExposurePath(exposure, path)) {
      return !exposed;
    }
    return false;
  };
  const isExposed = (path: Path) => exposure?.exposed.has(pathKey(path)) ?? false;
  const canExpose = (path: Path) => {
    if (!definitionMode || !exposure) {
      return false;
    }
    if (isNestedExposurePath(exposure, path)) {
      return exposure.nestedExposed.has(pathKey(path));
    }
    return true;
  };
  const structureEditable = (path: Path) => (
    !usageMode && !isNestedExposurePath(exposure, path)
  );
  const actions: PropertyActions = {
    schema,
    detectorDefinitions: document.definitions.detectors,
    assets: workspace?.assets ?? [],
    addAsset: workspace ? onAddAsset : undefined,
    overrides: overridden,
    exposure,
    usageMode,
    definitionMode,
    document,
    rawValue: (path) => valueAtPath(rawRoot, path),
    set: (path, next) => {
      if (readOnly(path)) {
        return;
      }
      if (mode === "usage-condition") {
        sendCommand({
          type: "set_usage_setting",
          path: rootPath,
          setting_path: path,
          value: next,
        });
      } else if (mode === "definition-condition") {
        sendCommand({
          type: "set_definition_setting",
          kind: "condition",
          name: definitionName,
          setting_path: path,
          value: next,
        });
      } else if (mode === "definition-detector") {
        sendCommand({
          type: "set_definition_setting",
          kind: "detector",
          name: definitionName,
          setting_path: path,
          value: next,
        });
      } else {
        sendCommand({ type: "set_value", path: absolute(path), value: next });
      }
    },
    remove: mode === "usage-condition"
      ? undefined
      : (path) => {
          const last = path[path.length - 1];
          if (typeof last !== "string" || readOnly(path)) {
            return;
          }
          if (mode === "definition-condition" || mode === "definition-detector") {
            sendCommand({
              type: "remove_definition_setting",
              kind: mode === "definition-condition" ? "condition" : "detector",
              name: definitionName,
              setting_path: path,
            });
          } else {
            sendCommand({
              type: "remove_setting",
              path: absolute(path.slice(0, -1)),
              key: last,
            });
          }
        },
    reset: mode === "usage-condition"
      ? (path) => {
          if (readOnly(path)) {
            return;
          }
          sendCommand({
            type: "reset_usage_setting",
            path: rootPath,
            setting_path: path,
          });
        }
      : undefined,
    readOnly,
    isExposed,
    canExpose,
    toggleExposure: definitionMode
      ? (path, exposed) => {
          if (!exposed && !window.confirm(
            "公開を解除すると、使用箇所の個別設定は既定値に戻ります。解除しますか？",
          )) {
            return;
          }
          sendCommand({
            type: exposed ? "expose_parameter" : "unexpose_parameter",
            kind: mode === "definition-detector" ? "detector" : "condition",
            name: definitionName,
            setting_path: path,
          });
        }
      : undefined,
    structureEditable,
    changeConditionType: mode === "usage-condition"
      ? undefined
      : (type) => {
          sendCommand({
            type: "set_condition_type",
            path: [...rootPath, ...basePath],
            value: type,
          });
        },
    changeDetectorType: mode === "usage-condition"
      ? undefined
      : (path, type) => {
          sendCommand({
            type: "set_detector_type",
            path: absolute(path),
            value: type,
          });
        },
    useDetector: mode === "usage-condition"
      ? undefined
      : (path, name) => {
          sendCommand({ type: "use_detector", path: absolute(path), name });
        },
    inlineDetector: mode === "usage-condition"
      ? undefined
      : (path) => {
          sendCommand({ type: "inline_detector", path: absolute(path) });
        },
    setDetectorUsage: mode === "usage-condition"
      ? undefined
      : (path, settingPath, next) => {
          sendCommand({
            type: "set_detector_usage_setting",
            path: absolute(path),
            setting_path: settingPath,
            value: next,
          });
        },
    resetDetectorUsage: mode === "usage-condition"
      ? undefined
      : (path, settingPath) => {
          sendCommand({
            type: "reset_detector_usage_setting",
            path: absolute(path),
            setting_path: settingPath,
          });
        },
  };
  return actions;
}
export function ConditionInspector({
  document,
  schema,
  workspace,
  rootPath,
  selectedPath,
  mode,
  sendCommand,
  onAddAsset,
}: {
  document: ScenarioDocument;
  schema: EditorSchema;
  workspace: WorkspaceInfo | null;
  rootPath: Path;
  selectedPath: Path;
  mode: "inline" | "definition-condition" | "usage-condition" | "definition-detector";
  sendCommand: (command: Record<string, unknown>) => void;
  onAddAsset?: (apply: (asset: string) => void) => void;
}) {
  const rawRoot = mode === "definition-detector"
    ? detectorDefinitionByName(document, String(rootPath[2]))?.detector
    : mode === "usage-condition"
      ? conditionDefinitionByName(
          document,
          sharedUseName(valueAtPathRawRoot(document, rootPath)),
        )?.condition
      : valueAtPathRawRoot(document, rootPath);
  const displayRoot = mode === "definition-detector"
    ? detectorDefinitionByName(document, String(rootPath[2]))?.detector_resolved
    : (resolvedRootAtPath(document, rootPath) ?? rawRoot);
  const relative = selectedPath.slice(rootPath.length).filter(
    (part): part is string | number => typeof part === "string" || typeof part === "number",
  );
  const value = valueAtPath(displayRoot, relative);
  const actions = buildActions(
    document,
    schema,
    workspace,
    mode,
    rootPath,
    relative,
    sendCommand,
    onAddAsset,
  );
  return (
    <div className="inspector">
      <h2>Properties</h2>
      <p className="muted">{formatPath(document, selectedPath)}</p>
      {mode !== "definition-detector" && (mode !== "usage-condition" || relative.length === 0) ? (
        <ConditionUsageToolbar
          document={document}
          selectedPath={mode === "usage-condition" ? rootPath : selectedPath}
          selectedValue={mode === "usage-condition" ? rawRoot : value}
          editable={mode !== "usage-condition" || relative.length === 0}
          excludeName={mode === "definition-condition" ? String(rootPath[2] ?? "") : undefined}
          onSelect={() => undefined}
          sendCommand={sendCommand}
        />
      ) : null}
      <SettingsEditor value={value} basePath={relative} actions={actions} />
    </div>
  );
}
