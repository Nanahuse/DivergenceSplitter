import type { Path } from "./model";

export type SpecialCondition =
  | "start_condition"
  | "reset_condition"
  | "incomplete_condition";

export type Selection =
  | { kind: "condition-definition"; name: string }
  | { kind: "detector-definition"; name: string }
  | { kind: "special"; name: SpecialCondition }
  | { kind: "split"; index: number }
  | { kind: "rule"; split: number; rule: number }
  | { kind: "sequence-rule"; split: number; rule: number; step: number }
  | null;

export type SplitMutation =
  | { kind: "add"; index: number }
  | { kind: "remove"; index: number }
  | { kind: "move"; from: number; to: number };

export function selectionPath(selection: Selection): Path | null {
  if (!selection) {
    return null;
  }
  switch (selection.kind) {
    case "condition-definition":
      return ["definitions", "conditions", selection.name];
    case "detector-definition":
      return ["definitions", "detectors", selection.name];
    case "special":
      return [selection.name];
    case "rule":
      return ["splits", selection.split, "rules", selection.rule, "condition"];
    case "sequence-rule":
      return [
        "splits",
        selection.split,
        "rules",
        selection.rule,
        "sequence",
        selection.step,
        "condition",
      ];
    case "split":
      return null;
  }
}

export function splitMutationForCommand(
  command: Record<string, unknown>,
): SplitMutation | null {
  const type = typeof command.type === "string" ? command.type : "";
  if (type === "add_split" && typeof command.index === "number") {
    return { kind: "add", index: command.index };
  }
  if (type === "remove_split" && typeof command.index === "number") {
    return { kind: "remove", index: command.index };
  }
  if (type === "move_split"
      && typeof command.from === "number"
      && typeof command.to === "number") {
    return { kind: "move", from: command.from, to: command.to };
  }
  return null;
}

function remapSplitIndex(index: number, mutation: SplitMutation): number {
  if (mutation.kind === "add") {
    return index >= mutation.index ? index + 1 : index;
  }
  if (mutation.kind === "remove") {
    return index > mutation.index ? index - 1 : index;
  }
  if (index === mutation.from) {
    return mutation.to;
  }
  if (mutation.from < index && index <= mutation.to) {
    return index - 1;
  }
  if (mutation.to <= index && index < mutation.from) {
    return index + 1;
  }
  return index;
}

export function adjustSelectionForSplitMutation(
  selection: Selection,
  selectedPath: Path | null,
  mutation: SplitMutation | null,
  nextSplitCount: number,
): { selection: Selection; selectedPath: Path | null } {
  if (!mutation || !selection
      || (selection.kind !== "split" && selection.kind !== "rule"
        && selection.kind !== "sequence-rule")) {
    return { selection, selectedPath };
  }
  const oldIndex = selection.kind === "split" ? selection.index : selection.split;
  let nextIndex = oldIndex;
  let selectSplit = false;

  if (mutation.kind === "remove" && oldIndex === mutation.index) {
    if (nextSplitCount === 0) {
      return { selection: null, selectedPath: null };
    }
    nextIndex = Math.min(mutation.index, nextSplitCount - 1);
    selectSplit = true;
  } else {
    nextIndex = remapSplitIndex(oldIndex, mutation);
  }

  if (nextIndex === oldIndex && !selectSplit) {
    return { selection, selectedPath };
  }

  let nextSelection: Selection;
  if (selectSplit || selection.kind === "split") {
    nextSelection = { kind: "split", index: nextIndex };
  } else if (selection.kind === "rule") {
    nextSelection = { ...selection, split: nextIndex };
  } else {
    nextSelection = { ...selection, split: nextIndex };
  }

  const nextPath = selectSplit
    ? null
    : selectedPath && selectedPath[0] === "splits"
      ? selectedPath.map((part, index) => index === 1 ? nextIndex : part)
      : selectedPath;
  return { selection: nextSelection, selectedPath: nextPath };
}

export function inverseSplitMutation(mutation: SplitMutation): SplitMutation {
  if (mutation.kind === "add") {
    return { kind: "remove", index: mutation.index };
  }
  if (mutation.kind === "remove") {
    return { kind: "add", index: mutation.index };
  }
  return { kind: "move", from: mutation.to, to: mutation.from };
}
