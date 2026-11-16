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

export interface ConditionUsageOverride {
  parameter: string;
  path: Path;
  default: JsonValue;
  value: JsonValue;
}

export interface ConditionUsageDetails {
  path: Path;
  name: string;
  resolved: JsonValue;
  default_resolved: JsonValue;
  overrides: ConditionUsageOverride[];
}

export interface ScenarioDocument {
  path: string;
  dirty: boolean;
  extra_root: Record<string, JsonValue>;
  condition_usages: ConditionUsageDetails[];
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

export interface PreviewImage {
  name: string;
  path?: string;
  url: string;
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

export function pathFromKey(key: string): Path {
  return JSON.parse(key) as Path;
}

export type DefinitionKind = "condition" | "detector";

export interface DefinitionExposureInfo {
  exposed: Map<string, string>;
  nestedExposed: Set<string>;
  nestedPrefixes: Set<string>;
}

interface SharedUseTarget {
  kind: DefinitionKind;
  name: string;
  raw: JsonValue;
}

function sharedUseTarget(
  document: ScenarioDocument,
  value: JsonValue | undefined,
  expected?: DefinitionKind,
): SharedUseTarget | undefined {
  if (!isSharedUse(value)) {
    return undefined;
  }
  const name = sharedUseName(value);
  const condition = conditionDefinitionByName(document, name);
  const detector = detectorDefinitionByName(document, name);
  if (expected === "condition" && condition) {
    return { kind: "condition", name, raw: condition.condition };
  }
  if (expected === "detector" && detector) {
    return { kind: "detector", name, raw: detector.detector };
  }
  if (condition) {
    return { kind: "condition", name, raw: condition.condition };
  }
  if (detector) {
    return { kind: "detector", name, raw: detector.detector };
  }
  return undefined;
}

function collectExposure(
  document: ScenarioDocument,
  value: JsonValue,
  stack: Set<string>,
  path: Path = [],
  expected?: DefinitionKind,
): DefinitionExposureInfo {
  const result: DefinitionExposureInfo = {
    exposed: new Map(),
    nestedExposed: new Set(),
    nestedPrefixes: new Set(),
  };
  if (isParameterReference(value)) {
    result.exposed.set(pathKey(path), value.$param);
    return result;
  }
  if (isSequence(value)) {
    value.forEach((item, index) => {
      const child = collectExposure(document, item, stack, [...path, index], expected);
      for (const [key, parameter] of child.exposed) {
        result.exposed.set(key, parameter);
      }
      child.nestedExposed.forEach((key) => result.nestedExposed.add(key));
      child.nestedPrefixes.forEach((key) => result.nestedPrefixes.add(key));
    });
    return result;
  }
  if (!isMapping(value)) {
    return result;
  }
  if (isSharedUse(value)) {
    const target = sharedUseTarget(document, value, expected);
    const key = target ? `${target.kind}:${target.name}` : "";
    result.nestedPrefixes.add(pathKey(path));
    if (!target || stack.has(key)) {
      return result;
    }
    const nestedStack = new Set(stack);
    nestedStack.add(key);
    const child = collectExposure(document, target.raw, nestedStack, [], target.kind);
    const withValues = sharedUseWith(value);
    for (const [childKey, childParameter] of child.exposed) {
      const fullPath = [...path, ...pathFromKey(childKey)];
      result.nestedExposed.add(pathKey(fullPath));
      const forwarded = withValues[childParameter];
      if (isParameterReference(forwarded)) {
        result.exposed.set(pathKey(fullPath), forwarded.$param);
      }
    }
    for (const prefix of child.nestedPrefixes) {
      result.nestedPrefixes.add(pathKey([...path, ...pathFromKey(prefix)]));
    }
    return result;
  }
  for (const [key, item] of Object.entries(value)) {
    const childExpected = key === "detector"
      ? "detector" as const
      : (key === "condition" || key === "reset_condition" || key === "conditions")
        ? "condition" as const
        : expected;
    const child = collectExposure(document, item, stack, [...path, key], childExpected);
    for (const [childKey, parameter] of child.exposed) {
      result.exposed.set(childKey, parameter);
    }
    child.nestedExposed.forEach((itemKey) => result.nestedExposed.add(itemKey));
    child.nestedPrefixes.forEach((itemKey) => result.nestedPrefixes.add(itemKey));
  }
  return result;
}

export function definitionExposureInfo(
  document: ScenarioDocument,
  kind: DefinitionKind,
  name: string,
): DefinitionExposureInfo {
  const raw = kind === "condition"
    ? conditionDefinitionByName(document, name)?.condition
    : detectorDefinitionByName(document, name)?.detector;
  if (raw === undefined) {
    return { exposed: new Map(), nestedExposed: new Set(), nestedPrefixes: new Set() };
  }
  return collectExposure(document, raw, new Set([`${kind}:${name}`]), [], kind);
}

export function isNestedExposurePath(
  info: DefinitionExposureInfo | null,
  path: Path,
): boolean {
  if (!info) {
    return false;
  }
  for (const prefixKey of info.nestedPrefixes) {
    if (isPrefix(pathFromKey(prefixKey), path)) {
      return true;
    }
  }
  return false;
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
    if (path[4] === "sequence") {
      const stepIndex = path[5];
      if (typeof stepIndex !== "number") {
        return undefined;
      }
      return rule?.sequence?.[stepIndex]?.condition;
    }
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
    const rule = document.splits[path[1]]?.rules[path[3]];
    if (path[4] === "sequence") {
      const stepIndex = path[5];
      if (typeof stepIndex !== "number") {
        return undefined;
      }
      return rule?.sequence?.[stepIndex]?.condition_resolved;
    }
    return rule?.condition_resolved;
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
      if (path[4] === "sequence" && typeof path[5] === "number") {
        return `Split ${split} / Rule ${path[3] + 1} / Step ${path[5] + 1}`;
      }
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
      condition_usages: [],
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
