import { useState } from "react";
import { sendToHost } from "./bridge";
import {
  isSharedUse,
  sharedUseName,
  type DefinitionKind,
  type JsonValue,
  type ParameterDefinition,
  type ScenarioDocument,
  type SplitDefinition,
  type WorkspaceInfo,
} from "./model";
import type { Selection, SpecialCondition } from "./selection";

type RunCommand = (command: Record<string, unknown>) => void;
type ChooseSelection = (selection: Selection) => void;

const starterCondition = { type: "elapsed", duration: "1s" };

function conditionMode(value: JsonValue | null | undefined): string {
  if (value === null || value === undefined) {
    return "未設定";
  }
  return isSharedUse(value) ? `use ${sharedUseName(value)}` : "inline";
}

function DefinitionList({
  kind,
  definitions,
  selection,
  chooseSelection,
  runCommand,
}: {
  kind: DefinitionKind;
  definitions: { name: string; parameters: ParameterDefinition[] }[];
  selection: Selection;
  chooseSelection: ChooseSelection;
  runCommand: RunCommand;
}) {
  const [draft, setDraft] = useState("");
  const isCondition = kind === "condition";
  const selectionKind = isCondition ? "condition-definition" : "detector-definition";
  const label = isCondition ? "共通Condition" : "共通Detector";
  const create = () => {
    const name = draft.trim();
    if (!name) {
      return;
    }
    runCommand({ type: `create_${kind}_definition`, name });
    setDraft("");
    chooseSelection({ kind: selectionKind, name });
  };

  return (
    <section>
      <div className="section-title">
        <h2>{label}</h2>
        <span className="count">{definitions.length}</span>
      </div>
      <div className="inline-form">
        <input
          value={draft}
          placeholder={isCondition ? "course_finish" : "shared_detector"}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              create();
            }
          }}
        />
        <button onClick={create}>作成</button>
      </div>
      <ul className="tree-list">
        {definitions.map(({ name, parameters }) => (
          <li
            key={name}
            className={selection?.kind === selectionKind && selection.name === name ? "active" : ""}
          >
            <button
              className="link-row"
              onClick={() => chooseSelection({ kind: selectionKind, name })}
            >
              <span className="anchor-mark">{isCondition ? "◇" : "#"}</span>
              {name}
              <span className="mode-hint">{parameters.length} params</span>
            </button>
            <button
              className="icon"
              title={`${label}を削除`}
              onClick={() => {
                if (window.confirm(`${name} を削除しますか？`)) {
                  runCommand({ type: `delete_${kind}_definition`, name });
                }
              }}
            >
              ×
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function SplitList({
  splits,
  selection,
  chooseSelection,
  runCommand,
}: {
  splits: (SplitDefinition | null)[];
  selection: Selection;
  chooseSelection: ChooseSelection;
  runCommand: RunCommand;
}) {
  const [draggedSplit, setDraggedSplit] = useState<number | null>(null);
  const [dropTarget, setDropTarget] = useState<{ index: number; after: boolean } | null>(null);
  const moveSplit = (from: number, to: number) => {
    if (from !== to) {
      runCommand({ type: "move_split", from, to });
    }
  };

  return (
    <section className="split-section">
      <div className="section-title">
        <h2>Split</h2>
        <button
          onClick={() =>
            runCommand({
              type: "add_split",
              index: splits.length,
            })
          }
        >
          + Split
        </button>
      </div>
      {splits.length > 1 ? (
        <p className="drag-hint">ドラッグして並び替え</p>
      ) : null}
      <ul className="tree-list split-list">
        {splits.map((split, index) => {
          const drop = dropTarget?.index === index ? dropTarget.after : null;
          return (
            <li
              key={index}
              className={[
                selection?.kind === "split" && selection.index === index
                  ? "active"
                  : "",
                drop === false ? "drop-before" : "",
                drop === true ? "drop-after" : "",
              ].filter(Boolean).join(" ")}
              onDragOver={(event) => {
                event.preventDefault();
                event.dataTransfer.dropEffect = "move";
                const rect = event.currentTarget.getBoundingClientRect();
                setDropTarget({
                  index,
                  after: event.clientY > rect.top + rect.height / 2,
                });
              }}
              onDrop={(event) => {
                event.preventDefault();
                const raw = event.dataTransfer.getData("text/plain");
                const from = draggedSplit ?? (raw === "" ? null : Number(raw));
                const rect = event.currentTarget.getBoundingClientRect();
                const after = event.clientY > rect.top + rect.height / 2;
                if (from !== null && Number.isInteger(from)) {
                  const insertAt = index + (after ? 1 : 0);
                  const to = from < insertAt ? insertAt - 1 : insertAt;
                  moveSplit(from, to);
                }
                setDraggedSplit(null);
                setDropTarget(null);
              }}
            >
              <span
                className="drag-handle"
                draggable
                title="ドラッグして並び替え"
                aria-label="ドラッグして並び替え"
                onDragStart={(event) => {
                  event.dataTransfer.effectAllowed = "move";
                  event.dataTransfer.setData("text/plain", String(index));
                  setDraggedSplit(index);
                }}
                onDragEnd={() => {
                  setDraggedSplit(null);
                  setDropTarget(null);
                }}
              >
                ⠿
              </span>
              <button
                className="link-row"
                onClick={() => chooseSelection({ kind: "split", index })}
              >
                <span>Split {index + 1}</span>
                <span className="mode-hint">
                  {split ? `${split.rules.length} rules` : "manual"}
                </span>
              </button>
              <div className="split-item-actions">
                <button
                  className="icon"
                  title="上へ"
                  disabled={index === 0}
                  onClick={() => moveSplit(index, index - 1)}
                >
                  ↑
                </button>
                <button
                  className="icon"
                  title="下へ"
                  disabled={index === splits.length - 1}
                  onClick={() => moveSplit(index, index + 1)}
                >
                  ↓
                </button>
                <button
                  className="icon"
                  title="Split を削除"
                  onClick={() => {
                    if (window.confirm(`Split ${index + 1} を削除しますか？`)) {
                      runCommand({ type: "remove_split", index });
                    }
                  }}
                >
                  ×
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export function ScenarioNavigation({
  document,
  workspace,
  selection,
  chooseSelection,
  runCommand,
}: {
  document: ScenarioDocument;
  workspace: WorkspaceInfo | null;
  selection: Selection;
  chooseSelection: ChooseSelection;
  runCommand: RunCommand;
}) {
  return (
    <aside className="pane left-pane">
      <section>
        <div className="section-title">
          <h2>作業ディレクトリ</h2>
        </div>
        {workspace ? (
          <>
            <p className="workspace-root" title={workspace.root}>
              {workspace.root}
            </p>
            <h3 className="subsection-title">YAML</h3>
            <ul className="tree-list">
              {workspace.scenarios.map((scenario) => (
                <li
                  key={scenario}
                  className={
                    document.path.endsWith(`\\${scenario}`)
                    || document.path.endsWith(`/${scenario}`)
                      ? "active"
                      : ""
                  }
                >
                  <button
                    className="link-row"
                    onClick={() =>
                      sendToHost({ type: "openScenario", name: scenario })
                    }
                  >
                    <span className="anchor-mark">Y</span>
                    {scenario}
                  </button>
                </li>
              ))}
            </ul>
            {workspace.scenarios.length === 0 ? (
              <p className="muted">YAML ファイルはまだありません。</p>
            ) : null}
          </>
        ) : (
          <p className="muted">
            作業フォルダを開くと、YAML を一覧から切り替えられます。
          </p>
        )}
      </section>
      <DefinitionList
        kind="condition"
        definitions={document.definitions.conditions}
        selection={selection}
        chooseSelection={chooseSelection}
        runCommand={runCommand}
      />
      <DefinitionList
        kind="detector"
        definitions={document.definitions.detectors}
        selection={selection}
        chooseSelection={chooseSelection}
        runCommand={runCommand}
      />
      <section>
        <div className="section-title">
          <h2>シナリオ条件</h2>
        </div>
        <ul className="tree-list">
          {(
            [
              ["start_condition", "Start", document.start_condition],
              ["reset_condition", "Reset", document.reset_condition],
              ["incomplete_condition", "Incomplete", document.incomplete_condition],
            ] as [SpecialCondition, string, JsonValue | null][]
          ).map(([key, label, value]) => (
            <li
              key={key}
              className={
                selection?.kind === "special" && selection.name === key
                  ? "active"
                  : ""
              }
            >
              <button
                className="link-row"
                disabled={value === null || value === undefined}
                onClick={() => chooseSelection({ kind: "special", name: key })}
              >
                <span>{label}</span>
                <span className="mode-hint">{conditionMode(value)}</span>
              </button>
              {key === "start_condition" ? null : (
                <button
                  className="icon"
                  title={value ? "無効化" : "追加"}
                  onClick={() =>
                    runCommand({
                      type: "set_optional_condition",
                      name: key,
                      enabled: !value,
                      value: starterCondition,
                    })
                  }
                >
                  {value ? "−" : "+"}
                </button>
              )}
            </li>
          ))}
        </ul>
      </section>
      <SplitList
        splits={document.splits}
        selection={selection}
        chooseSelection={chooseSelection}
        runCommand={runCommand}
      />
    </aside>
  );
}
