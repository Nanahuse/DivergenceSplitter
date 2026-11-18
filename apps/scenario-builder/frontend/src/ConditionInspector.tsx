import { useEffect, useState } from "react";
import {
  formatPath,
  isMapping,
  isParameterReference,
  isSharedUse,
  resolvedRootAtPath,
  valueAtPath,
  type EditorSchema,
  type Path,
  type PreviewImage,
  type ScenarioDocument,
  type WorkspaceInfo,
} from "./model";
import { ExposedParametersPanel, SettingsEditor } from "./ConditionSettings";
import { ConditionUsageToolbar } from "./ConditionUsageToolbar";
import {
  conditionExposurePanel,
  conditionInspectorRoots,
  type ConditionInspectorMode,
} from "./conditionExposure";
import {
  buildNestedConditionUsageActions,
  buildPropertyActions,
  type PropertyActions,
} from "./conditionPropertyActions";

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
  mode: ConditionInspectorMode;
  sendCommand: (command: Record<string, unknown>) => void;
  onAddAsset?: (apply: (asset: string) => void) => void;
  onExtractCondition?: (path: Path, name: string) => void;
  inputImage?: PreviewImage | null;
  referenceImages?: Record<string, string>;
  onPickInputImage?: () => void;
  onRequestReferenceImage?: (reference: string) => void;
}) {
  const roots = conditionInspectorRoots(document, mode, rootPath);
  const { rawUsage, rawRoot } = roots;
  const displayRoot = resolvedRootAtPath(document, rootPath) ?? rawRoot;
  const relative = selectedPath.slice(rootPath.length);
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
  const propertyContext = { document, schema, workspace, rootPath, sendCommand, onAddAsset };
  const baseActions = nestedUsage
    ? buildNestedConditionUsageActions(
        propertyContext,
        mode === "definition-condition" ? "definition-condition" : "inline",
        selectedPath,
        nestedUsage,
      )
    : buildPropertyActions(propertyContext, mode, relative, roots);
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
    rawUsage,
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
          selectedValue={nestedUsage ?? (mode === "usage-condition" ? rawUsage : value)}
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
