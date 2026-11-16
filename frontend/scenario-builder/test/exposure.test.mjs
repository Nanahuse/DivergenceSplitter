import test from "node:test";
import assert from "node:assert/strict";

import {
  conditionExposurePanel,
  nestedConditionUsageExposure,
} from "../src/conditionExposure.ts";
import { pathKey, valueAtPath } from "../src/model.ts";

const referencePath = ["conditions", 1, "detector", "reference"];
const ruleRoot = ["splits", 0, "rules", 0, "condition"];
const parentRoot = ["definitions", "conditions", "sp_parent"];

const spEvenRaw = {
  type: "all",
  conditions: [
    { type: "elapsed", duration: "1s" },
    {
      type: "detected",
      detector: {
        type: "template_match",
        template: "Asset/SP.png",
        reference: { $param: "reference" },
      },
    },
  ],
};

function spEvenResolved(reference) {
  return {
    type: "all",
    conditions: [
      { type: "elapsed", duration: "1s" },
      {
        type: "detected",
        detector: {
          type: "template_match",
          template: "Asset/SP.png",
          reference,
        },
      },
    ],
  };
}

const parentUse = {
  use: "sp_even",
  with: { reference: { $param: "course_name_reference" } },
};

const parentRaw = {
  type: "then",
  conditions: [parentUse, { type: "elapsed", duration: "2s" }],
};

const parentResolved = {
  type: "then",
  conditions: [spEvenResolved("Asset/SP1.png"), { type: "elapsed", duration: "2s" }],
};

const rootUse = { use: "sp_even", with: { reference: "Asset/SP2.png" } };

const nestedRaw = {
  type: "then",
  conditions: [
    { type: "elapsed", duration: "1s" },
    {
      type: "all",
      conditions: [
        { type: "elapsed", duration: "2s" },
        { use: "sp_even" },
      ],
    },
  ],
};

const nestedResolved = {
  type: "then",
  conditions: [
    { type: "elapsed", duration: "1s" },
    {
      type: "all",
      conditions: [
        { type: "elapsed", duration: "2s" },
        spEvenResolved("Asset/SP1.png"),
      ],
    },
  ],
};

const nestedRuleRoot = ["splits", 1, "rules", 0, "condition"];

const document = {
  path: "scenario.yaml",
  dirty: false,
  extra_root: {},
  condition_usages: [],
  definitions: {
    conditions: [
      {
        name: "sp_even",
        parameters: [{ name: "reference", default: "Asset/SP1.png" }],
        condition: spEvenRaw,
        condition_resolved: spEvenResolved("Asset/SP1.png"),
      },
      {
        name: "sp_parent",
        parameters: [{ name: "course_name_reference", default: "Asset/SP1.png" }],
        condition: parentRaw,
        condition_resolved: parentResolved,
      },
    ],
    detectors: [],
  },
  start_condition: null,
  start_condition_resolved: null,
  reset_condition: null,
  reset_condition_resolved: null,
  incomplete_condition: null,
  incomplete_condition_resolved: null,
  splits: [
    {
      rules: [
        {
          condition: rootUse,
          condition_resolved: spEvenResolved("Asset/SP2.png"),
          action: "a",
        },
      ],
    },
    {
      rules: [
        {
          condition: nestedRaw,
          condition_resolved: nestedResolved,
          action: "b",
        },
      ],
    },
  ],
};

function nestedSelection(root, selectedRelativePath) {
  const relative = selectedRelativePath ?? [];
  return {
    selectedPath: [...root, ...relative],
    nestedUsage: valueAtPath(
      root[0] === "definitions"
        ? document.definitions.conditions.find((item) => item.name === root[2]).condition
        : document.splits[root[1]].rules[root[3]].condition,
      relative,
    ),
    value: valueAtPath(
      root[0] === "definitions"
        ? document.definitions.conditions.find((item) => item.name === root[2]).condition_resolved
        : document.splits[root[1]].rules[root[3]].condition_resolved,
      relative,
    ),
  };
}

test("root shared condition exposes its parameters", () => {
  const panel = conditionExposurePanel(
    document,
    "usage-condition",
    ruleRoot,
    ruleRoot,
    document.splits[0].rules[0].condition,
    undefined,
    document.splits[0].rules[0].condition_resolved,
  );
  assert.equal(panel.conditionName, "sp_even");
  assert.equal(panel.exposure.exposed.get(pathKey(referencePath)), "reference");
  assert.equal(
    valueAtPath(panel.resolvedRoot, referencePath),
    "Asset/SP2.png",
  );
});

test("shared condition nested under then exposes its parameters", () => {
  const relative = ["conditions", 1, "conditions", 1];
  const selected = nestedSelection(nestedRuleRoot, relative);
  const panel = conditionExposurePanel(
    document,
    "inline",
    nestedRuleRoot,
    selected.selectedPath,
    nestedRaw,
    selected.nestedUsage,
    selected.value,
  );
  assert.equal(panel.conditionName, "sp_even");
  assert.equal(panel.exposure.exposed.get(pathKey(referencePath)), "reference");
  assert.equal(valueAtPath(panel.resolvedRoot, referencePath), "Asset/SP1.png");
});

