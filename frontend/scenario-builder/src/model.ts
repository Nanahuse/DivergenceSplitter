export type JsonValue =
  | null
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

export interface AliasValue {
  [key: string]: JsonValue;
  $alias: string;
}

export interface SharedDefinition {
  name: string;
  kind: "condition" | "detector" | "other";
  value: JsonValue;
  resolved: JsonValue;
  ids: string[];
}

export interface RuleDefinition {
  condition: JsonValue;
  condition_resolved?: JsonValue;
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
  definitions: SharedDefinition[];
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

export interface EditorState {
  type: "state";
  version: number;
  schema: EditorSchema;
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

export const actions = ["split", "skip", "undo", "reset", "pause", "resume", "start"] as const;

export function isAlias(value: JsonValue | undefined): value is AliasValue {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    Object.keys(value).length === 1 &&
    typeof (value as Record<string, JsonValue>).$alias === "string"
  );
}

export function isMapping(value: JsonValue | undefined): value is Record<string, JsonValue> {
  return typeof value === "object" && value !== null && !Array.isArray(value) && !isAlias(value);
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

export function pathKey(path: Path): string {
  return JSON.stringify(path);
}

export function pathEquals(left: Path, right: Path): boolean {
  return pathKey(left) === pathKey(right);
}

export function isPrefix(prefix: Path, path: Path): boolean {
  return prefix.length <= path.length && prefix.every((part, index) => part === path[index]);
}

export function definitionByName(
  document: ScenarioDocument,
  name: string,
): SharedDefinition | undefined {
  return document.definitions.find((definition) => definition.name === name);
}

export function conditionType(value: JsonValue | undefined): string {
  return scalar(mappingField(value, "type")) ?? "";
}

export function conditionId(value: JsonValue | undefined): string {
  return scalar(mappingField(value, "id")) ?? "";
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

export function conditionIds(value: JsonValue | undefined, result = new Set<string>()): string[] {
  if (!isMapping(value)) {
    return [...result];
  }
  const id = conditionId(value);
  if (id) {
    result.add(id);
  }
  const type = conditionType(value);
  for (const key of childConditionKeys(type)) {
    const child = value[key];
    if (key === "conditions" && isSequence(child)) {
      child.forEach((item) => conditionIds(item, result));
    } else {
      conditionIds(child, result);
    }
  }
  return [...result];
}

export function isInheritanceUsage(value: JsonValue | undefined): boolean {
  return isMapping(value) && isAlias(value.extends);
}

export function isReferenceUsage(value: JsonValue | undefined): boolean {
  return isAlias(value);
}

export function usageAnchor(value: JsonValue | undefined): string | null {
  if (isAlias(value)) {
    return value.$alias;
  }
  if (isInheritanceUsage(value) && isMapping(value)) {
    const extendsValue = value.extends;
    return isAlias(extendsValue) ? extendsValue.$alias : null;
  }
  return null;
}

export function resolvedRootAtPath(
  document: ScenarioDocument,
  path: Path,
): JsonValue | undefined {
  if (path.length === 0) {
    return undefined;
  }
  if (path[0] === "definitions") {
    const name = path[1];
    if (typeof name !== "string") {
      return undefined;
    }
    return definitionByName(document, name)?.resolved;
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

export function conditionAtPath(
  document: ScenarioDocument,
  path: Path,
): JsonValue | undefined {
  if (path.length === 0) {
    return undefined;
  }
  if (path[0] === "definitions") {
    const name = path[1];
    if (typeof name !== "string") {
      return undefined;
    }
    return definitionByName(document, name)?.value;
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
  if (path[0] === "definitions" && typeof path[1] === "string") {
    return `共通定義: ${path[1]}`;
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

export function emptyDemoState(): EditorState {
  return {
    type: "state",
    version: 2,
    schema: { conditionFields: {}, detectorFields: {} },
    canUndo: false,
    canRedo: false,
    document: {
      path: "",
      dirty: false,
      definitions: [],
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
