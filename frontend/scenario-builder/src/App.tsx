import { useCallback, useEffect, useMemo, useState } from "react";
import { listenToHost, sendCommand, sendToHost, isWebViewHost } from "./bridge";
import {
  emptyDemoState,
  formatPath,
  isAlias,
  isInheritanceUsage,
  isMapping,
  usageAnchor,
  type EditorState,
  type JsonValue,
  type Path,
} from "./model";
import { ConditionInspector, ConditionPane, UsageModeToolbar } from "./ConditionEditor";
import { RulesEditor } from "./RulesEditor";

type Selection =
  | { kind: "definition"; name: string }
  | { kind: "special"; name: SpecialCondition }
  | { kind: "split"; index: number }
  | { kind: "rule"; split: number; rule: number }
  | null;

type SpecialCondition = "start_condition" | "reset_condition" | "incomplete_condition";

const starterCondition = { type: "elapsed", duration: "1s" };

function selectionPath(selection: Selection): Path | null {
  if (!selection) {
    return null;
  }
  switch (selection.kind) {
    case "definition":
      return ["definitions", selection.name];
    case "special":
      return [selection.name];
    case "rule":
      return ["splits", selection.split, "rules", selection.rule, "condition"];
    case "split":
      return null;
  }
}

function conditionMode(value: JsonValue | null | undefined): string {
  if (value === null || value === undefined) {
    return "未設定";
  }
  if (isAlias(value)) {
    return `*${usageAnchor(value)}`;
  }
  if (isInheritanceUsage(value)) {
    return `extends *${usageAnchor(value)}`;
  }
  return "inline";
}

