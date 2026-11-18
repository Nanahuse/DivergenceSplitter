import test from "node:test";
import assert from "node:assert/strict";

import {
  adjustSelectionForSplitMutation,
  inverseSplitMutation,
} from "../src/selection.ts";

const rulePath = ["splits", 1, "rules", 0, "condition"];
const splitPath = ["splits", 1];

test("condition edits leave the selection unchanged", () => {
  const selection = { kind: "rule", split: 1, rule: 0 };
  const result = adjustSelectionForSplitMutation(
    selection,
    rulePath,
    null,
    3,
  );
  assert.equal(result.selection, selection);
  assert.equal(result.selectedPath, rulePath);
});

test("removing the selected rule selects the next split", () => {
  const result = adjustSelectionForSplitMutation(
    { kind: "rule", split: 1, rule: 0 },
    rulePath,
    { kind: "remove", index: 1 },
    2,
  );
  assert.deepEqual(result.selection, { kind: "split", index: 1 });
  assert.equal(result.selectedPath, null);
});

test("removing the last selected split selects the previous split", () => {
  const result = adjustSelectionForSplitMutation(
    { kind: "split", index: 2 },
    null,
    { kind: "remove", index: 2 },
    2,
  );
  assert.deepEqual(result.selection, { kind: "split", index: 1 });
  assert.equal(result.selectedPath, null);
});

test("removing the only split clears the selection", () => {
  const result = adjustSelectionForSplitMutation(
    { kind: "split", index: 0 },
    null,
    { kind: "remove", index: 0 },
    0,
  );
  assert.equal(result.selection, null);
  assert.equal(result.selectedPath, null);
});

test("removing an earlier split shifts the selected index and path", () => {
  const result = adjustSelectionForSplitMutation(
    { kind: "sequence-rule", split: 2, rule: 0, step: 1 },
    ["splits", 2, "rules", 0, "sequence", 1, "condition"],
    { kind: "remove", index: 0 },
    2,
  );
  assert.deepEqual(result.selection, {
    kind: "sequence-rule",
    split: 1,
    rule: 0,
    step: 1,
  });
  assert.equal(result.selectedPath[1], 1);
});

test("adding before the selection shifts it and adding after does not", () => {
  const before = adjustSelectionForSplitMutation(
    { kind: "rule", split: 1, rule: 0 },
    rulePath,
    { kind: "add", index: 0 },
    3,
  );
  assert.equal(before.selection.split, 2);
  assert.equal(before.selectedPath[1], 2);

  const after = adjustSelectionForSplitMutation(
    { kind: "rule", split: 1, rule: 0 },
    rulePath,
    { kind: "add", index: 2 },
    3,
  );
  assert.equal(after.selection.split, 1);
  assert.equal(after.selectedPath[1], 1);
});

test("moving the selected split tracks the destination", () => {
  const result = adjustSelectionForSplitMutation(
    { kind: "split", index: 1 },
    splitPath,
    { kind: "move", from: 1, to: 3 },
    4,
  );
  assert.deepEqual(result.selection, { kind: "split", index: 3 });
  assert.equal(result.selectedPath[1], 3);
});

test("moving another split keeps the selected split identity", () => {
  const result = adjustSelectionForSplitMutation(
    { kind: "rule", split: 2, rule: 0 },
    ["splits", 2, "rules", 0, "condition"],
    { kind: "move", from: 0, to: 3 },
    4,
  );
  assert.equal(result.selection.split, 1);
  assert.equal(result.selectedPath[1], 1);
});

test("undone moves restore the tracked index", () => {
  const moved = adjustSelectionForSplitMutation(
    { kind: "split", index: 2 },
    ["splits", 2],
    { kind: "move", from: 0, to: 3 },
    4,
  );
  assert.equal(moved.selection.index, 1);
  const undone = adjustSelectionForSplitMutation(
    moved.selection,
    moved.selectedPath,
    inverseSplitMutation({ kind: "move", from: 0, to: 3 }),
    4,
  );
  assert.equal(undone.selection.index, 2);
  assert.equal(undone.selectedPath[1], 2);
});
