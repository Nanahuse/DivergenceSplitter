import {
  conditionDefinitionByName,
  pathKey,
  sharedUseWith,
  valueAtPath,
  definitionExposureInfo,
  isNestedExposurePath,
  type DefinitionExposureInfo,
  type EditorSchema,
  type JsonValue,
  type Path,
  type PreviewImage,
  type ScenarioDocument,
  type SharedDetectorDefinition,
  type WorkspaceInfo,
} from "./model";
import {
  conditionUsageName,
  nestedConditionUsageExposure,
  type ConditionInspectorMode,
  type ConditionInspectorRoots,
  type NestedConditionRootMode,
} from "./conditionExposure";

export interface PropertyActions {
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

export interface PropertyContext {
  document: ScenarioDocument;
  schema: EditorSchema;
  workspace: WorkspaceInfo | null;
  rootPath: Path;
  sendCommand: (command: Record<string, unknown>) => void;
  onAddAsset?: (apply: (asset: string) => void) => void;
}

export function buildPropertyActions(
  { document, schema, workspace, rootPath, sendCommand, onAddAsset }: PropertyContext,
  mode: ConditionInspectorMode,
  basePath: Path,
  { rawUsage, rawRoot }: ConditionInspectorRoots,
): PropertyActions {
  const definitionName = String(rootPath[2] ?? "");
  const usageName = conditionUsageName(rawUsage);
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
    const withValues = sharedUseWith(rawUsage);
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

export function buildNestedConditionUsageActions(
  { document, schema, workspace, rootPath, sendCommand, onAddAsset }: PropertyContext,
  rootMode: NestedConditionRootMode,
  usagePath: Path,
  usageValue: JsonValue,
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