export default function App() {
  const [state, setState] = useState<EditorState | null>(
    isWebViewHost() ? null : emptyDemoState(),
  );
  const [selection, setSelection] = useState<Selection>(null);
  const [selectedPath, setSelectedPath] = useState<Path | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newDefinitionName, setNewDefinitionName] = useState("");
  const preview = !isWebViewHost();

  useEffect(() => {
    const detach = listenToHost(
      (nextState) => {
        setState(nextState);
        setError(null);
      },
      (hostError) => setError(hostError.message),
    );
    sendToHost({ type: "ready" });
    return detach;
  }, []);

  useEffect(() => {
    if (!state) {
      return;
    }
    if (selection?.kind === "definition"
      && !state.document.definitions.some((definition) => definition.name === selection.name)) {
      setSelection(null);
    }
    if (selection?.kind === "split" && selection.index >= state.document.splits.length) {
      setSelection(null);
    }
    if (selection?.kind === "rule") {
      const split = state.document.splits[selection.split];
      if (!split || selection.rule >= split.rules.length) {
        setSelection(null);
      }
    }
  }, [state, selection]);

  const rootPath = useMemo(() => selectionPath(selection), [selection]);
  const activePath = selectedPath && rootPath ? selectedPath : rootPath;

  const runCommand = useCallback((command: Record<string, unknown>) => {
    if (!preview) {
      sendCommand(command);
    }
  }, [preview]);

  const chooseSelection = useCallback((next: Selection) => {
    setSelection(next);
    setSelectedPath(selectionPath(next));
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey)) {
        return;
      }
      const key = event.key.toLowerCase();
      if (key === "z" && !event.shiftKey) {
        event.preventDefault();
        runCommand({ type: "undo" });
      } else if (key === "y" || (key === "z" && event.shiftKey)) {
        event.preventDefault();
        runCommand({ type: "redo" });
      } else if (key === "s") {
        event.preventDefault();
        sendToHost({ type: event.shiftKey ? "saveAs" : "save" });
      } else if (key === "o") {
        event.preventDefault();
        sendToHost({ type: "open" });
      } else if (key === "n") {
        event.preventDefault();
        sendToHost({ type: "new" });
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [runCommand]);

  const createDefinition = () => {
    const name = newDefinitionName.trim();
    if (!name) {
      return;
    }
    runCommand({
      type: "set_definition",
      name,
      value: {
        type: "all",
        conditions: [
          { id: "step", type: "elapsed", duration: "1s" },
        ],
      },
    });
    setNewDefinitionName("");
    chooseSelection({ kind: "definition", name });
  };

  const document = state?.document;
  const splitSelection = selection?.kind === "split" ? selection : null;

  return (
    <div className="app">
      <header className="toolbar">
        <div className="brand">
          <strong>Scenario Builder</strong>
          <span className="poc">PoC</span>
        </div>
        <div className="toolbar-group">
          <button onClick={() => sendToHost({ type: "new" })}>新規</button>
          <button onClick={() => sendToHost({ type: "open" })}>開く</button>
          <button onClick={() => sendToHost({ type: "save" })}>保存</button>
          <button onClick={() => sendToHost({ type: "saveAs" })}>名前を付けて保存</button>
        </div>
        <div className="toolbar-group">
          <button
            disabled={!state?.canUndo}
            onClick={() => runCommand({ type: "undo" })}
          >
            Undo
          </button>
          <button
            disabled={!state?.canRedo}
            onClick={() => runCommand({ type: "redo" })}
          >
            Redo
          </button>
        </div>
        <div className="file-status">
          <span className={document?.dirty ? "dirty" : ""}>
            {document?.dirty ? "● " : ""}
            {document?.path || "(未保存)"}
          </span>
        </div>
      </header>

      {preview ? (
        <div className="notice">
          WebView2 ホスト外のプレビューです。編集コマンドは送信されません。
        </div>
      ) : null}
      {error ? (
        <div className="error-banner" onClick={() => setError(null)}>
          {error}
        </div>
      ) : null}

      {!document ? (
        <main className="loading">C++ ホストからの状態を待っています…</main>
      ) : (
        <main className="panes">
          <aside className="pane left-pane">
            <section>
              <div className="section-title">
                <h2>共通定義</h2>
                <span className="count">{document.definitions.length}</span>
              </div>
              <div className="inline-form">
                <input
                  value={newDefinitionName}
                  placeholder="course_finish"
                  onChange={(event) => setNewDefinitionName(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      createDefinition();
                    }
                  }}
                />
                <button onClick={createDefinition}>作成</button>
              </div>
              <ul className="tree-list">
                {document.definitions.map((definition) => (
                  <li
                    key={definition.name}
                    className={
                      selection?.kind === "definition"
                      && selection.name === definition.name
                        ? "active"
                        : ""
                    }
                  >
                    <button
                      className="link-row"
                      onClick={() =>
                        chooseSelection({ kind: "definition", name: definition.name })
                      }
                    >
                      <span className="anchor-mark">
                        {definition.kind === "condition" ? "&" : "#"}
                      </span>
                      {definition.name}
                    </button>
                    <button
                      className="icon"
                      title="共通定義を削除"
                      onClick={() => {
                        if (window.confirm(`共通定義 ${definition.name} を削除しますか？`)) {
                          runCommand({ type: "delete_definition", name: definition.name });
                        }
                      }}
                    >
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            </section>

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

            <section className="split-section">
              <div className="section-title">
                <h2>Split</h2>
                <button
                  onClick={() =>
                    runCommand({
                      type: "add_split",
                      index: document.splits.length,
                    })
                  }
                >
                  + Split
                </button>
              </div>
              <ul className="tree-list">
                {document.splits.map((split, index) => (
                  <li
                    key={index}
                    className={
                      selection?.kind === "split" && selection.index === index
                        ? "active"
                        : ""
                    }
                  >
                    <button
                      className="link-row"
                      onClick={() => chooseSelection({ kind: "split", index })}
                    >
                      <span>Split {index + 1}</span>
                      <span className="mode-hint">
                        {split ? `${split.rules.length} rules` : "manual"}
                      </span>
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
                  </li>
                ))}
              </ul>
            </section>
          </aside>

          <section className="pane center-pane">
            {rootPath && (selection?.kind === "definition"
              || selection?.kind === "special"
              || selection?.kind === "rule") ? (
              <ConditionPane
                document={document}
                usagePath={rootPath}
                selectedPath={activePath ?? rootPath}
                onSelect={setSelectedPath}
                sendCommand={runCommand}
              />
            ) : splitSelection ? (
              <RulesEditor
                document={document}
                splitIndex={splitSelection.index}
                onSelectCondition={(path) => {
                  setSelection({
                    kind: "rule",
                    split: splitSelection.index,
                    rule: path[3] as number,
                  });
                  setSelectedPath(path);
                }}
                sendCommand={runCommand}
              />
            ) : (
              <div className="welcome">
                <h2>Scenario Builder</h2>
                <p>
                  左の一覧から共通定義・Start / Reset / Incomplete・Split
                  を選択してください。
                </p>
                <p className="muted">
                  共通定義を作成し、Condition の参照や継承、使用箇所ごとの
                  overrides を編集できます。
                </p>
              </div>
            )}
          </section>

          <aside className="pane right-pane">
            {rootPath && (selection?.kind === "definition"
              || selection?.kind === "special"
              || selection?.kind === "rule") ? (
              <>
                <ConditionInspector
                  document={document}
                  usagePath={rootPath}
                  selectedPath={activePath ?? rootPath}
                  sendCommand={runCommand}
                />
                {activePath && rootPath && activePath.join("/") !== rootPath.join("/") ? (
                  <button
                    className="secondary"
                    onClick={() => setSelectedPath(rootPath)}
                  >
                    root に戻る
                  </button>
                ) : null}
              </>
            ) : splitSelection ? (
              <div className="inspector">
                <h2>Split {splitSelection.index + 1}</h2>
                <p className="muted">
                  {document.splits[splitSelection.index]
                    ? "中央の一覧から対象 Rule の Condition を開けます。"
                    : "手動区間です。自動区間に変更すると Rule を追加できます。"}
                </p>
              </div>
            ) : (
              <div className="inspector">
                <h2>Properties</h2>
                <p className="muted">
                  Condition を選択すると、設定・参照・上書きを編集できます。
                </p>
                {rootPath ? (
                  <UsageModeToolbar
                    document={document}
                    selectedValue={undefined}
                    selectedPath={rootPath}
                    sendCommand={runCommand}
                  />
                ) : null}
              </div>
            )}
          </aside>
        </main>
      )}

      <footer className="statusbar">
        <span>
          {selection
            ? formatPath(
                document ?? emptyDemoState().document,
                rootPath ?? [],
              )
            : "No selection"}
        </span>
        <span>{isMapping(document?.start_condition) ? "start condition ready" : ""}</span>
      </footer>
    </div>
  );
}
