import { useEffect, useId, useMemo, useRef, useState } from "react";
import {
  conditionType,
  isMapping,
  isParameterReference,
  isSequence,
  isSharedUse,
  pathFromKey,
  pathKey,
  scalar,
  sharedUseName,
  sharedUseWith,
  valueAtPath,
  definitionExposureInfo,
  isNestedExposurePath,
  type DefinitionExposureInfo,
  type FieldSchema,
  type JsonValue,
  type Path,
} from "./model";
import { SettingRow } from "./ConditionFields";
import { DetectorPreview } from "./InputPreview";
import { Tooltip } from "./Tooltip";
import type { PropertyActions } from "./conditionPropertyActions";

function assetName(asset: string): string {
  return asset.replace(/^Asset\//, "");
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

export function ExposedParametersPanel({
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

export function SettingsEditor({
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
