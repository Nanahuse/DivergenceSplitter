export type JsonValue =
  | null
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

export interface ParameterDefinition {
  name: string;
  default: JsonValue;
}

export interface SharedConditionDefinition {
  name: string;
  parameters: ParameterDefinition[];
  condition: JsonValue;
  condition_resolved: JsonValue;
}

export interface SharedDetectorDefinition {
  name: string;
  parameters: ParameterDefinition[];
  detector: JsonValue;
  detector_resolved: JsonValue;
}

export interface Definitions {
  conditions: SharedConditionDefinition[];
  detectors: SharedDetectorDefinition[];
}

export interface RuleDefinition {
  condition: JsonValue;
  condition_resolved: JsonValue;
  action: string;
}

export interface ScenarioRule {
  sequence?: RuleDefinition[];
  condition?: JsonValue;
  condition_resolved?: JsonValue;
  action?: string;
}

export interface SplitDefinition {
  rules: ScenarioRule[];
}

export interface ScenarioDocument {
  path: string;
  dirty: boolean;
  extra_root: Record<string, JsonValue>;
  definitions: Definitions;
  start_condition: JsonValue | null;
  start_condition_resolved: JsonValue | null;
  reset_condition: JsonValue | null;
  reset_condition_resolved: JsonValue | null;
  incomplete_condition: JsonValue | null;
  incomplete_condition_resolved: JsonValue | null;
  splits: (SplitDefinition | null)[];
}

export interface FieldSchema {
  name: string;
  kind:
    | "text"
    | "number"
    | "integer"
    | "duration"
    | "condition"
    | "condition_list"
    | "detector"
    | "roi"
    | "number_list";
  required: boolean;
  default: JsonValue;
}

export interface EditorSchema {
  conditionFields: Record<string, FieldSchema[]>;
  detectorFields: Record<string, FieldSchema[]>;
}

export interface WorkspaceInfo {
  root: string;
  assets: string[];
  scenarios: string[];
}

export interface EditorState {
  type: "state";
  version: number;
  schema: EditorSchema;
  workspace: WorkspaceInfo | null;
  document: ScenarioDocument;
  canUndo: boolean;
  canRedo: boolean;
}

export interface HostError {
  type: "error";
  message: string;
}

export type Path = (string | number)[];

export const conditionTypes = [
  "detected",
  "all",
  "any",
  "not",
  "rising_edge",
  "falling_edge",
  "once",
  "elapsed",
  "hold",
  "nth",
  "reset_when",
  "then",
] as const;

export const detectorTypes = [
  "template_match",
  "mean_absolute_similarity",
  "root_mean_square_similarity",
  "histogram_similarity",
  "perceptual_hash_similarity",
  "difference_hash_similarity",
  "mean_brightness",
  "color_range",
  "phase_correlation",
] as const;

export const actions = [
  "split",
  "skip",
  "undo",
  "reset",
  "pause",
  "resume",
  "start",
] as const;

export function isMapping(
  value: JsonValue | undefined,
): value is Record<string, JsonValue> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isSequence(value: JsonValue | undefined): value is JsonValue[] {
  return Array.isArray(value);
}

export function scalar(value: JsonValue | undefined): string | null {
  return typeof value === "string" ? value : null;
}

export function mappingField(
  value: JsonValue | undefined,
  key: string,
): JsonValue | undefined {
  return isMapping(value) ? value[key] : undefined;
}

export function isParameterReference(
  value: JsonValue | undefined,
): value is { $param: string } {
  return (
    isMapping(value)
    && Object.keys(value).length === 1
    && typeof value.$param === "string"
  );
}

export function isSharedUse(value: JsonValue | undefined): boolean {
  return isMapping(value) && typeof value.use === "string";
}

export function sharedUseName(value: JsonValue | undefined): string {
  return isMapping(value) ? (scalar(value.use) ?? "") : "";
}

export function sharedUseWith(value: JsonValue | undefined): Record<string, JsonValue> {
  return isMapping(value) && isMapping(value.with) ? value.with : {};
}

export function pathKey(path: Path): string {
  return JSON.stringify(path);
}

export function pathEquals(left: Path, right: Path): boolean {
  return pathKey(left) === pathKey(right);
}

export function isPrefix(prefix: Path, path: Path): boolean {
  return prefix.length <= path.length && prefix.every((part, index) => part === path[index]);
}

export function conditionDefinitionByName(
  document: ScenarioDocument,
  name: string,
): SharedConditionDefinition | undefined {
  return document.definitions.conditions.find((definition) => definition.name === name);
}

export function detectorDefinitionByName(
  document: ScenarioDocument,
  name: string,
): SharedDetectorDefinition | undefined {
  return document.definitions.detectors.find((definition) => definition.name === name);
}

export function conditionType(value: JsonValue | undefined): string {
  return scalar(mappingField(value, "type")) ?? "";
}

