import { useEffect, useId, useMemo, useRef, useState } from "react";
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
  pathFromKey,
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
  type PreviewImage,
  type ScenarioDocument,
  type SharedDetectorDefinition,
  type WorkspaceInfo,
} from "./model";
import { Tooltip } from "./Tooltip";
import { ConditionSummary } from "./ConditionSummary";
import { DetectorPreview } from "./InputPreview";
import { Breadcrumb, type BreadcrumbItem } from "./Breadcrumb";
import {
  conditionExposurePanel,
  nestedConditionUsageExposure,
} from "./conditionExposure";

const defaultCondition: JsonValue = { type: "elapsed", duration: "1s" };
function assetName(asset: string): string {
  return asset.replace(/^Asset\//, "");
}

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
  inputImage?: PreviewImage | null;
  referenceImages?: Record<string, string>;
  onPickInputImage?: () => void;
  onRequestReferenceImage?: (reference: string) => void;
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
      !actions.readOnly([...path, field.name]),
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
          <DetectorPreview
            detector={value}
            inputImage={actions.inputImage}
            referenceImages={actions.referenceImages}
            onPickInputImage={actions.onPickInputImage}
            onRequestReferenceImage={actions.onRequestReferenceImage}
          />
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
      inputImage: actions.inputImage,
      referenceImages: actions.referenceImages,
      onPickInputImage: actions.onPickInputImage,
      onRequestReferenceImage: actions.onRequestReferenceImage,
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
        <DetectorPreview
          detector={value}
          inputImage={nested.inputImage}
          referenceImages={nested.referenceImages}
          onPickInputImage={nested.onPickInputImage}
          onRequestReferenceImage={nested.onRequestReferenceImage}
        />
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
      <DetectorPreview
        detector={value}
        inputImage={actions.inputImage}
        referenceImages={actions.referenceImages}
        onPickInputImage={actions.onPickInputImage}
        onRequestReferenceImage={actions.onRequestReferenceImage}
      />
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
  label = "reference",
}: {
  actions: PropertyActions;
  path: Path;
  value: JsonValue | undefined;
  overridden: boolean;
  reset?: () => void;
  readOnly?: boolean;
  label?: string;
  expose?: {
    exposed: boolean;
    disabled: boolean;
    onChange: (exposed: boolean) => void;
  };
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  const titleId = useId();
  const current = scalar(value) ?? "";
  const known = actions.assets.includes(current);
  const filtered = useMemo(() => {
    const term = query.trim().toLocaleLowerCase();
    if (!term) {
      return actions.assets;
    }
    return actions.assets.filter((asset) =>
      asset.toLocaleLowerCase().includes(term)
      || assetName(asset).toLocaleLowerCase().includes(term)
    );
  }, [actions.assets, query]);

  useEffect(() => {
    if (!open) {
      return;
    }
    setQuery("");
    const timer = window.setTimeout(() => searchRef.current?.focus(), 0);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <>
      <div className="asset-setting">
        <div className="asset-setting-header">
          <span className="setting-label">{label}</span>
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
        </div>
        <div className="asset-setting-controls">
          <span
            className={current ? "asset-current" : "asset-current empty"}
            title={current || undefined}
          >
            {current ? assetName(current) : "未選択"}
            {current !== "" && !known ? " (見つかりません)" : ""}
          </span>
          <button
            type="button"
            className="asset-change"
            disabled={readOnly}
            onClick={() => setOpen(true)}
          >
            変更
          </button>
          {reset ? (
            <button
              type="button"
              className="icon"
              title="共通定義の値に戻す"
              onClick={reset}
            >
              ↺
            </button>
          ) : (
            <span />
          )}
        </div>
      </div>

      {open ? (
        <div
          className="asset-dialog-backdrop"
          onMouseDown={() => setOpen(false)}
        >
          <div
            className="asset-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="asset-dialog-header">
              <h2 id={titleId}>参照画像を選択</h2>
              <button
                type="button"
                className="icon"
                title="閉じる"
                onClick={() => setOpen(false)}
              >
                ×
              </button>
            </div>
            <div className="asset-dialog-search">
              <input
                ref={searchRef}
                value={query}
                aria-label="ファイル名で検索"
                placeholder="ファイル名で検索"
                onChange={(event) => setQuery(event.target.value)}
              />
            </div>
            <div className="asset-dialog-list">
              {filtered.map((asset) => (
                <button
                  type="button"
                  key={asset}
                  className={
                    asset === current
                      ? "asset-dialog-option selected"
                      : "asset-dialog-option"
                  }
                  onClick={() => {
                    actions.set(path, asset);
                    setOpen(false);
                  }}
                >
                  <span title={asset}>{assetName(asset)}</span>
                  {asset === current ? (
                    <span className="mode-hint">選択中</span>
                  ) : null}
                </button>
              ))}
              {filtered.length === 0 ? (
                <p className="muted asset-dialog-empty">
                  {actions.assets.length === 0
                    ? "Asset に画像がありません。新規追加してください。"
                    : "一致する画像がありません。"}
                </p>
              ) : null}
            </div>
            <div className="asset-dialog-footer">
              <span className="muted">
                {filtered.length} / {actions.assets.length} 件
              </span>
              {!readOnly && actions.addAsset ? (
                <button
                  type="button"
                  onClick={() =>
                    actions.addAsset?.((asset) => {
                      actions.set(path, asset);
                      setOpen(false);
                    })
                  }
                >
                  ＋ 新規追加...
                </button>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}

function ExposedRoiEditor({
  actions,
  path,
  value,
  label,
  overridden,
  reset,
}: {
  actions: PropertyActions;
  path: Path;
  value: JsonValue | undefined;
  label: string;
  overridden: boolean;
  reset?: () => void;
}) {
  const mapping = isMapping(value) ? value : {};
  const effective: Record<string, JsonValue> = {
    x: "0",
    y: "0",
    width: "1",
    height: "1",
    ...mapping,
  };
  const readOnly = actions.readOnly(path);
  return (
    <div className="exposed-roi-editor">
      <div className="exposed-parameter-header">
        <span>{label}</span>
        {overridden ? <span className="override-badge">この使用箇所</span> : null}
        {!readOnly && reset ? (
          <button
            type="button"
            className="icon"
            title="共通定義の値に戻す"
            onClick={reset}
          >
            ↺
          </button>
        ) : null}
      </div>
      {(["x", "y", "width", "height"] as const).map((key) => (
        <SettingRow
          key={key}
          label={key}
          value={effective[key]}
          readOnly={readOnly}
          onCommit={(next) =>
            actions.set(path, { ...effective, [key]: next })
          }
        />
      ))}
    </div>
  );
}

function ExposedParametersPanel({
  conditionName,
  exposure,
  resolvedRoot,
  actions,
}: {
  conditionName: string;
  exposure: DefinitionExposureInfo | null;
  resolvedRoot: JsonValue | undefined;
  actions: PropertyActions;
}) {
  if (!exposure || exposure.exposed.size === 0) {
    return null;
  }
  const entries: {
    parameter: string;
    path: Path;
    label: string;
    value: JsonValue | undefined;
    overridden: boolean;
  }[] = [];
  const seen = new Set<string>();
  for (const [key, parameter] of exposure.exposed) {
    if (seen.has(parameter)) {
      continue;
    }
    seen.add(parameter);
    const path = pathFromKey(key);
    const owner = exposure.owners.get(key)?.name ?? conditionName;
    const leaf = String(path[path.length - 1] ?? "");
    entries.push({
      parameter,
      path,
      label: `${owner} / ${leaf}`,
      value: valueAtPath(resolvedRoot, path),
      overridden: actions.overrides.has(pathKey(path)),
    });
  }
  if (entries.length === 0) {
    return null;
  }
  return (
    <section className="exposed-parameters">
      <div className="exposed-parameters-header">
        <h3>公開パラメーター</h3>
        <span>共通Condition: {conditionName}</span>
      </div>
      <div className="exposed-parameters-list">
        {entries.map((entry) => {
          const readOnly = actions.readOnly(entry.path);
          const reset = entry.overridden && actions.reset
            ? () => actions.reset?.(entry.path)
            : undefined;
          const leaf = String(entry.path[entry.path.length - 1] ?? "");
          if (leaf === "reference" && typeof entry.value === "string") {
            return (
              <AssetSelect
                key={`${entry.parameter}-${entry.path.join("/")}`}
                actions={actions}
                path={entry.path}
                value={entry.value}
                overridden={entry.overridden}
                reset={reset}
                readOnly={readOnly}
                label={entry.label}
              />
            );
          }
          if (leaf === "roi") {
            return (
              <ExposedRoiEditor
                key={`${entry.parameter}-${entry.path.join("/")}`}
                actions={actions}
                path={entry.path}
                value={entry.value}
                label={entry.label}
                overridden={entry.overridden}
                reset={reset}
              />
            );
          }
          return (
            <SettingRow
              key={`${entry.parameter}-${entry.path.join("/")}`}
              label={entry.label}
              value={entry.value}
              overridden={entry.overridden}
              readOnly={readOnly}
              onCommit={(next) => actions.set(entry.path, next)}
              onReset={reset}
            />
          );
        })}
      </div>
    </section>
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
  const typeControl = actions.changeConditionType && actions.structureEditable(basePath) ? (
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
    <span tabIndex={type === "then" ? 0 : undefined}>{type}</span>
  );
  return (
    <div className="settings-editor">
      <div className="setting-row">
        <span className="setting-label">type</span>
        <Tooltip
          align="end"
          content={type === "then" ? (
            <>
              <strong>then</strong>
              <span>
                複数の条件を順番に判定し、すべて成立したときに1つの操作を実行します。
              </span>
            </>
          ) : undefined}
        >
          {typeControl}
        </Tooltip>
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
        className={`condition-card shared-condition ${selected ? "selected" : ""}`}
        onClick={(event) => {
          event.stopPropagation();
          onSelect(nodePath);
        }}
      >
        <ConditionSummary
          document={document}
          condition={value}
          path={nodePath}
        />
      </div>
    );
  }  if (!isMapping(value)) {
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
      <ConditionSummary
        document={document}
        condition={value}
        path={nodePath}
        showType={false}
      />
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

function ExtractConditionDialog({
  existingNames,
  onClose,
  onSubmit,
}: {
  existingNames: string[];
  onClose: () => void;
  onSubmit: (name: string) => void;
}) {
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const submit = () => {
    const next = name.trim();
    if (!next) {
      setError("共通定義名を入力してください。");
      return;
    }
    if (existingNames.includes(next)) {
      setError("同名の共通Conditionが既に存在します。");
      return;
    }
    onSubmit(next);
    onClose();
  };

  return (
    <div className="asset-dialog-backdrop" onMouseDown={onClose}>
      <form
        className="asset-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="extract-condition-title"
        onMouseDown={(event) => event.stopPropagation()}
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <div className="asset-dialog-header">
          <h2 id="extract-condition-title">共通 Condition として登録</h2>
          <button type="button" className="icon" title="閉じる" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="extract-dialog-body">
          <p className="muted">
            現在の Condition を共通定義に移動し、この場所を共通定義への参照に置き換えます。
          </p>
          <label className="extract-dialog-name">
            <span>共通定義名</span>
            <input
              autoFocus
              value={name}
              placeholder="course_clear_condition"
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          {error ? <p className="error-text">{error}</p> : null}
        </div>
        <div className="asset-dialog-footer">
          <span />
          <div className="dialog-actions">
            <button type="button" className="secondary" onClick={onClose}>
              取消
            </button>
            <button type="submit">登録</button>
          </div>
        </div>
      </form>
    </div>
  );
}

function DefinitionNameEditor({
  label,
  name,
  existingNames,
  onRename,
}: {
  label: string;
  name: string;
  existingNames: string[];
  onRename?: (from: string, to: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(name);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setEditing(false);
    setDraft(name);
    setError(null);
  }, [name]);

  const cancel = () => {
    setDraft(name);
    setEditing(false);
    setError(null);
  };

  const commit = () => {
    const next = draft.trim();
    if (!next) {
      setError("名前を入力してください。");
      return;
    }
    if (next === name) {
      setEditing(false);
      setError(null);
      return;
    }
    if (existingNames.includes(next)) {
      setError("同名の定義が既に存在します。");
      return;
    }
    setEditing(false);
    setError(null);
    onRename?.(name, next);
  };

  return (
    <div className="definition-heading">
      {editing ? (
        <div className="definition-name-editor">
          <input
            autoFocus
            value={draft}
            aria-label={`${label}の名前`}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                commit();
              } else if (event.key === "Escape") {
                event.preventDefault();
                cancel();
              }
            }}
          />
          <button type="button" onClick={commit}>保存</button>
          <button type="button" className="secondary" onClick={cancel}>取消</button>
          {error ? <span className="error-text">{error}</span> : null}
        </div>
      ) : (
        <>
          <h2>{label}: {name}</h2>
          {onRename ? (
            <button
              type="button"
              className="icon rename-button"
              title="名前を変更"
              aria-label="名前を変更"
              onClick={() => {
                setDraft(name);
                setError(null);
                setEditing(true);
              }}
            >
              ✎
            </button>
          ) : null}
        </>
      )}
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
  onNavigateSplit,
  onRenameDefinition,
}: {
  document: ScenarioDocument;
  rootPath: Path;
  selectedPath: Path;
  definition: boolean;
  onSelect: (path: Path) => void;
  sendCommand: (command: Record<string, unknown>) => void;
  onNavigateSplit?: (index: number) => void;
  onRenameDefinition?: (from: string, to: string) => void;
}) {
  const raw = valueAtPath(conditionRootValue(document, rootPath), []);
  if (raw === undefined || raw === null) {
    return <p className="muted">Condition が設定されていません。</p>;
  }
  const shared = !definition && isSharedUse(raw);
  const display = shared
    ? (resolvedRootAtPath(document, rootPath) ?? raw)
    : raw;
  const splitIndex = rootPath[0] === "splits" && typeof rootPath[1] === "number"
    ? rootPath[1]
    : null;
  const ruleIndex = splitIndex !== null && typeof rootPath[3] === "number"
    ? rootPath[3]
    : null;
  const stepIndex = splitIndex !== null && rootPath[4] === "sequence"
    && typeof rootPath[5] === "number"
    ? rootPath[5]
    : null;
  const breadcrumbItems: BreadcrumbItem[] = splitIndex === null
    ? []
    : [
        {
          label: `Split ${splitIndex + 1}`,
          onClick: onNavigateSplit
            ? () => onNavigateSplit(splitIndex)
            : undefined,
        },
        ...(ruleIndex === null
          ? []
          : [{ label: `Rule ${ruleIndex + 1}` }]),
        ...(stepIndex === null
          ? []
          : [{ label: `Step ${stepIndex + 1}` }]),
      ];
  const definitionName = definition ? String(rootPath[2] ?? "") : "";
  const definitionNames = document.definitions.conditions.map(
    (item) => item.name,
  );
  return (
    <div className="condition-pane">
      <div className="condition-pane-header">
        {definition && definitionName ? (
          <DefinitionNameEditor
            label="共通Condition"
            name={definitionName}
            existingNames={definitionNames}
            onRename={onRenameDefinition}
          />
        ) : breadcrumbItems.length > 0 ? (
          <Breadcrumb
            items={breadcrumbItems}
            className="condition-pane-breadcrumb"
          />
        ) : (
          <h2>{formatPath(document, rootPath)}</h2>
        )}
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
    const rule = document.splits[rootPath[1]]?.rules[rootPath[3] as number];
    if (rootPath[4] === "sequence") {
      const stepIndex = rootPath[5];
      if (typeof stepIndex !== "number") {
        return undefined;
      }
      return rule?.sequence?.[stepIndex]?.condition;
    }
    return rule?.condition;
  }
  return undefined;
}

export function DetectorPane({
  document,
  rootPath,
  onRenameDefinition,
}: {
  document: ScenarioDocument;
  rootPath: Path;
  onRenameDefinition?: (from: string, to: string) => void;
}) {
  const definition = detectorDefinitionByName(document, String(rootPath[2]));
  if (!definition) {
    return <p className="muted">Detector 定義が見つかりません。</p>;
  }
  const detector = definition.detector_resolved;
  return (
    <div className="condition-pane">
      <div className="condition-pane-header">
        <DefinitionNameEditor
          label="共通Detector"
          name={definition.name}
          existingNames={document.definitions.detectors.map((item) => item.name)}
          onRename={onRenameDefinition}
        />
        <span className="mode-badge inherits">共通定義</span>
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
function buildNestedConditionUsageActions(
  document: ScenarioDocument,
  schema: EditorSchema,
  workspace: WorkspaceInfo | null,
  rootMode: "inline" | "definition-condition",
  rootPath: Path,
  usagePath: Path,
  usageValue: JsonValue,
  sendCommand: (command: Record<string, unknown>) => void,
  onAddAsset?: (apply: (asset: string) => void) => void,
): PropertyActions {
  const exposure = nestedConditionUsageExposure(
    document,
    rootMode,
    rootPath,
    usagePath,
    usageValue,
  );
  const usageName = exposure.usageName;
  const childDefinition = conditionDefinitionByName(document, usageName);
  const childExposure = exposure.childExposure;
  const parentName = exposure.parentName;
  const parentExposure = exposure.parentExposure;
  const parentPath = exposure.parentPath;
  const parentExposed = exposure.parentExposed;
  const childExposed = exposure.childExposed;
  const overrides = exposure.overrides;

  return {
    schema,
    detectorDefinitions: document.definitions.detectors,
    assets: workspace?.assets ?? [],
    addAsset: workspace ? onAddAsset : undefined,
    overrides,
    exposure: childExposure,
    usageMode: true,
    definitionMode: false,
    document,
    rawValue: (path) => valueAtPath(childDefinition?.condition, path),
    set: (path, next) => {
      const command = exposure.writeCommand(path, next);
      if (command) {
        sendCommand(command);
      }
    },
    readOnly: (path) => !(parentExposed(path) || childExposed(path)),
    isExposed: parentExposed,
    canExpose: (path) => {
      if (!parentExposure) {
        return false;
      }
      const fullPath = parentPath(path);
      if (isNestedExposurePath(parentExposure, fullPath)) {
        return parentExposure.nestedExposed.has(pathKey(fullPath));
      }
      return true;
    },
    toggleExposure: parentExposure
      ? (path, exposed) => {
          if (!exposed && !window.confirm(
            "公開を解除すると、使用箇所の個別設定は既定値に戻ります。解除しますか？",
          )) {
            return;
          }
          sendCommand({
            type: exposed ? "expose_parameter" : "unexpose_parameter",
            kind: "condition",
            name: parentName,
            setting_path: parentPath(path),
          });
        }
      : undefined,
    structureEditable: () => false,
    reset: (path) => {
      const command = exposure.resetCommand(path);
      if (command) {
        sendCommand(command);
      }
    },
  };
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
  onExtractCondition,
  inputImage,
  referenceImages,
  onPickInputImage,
  onRequestReferenceImage,
}: {
  document: ScenarioDocument;
  schema: EditorSchema;
  workspace: WorkspaceInfo | null;
  rootPath: Path;
  selectedPath: Path;
  mode: "inline" | "definition-condition" | "usage-condition" | "definition-detector";
  sendCommand: (command: Record<string, unknown>) => void;
  onAddAsset?: (apply: (asset: string) => void) => void;
  onExtractCondition?: (path: Path, name: string) => void;
  inputImage?: PreviewImage | null;
  referenceImages?: Record<string, string>;
  onPickInputImage?: () => void;
  onRequestReferenceImage?: (reference: string) => void;
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
  const selectedRaw = valueAtPath(rawRoot, relative);
  const nestedUsage = (
    (mode === "inline" || mode === "definition-condition")
    && isSharedUse(selectedRaw)
  ) ? selectedRaw : undefined;
  const value = valueAtPath(displayRoot, relative);
  const canExtract = mode === "inline"
    && isMapping(selectedRaw)
    && !isSharedUse(selectedRaw)
    && !isParameterReference(selectedRaw);
  const [extractOpen, setExtractOpen] = useState(false);
  const baseActions = nestedUsage
    ? buildNestedConditionUsageActions(
        document,
        schema,
        workspace,
        mode === "definition-condition" ? "definition-condition" : "inline",
        rootPath,
        selectedPath,
        nestedUsage,
        sendCommand,
        onAddAsset,
      )
    : buildActions(
        document,
        schema,
        workspace,
        mode,
        rootPath,
        relative,
        sendCommand,
        onAddAsset,
      );
  const actions: PropertyActions = {
    ...baseActions,
    inputImage,
    referenceImages,
    onPickInputImage,
    onRequestReferenceImage,
  };
  const panel = conditionExposurePanel(
    document,
    mode,
    rootPath,
    selectedPath,
    rawRoot,
    nestedUsage,
    value,
  );
  const showExposurePanel = panel.exposure !== null && panel.conditionName !== "";
  return (
    <div className="inspector">
      <h2>Properties</h2>
      <p className="muted">{formatPath(document, selectedPath)}</p>
      {mode !== "definition-detector"
        && (nestedUsage || mode !== "usage-condition" || relative.length === 0) ? (
        <ConditionUsageToolbar
          document={document}
          selectedPath={nestedUsage ? selectedPath : (mode === "usage-condition" ? rootPath : selectedPath)}
          selectedValue={nestedUsage ?? (mode === "usage-condition" ? rawRoot : value)}
          editable={nestedUsage ? true : (mode !== "usage-condition" || relative.length === 0)}
          excludeName={
            mode === "definition-condition" && !nestedUsage
              ? String(rootPath[2] ?? "")
              : undefined
          }
          onSelect={() => undefined}
          sendCommand={sendCommand}
        />
      ) : null}
      {showExposurePanel ? (
        <ExposedParametersPanel
          conditionName={panel.conditionName}
          exposure={panel.exposure}
          resolvedRoot={panel.resolvedRoot}
          actions={actions}
        />
      ) : null}
      {canExtract && onExtractCondition ? (
        <button
          type="button"
          className="secondary extract-condition-button"
          onClick={() => setExtractOpen(true)}
        >
          共通 Condition として登録
        </button>
      ) : null}
      <SettingsEditor
        value={value}
        basePath={nestedUsage ? [] : relative}
        actions={actions}
      />
      {extractOpen ? (
        <ExtractConditionDialog
          existingNames={document.definitions.conditions.map((item) => item.name)}
          onClose={() => setExtractOpen(false)}
          onSubmit={(name) => onExtractCondition?.(selectedPath, name)}
        />
      ) : null}
    </div>
  );
}