test("shared condition nested under all and any exposes its parameters", () => {
  for (const type of ["all", "any"]) {
    const relativeRoot = {
      type: "then",
      conditions: [
        {
          type,
          conditions: [
            { type: "elapsed", duration: "3s" },
            { use: "sp_even" },
          ],
        },
      ],
    };
    const relative = ["conditions", 0, "conditions", 1];
    const selected = valueAtPath(relativeRoot, relative);
    const panel = conditionExposurePanel(
      document,
      "inline",
      ruleRoot,
      [...ruleRoot, ...relative],
      relativeRoot,
      selected,
      spEvenResolved("Asset/SP1.png"),
    );
    assert.equal(panel.conditionName, "sp_even", type);
    assert.equal(panel.exposure.exposed.get(pathKey(referencePath)), "reference");
  }
});

test("deeply nested shared condition uses the selected child definition", () => {
  const relativeRoot = {
    type: "then",
    conditions: [
      {
        type: "all",
        conditions: [
          {
            type: "then",
            conditions: [{ use: "sp_even" }],
          },
        ],
      },
    ],
  };
  const relative = ["conditions", 0, "conditions", 0, "conditions", 0];
  const panel = conditionExposurePanel(
    document,
    "inline",
    ruleRoot,
    [...ruleRoot, ...relative],
    relativeRoot,
    valueAtPath(relativeRoot, relative),
    spEvenResolved("Asset/SP1.png"),
  );
  assert.equal(panel.conditionName, "sp_even");
  assert.equal(panel.exposure.exposed.get(pathKey(referencePath)), "reference");
});

test("forwarded child parameter is exposed on the parent definition", () => {
  const panel = conditionExposurePanel(
    document,
    "definition-condition",
    parentRoot,
    parentRoot,
    parentRaw,
    undefined,
    parentResolved,
  );
  const forwarded = [
    "conditions",
    0,
    ...referencePath,
  ];
  assert.equal(panel.conditionName, "sp_parent");
  assert.equal(
    panel.exposure.exposed.get(pathKey(forwarded)),
    "course_name_reference",
  );
  assert.equal(
    valueAtPath(panel.resolvedRoot, forwarded),
    "Asset/SP1.png",
  );
});

test("nested use inside a shared definition uses the child exposure panel", () => {
  const relative = ["conditions", 0];
  const selected = nestedSelection(parentRoot, relative);
  const panel = conditionExposurePanel(
    document,
    "definition-condition",
    parentRoot,
    selected.selectedPath,
    parentRaw,
    selected.nestedUsage,
    selected.value,
  );
  assert.equal(panel.conditionName, "sp_even");
  assert.equal(panel.exposure.exposed.get(pathKey(referencePath)), "reference");
  assert.equal(valueAtPath(panel.resolvedRoot, referencePath), "Asset/SP1.png");
});

test("selecting an inline parent does not show child parameters", () => {
  const panel = conditionExposurePanel(
    document,
    "inline",
    ruleRoot,
    ruleRoot,
    parentRaw,
    undefined,
    parentResolved,
  );
  assert.equal(panel.conditionName, "");
  assert.equal(panel.exposure, null);
});

test("changing a nested reference targets only the selected usage", () => {
  const usagePath = [...ruleRoot, "conditions", 1, "conditions", 1];
  const context = nestedConditionUsageExposure(
    document,
    "inline",
    ruleRoot,
    usagePath,
    { use: "sp_even" },
  );
  const command = context.writeCommand(referencePath, "Asset/SP2.png");
  assert.deepEqual(command, {
    type: "set_usage_setting",
    path: usagePath,
    setting_path: referencePath,
    value: "Asset/SP2.png",
  });
});

test("resetting a nested reference removes its usage override", () => {
  const usagePath = [...ruleRoot, "conditions", 1, "conditions", 1];
  const context = nestedConditionUsageExposure(
    document,
    "inline",
    ruleRoot,
    usagePath,
    { use: "sp_even", with: { reference: "Asset/SP2.png" } },
  );
  assert.equal(context.overrides.has(pathKey(referencePath)), true);
  assert.deepEqual(context.resetCommand(referencePath), {
    type: "reset_usage_setting",
    path: usagePath,
    setting_path: referencePath,
  });
});

test("forwarding inside a definition edits the parent parameter, not the child usage", () => {
  const usagePath = [...parentRoot, "conditions", 0];
  const context = nestedConditionUsageExposure(
    document,
    "definition-condition",
    parentRoot,
    usagePath,
    parentUse,
  );
  const forwarded = ["conditions", 0, ...referencePath];
  assert.equal(context.overrides.has(pathKey(referencePath)), false);
  assert.equal(context.resetCommand(referencePath), null);
  assert.deepEqual(context.writeCommand(referencePath, "Asset/SP3.png"), {
    type: "set_definition_setting",
    kind: "condition",
    name: "sp_parent",
    setting_path: forwarded,
    value: "Asset/SP3.png",
  });
});
