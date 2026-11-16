import {
  definitionExposureInfo,
  isSharedUse,
  pathFromKey,
  pathKey,
  resolvedRootAtPath,
  sharedUseName,
  sharedUseWith,
  type DefinitionExposureInfo,
  type JsonValue,
  type Path,
  type ScenarioDocument,
} from "./model.ts";

export type ConditionInspectorMode =
  | "inline"
  | "definition-condition"
  | "usage-condition"
  | "definition-detector";

export type NestedConditionRootMode = "inline" | "definition-condition";

export interface ConditionExposurePanel {
  conditionName: string;
  exposure: DefinitionExposureInfo | null;
  resolvedRoot: JsonValue | undefined;
}

export function conditionExposurePanel(
  document: ScenarioDocument,
  mode: ConditionInspectorMode,
  rootPath: Path,
  selectedPath: Path,
  rawRoot: JsonValue | undefined,
  nestedUsage: JsonValue | undefined,
  value: JsonValue | undefined,
): ConditionExposurePanel {
  const relative = selectedPath.slice(rootPath.length);
  const panelUsage = nestedUsage
    ?? (
      mode === "usage-condition" && relative.length === 0
        ? rawRoot
        : undefined
    );
  const conditionName = isSharedUse(panelUsage)
    ? sharedUseName(panelUsage)
    : mode === "definition-condition" && relative.length === 0
      ? String(rootPath[2] ?? "")
      : "";
  const exposure = conditionName
    ? definitionExposureInfo(document, "condition", conditionName)
    : null;
  const resolvedRoot = nestedUsage
    ? value
    : resolvedRootAtPath(document, rootPath);
  return { conditionName, exposure, resolvedRoot };
}

export interface NestedConditionUsageExposure {
  usageName: string;
  childExposure: DefinitionExposureInfo;
  parentName: string;
  parentExposure: DefinitionExposureInfo | null;
  overrides: Set<string>;
  parentPath: (path: Path) => Path;
  parentExposed: (path: Path) => boolean;
  childExposed: (path: Path) => boolean;
  writeCommand: (
    path: Path,
    value: JsonValue,
  ) => Record<string, unknown> | null;
  resetCommand: (path: Path) => Record<string, unknown> | null;
}

export function nestedConditionUsageExposure(
  document: ScenarioDocument,
  rootMode: NestedConditionRootMode,
  rootPath: Path,
  usagePath: Path,
  usageValue: JsonValue,
): NestedConditionUsageExposure {
  const usageName = sharedUseName(usageValue);
  const childExposure = definitionExposureInfo(document, "condition", usageName);
  const parentName = rootMode === "definition-condition"
    ? String(rootPath[2] ?? "")
    : "";
  const parentExposure = parentName
    ? definitionExposureInfo(document, "condition", parentName)
    : null;
  const parentPrefix = usagePath.slice(rootPath.length);
  const parentPath = (path: Path) => [...parentPrefix, ...path];
  const parentExposed = (path: Path) => (
    parentExposure?.exposed.has(pathKey(parentPath(path))) ?? false
  );
  const childExposed = (path: Path) => childExposure.exposed.has(pathKey(path));

  const overrides = new Set<string>();
  const withValues = sharedUseWith(usageValue);
  for (const [exposedKey, parameter] of childExposure.exposed) {
    if (
      Object.prototype.hasOwnProperty.call(withValues, parameter)
      && !parentExposed(pathFromKey(exposedKey))
    ) {
      overrides.add(exposedKey);
    }
  }

  return {
    usageName,
    childExposure,
    parentName,
    parentExposure,
    overrides,
    parentPath,
    parentExposed,
    childExposed,
    writeCommand: (path, value) => {
      if (parentExposed(path)) {
        return {
          type: "set_definition_setting",
          kind: "condition",
          name: parentName,
          setting_path: parentPath(path),
          value,
        };
      }
      if (childExposed(path)) {
        return {
          type: "set_usage_setting",
          path: usagePath,
          setting_path: path,
          value,
        };
      }
      return null;
    },
    resetCommand: (path) => {
      if (childExposed(path) && !parentExposed(path)) {
        return {
          type: "reset_usage_setting",
          path: usagePath,
          setting_path: path,
        };
      }
      return null;
    },
  };
}