export function childConditionKeys(type: string): string[] {
  if (type === "all" || type === "any" || type === "then") {
    return ["conditions"];
  }
  if (type === "reset_when") {
    return ["condition", "reset_condition"];
  }
  if (["not", "rising_edge", "falling_edge", "once", "hold", "nth"].includes(type)) {
    return ["condition"];
  }
  return [];
}

export function conditionAtPath(
  document: ScenarioDocument,
  path: Path,
): JsonValue | undefined {
  if (path.length === 0) {
    return undefined;
  }
  if (path[0] === "definitions") {
    const section = path[1];
    const name = path[2];
    if (typeof name !== "string") {
      return undefined;
    }
    if (section === "conditions") {
      return conditionDefinitionByName(document, name)?.condition;
    }
    if (section === "detectors") {
      return detectorDefinitionByName(document, name)?.detector;
    }
    return undefined;
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
  if (path[0] === "splits" && path.length >= 5) {
    const splitIndex = path[1];
    const ruleIndex = path[3];
    if (typeof splitIndex !== "number" || typeof ruleIndex !== "number") {
      return undefined;
    }
    const split = document.splits[splitIndex];
    const rule = split?.rules[ruleIndex];
    return rule?.condition;
  }
  return undefined;
}

export function resolvedRootAtPath(
  document: ScenarioDocument,
  path: Path,
): JsonValue | undefined {
  if (path.length === 0) {
    return undefined;
  }
  if (path[0] === "definitions") {
    const section = path[1];
    const name = path[2];
    if (typeof name !== "string") {
      return undefined;
    }
    if (section === "conditions") {
      return conditionDefinitionByName(document, name)?.condition_resolved;
    }
    if (section === "detectors") {
      return detectorDefinitionByName(document, name)?.detector_resolved;
    }
    return undefined;
  }
  if (path[0] === "start_condition") {
    return document.start_condition_resolved ?? undefined;
  }
  if (path[0] === "reset_condition") {
    return document.reset_condition_resolved ?? undefined;
  }
  if (path[0] === "incomplete_condition") {
    return document.incomplete_condition_resolved ?? undefined;
  }
  if (path[0] === "splits" && typeof path[1] === "number" && typeof path[3] === "number") {
    return document.splits[path[1]]?.rules[path[3]]?.condition_resolved;
  }
  return undefined;
}

export function valueAtPath(root: JsonValue | undefined, path: Path): JsonValue | undefined {
  let current = root;
  for (const part of path) {
    if (typeof part === "number") {
      if (!isSequence(current)) {
        return undefined;
      }
      current = current[part];
    } else {
      if (!isMapping(current)) {
        return undefined;
      }
      current = current[part];
    }
  }
  return current;
}

export function withPath(root: Path, ...parts: (string | number)[]): Path {
  return [...root, ...parts];
}

export function formatPath(_document: ScenarioDocument, path: Path): string {
  if (path[0] === "definitions" && typeof path[2] === "string") {
    const label = path[1] === "detectors" ? "共通Detector" : "共通Condition";
    return `${label}: ${path[2]}`;
  }
  if (path[0] === "start_condition") {
    return "Start";
  }
  if (path[0] === "reset_condition") {
    return "Reset";
  }
  if (path[0] === "incomplete_condition") {
    return "Incomplete";
  }
  if (path[0] === "splits" && typeof path[1] === "number") {
    const split = path[1] + 1;
    if (typeof path[3] === "number") {
      return `Split ${split} / Rule ${path[3] + 1}`;
    }
    return `Split ${split}`;
  }
  return path.join("/");
}

export function parameterPathMap(condition: JsonValue): Map<string, Path> {
  const result = new Map<string, Path>();
  const visit = (value: JsonValue, path: Path) => {
    if (isParameterReference(value)) {
      if (!result.has(value.$param)) {
        result.set(value.$param, path);
      }
      return;
    }
    if (isSequence(value)) {
      value.forEach((item, index) => visit(item, [...path, index]));
      return;
    }
    if (!isMapping(value)) {
      return;
    }
    for (const [key, item] of Object.entries(value)) {
      visit(item, [...path, key]);
    }
  };
  visit(condition, []);
  return result;
}

export function emptyDemoState(): EditorState {
  return {
    type: "state",
    version: 3,
    schema: { conditionFields: {}, detectorFields: {} },
    workspace: null,
    canUndo: false,
    canRedo: false,
    document: {
      path: "",
      dirty: false,
      extra_root: {},
      definitions: { conditions: [], detectors: [] },
      start_condition: { type: "elapsed", duration: "2s" },
      start_condition_resolved: { type: "elapsed", duration: "2s" },
      reset_condition: null,
      reset_condition_resolved: null,
      incomplete_condition: null,
      incomplete_condition_resolved: null,
      splits: [{ rules: [] }],
    },
  };
}
