import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { listenToHost, sendCommand, sendToHost, isWebViewHost } from "./bridge";
import {
  conditionAtPath,
  emptyDemoState,
  formatPath,
  isSharedUse,
  sharedUseName,
  type EditorState,
  type JsonValue,
  type Path,
  type WorkspaceInfo,
} from "./model";
import { ConditionInspector, ConditionPane, DetectorPane } from "./ConditionEditor";
import { RulesEditor } from "./RulesEditor";

type Selection =
  | { kind: "condition-definition"; name: string }
  | { kind: "detector-definition"; name: string }
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
    case "condition-definition":
      return ["definitions", "conditions", selection.name];
    case "detector-definition":
      return ["definitions", "detectors", selection.name];
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
  return isSharedUse(value) ? `use ${sharedUseName(value)}` : "inline";
}

export default function App() {
  const [state, setState] = useState<EditorState | null>(
    isWebViewHost() ? null : emptyDemoState(),
  );
  const [selection, setSelection] = useState<Selection>(null);
  const [selectedPath, setSelectedPath] = useState<Path | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newConditionName, setNewConditionName] = useState("");
  const [newDetectorName, setNewDetectorName] = useState("");
  const pendingAssetRef = useRef<((asset: string) => void) | null>(null);
  const preview = !isWebViewHost();

  useEffect(() => {
    const detach = listenToHost(
      (nextState) => {
        setState(nextState);
        setError(null);
      },
      (hostError) => {
        pendingAssetRef.current = null;
        setError(hostError.message);
      },
      (asset) => {
        const apply = pendingAssetRef.current;
        pendingAssetRef.current = null;
        apply?.(asset);
      },
    );
    sendToHost({ type: "ready" });
    return detach;
  }, []);

  const addAsset = useCallback((apply: (asset: string) => void) => {
    if (preview) {
      return;
    }
    pendingAssetRef.current = apply;
    sendToHost({ type: "addAsset" });
  }, [preview]);

  useEffect(() => {
    if (!state) {
      return;
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

  const createConditionDefinition = () => {
    const name = newConditionName.trim();
    if (!name) {
      return;
    }
    runCommand({ type: "create_condition_definition", name });
    setNewConditionName("");
    chooseSelection({ kind: "condition-definition", name });
  };

  const createDetectorDefinition = () => {
    const name = newDetectorName.trim();
    if (!name) {
      return;
    }
    runCommand({ type: "create_detector_definition", name });
    setNewDetectorName("");
    chooseSelection({ kind: "detector-definition", name });
  };

  const document = state?.document;
  const schema = state?.schema ?? { conditionFields: {}, detectorFields: {} };
  const workspace: WorkspaceInfo | null = state?.workspace ?? null;
  const splitSelection = selection?.kind === "split" ? selection : null;

  const inspectorMode = useMemo(() => {
    if (!document || !rootPath) {
      return null;
    }
    if (selection?.kind === "condition-definition") {
      return "definition-condition" as const;
    }
    if (selection?.kind === "detector-definition") {
      return "definition-detector" as const;
    }
    const raw = conditionAtPath(document, rootPath);
    return isSharedUse(raw) ? ("usage-condition" as const) : ("inline" as const);
  }, [document, selection, rootPath]);

  return (
    <div className="app">
      <header className="toolbar">
        <div className="brand">
          <strong>Scenario Builder</strong>
          <span className="poc">YAML v2</span>
        </div>
        <div className="toolbar-group">
          <button onClick={() => sendToHost({ type: "openWorkspace" })}>
            作業フォルダ
          </button>
          <button onClick={() => sendToHost({ type: "new" })}>新規</button>
          <button onClick={() => sendToHost({ type: "open" })}>開く</button>
          <button onClick={() => sendToHost({ type: "save" })}>保存</button>
          <button onClick={() => sendToHost({ type: "saveAs" })}>名前を付けて保存</button>
        </div>
        <div className="toolbar-group">
          <button disabled={!state?.canUndo} onClick={() => runCommand({ type: "undo" })}>
            Undo
          </button>
          <button disabled={!state?.canRedo} onClick={() => runCommand({ type: "redo" })}>
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
                <h2>作業ディレクトリ</h2>
              </div>
              {workspace ? (
                <>
                  <p className="workspace-root" title={workspace.root}>
                    {workspace.root}
                  </p>
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
                  作業フォルダを開くと、YAML と Asset をまとめて管理できます。
                </p>
              )}
            </section>
            <section>
              <div className="section-title">
                <h2>共通Condition</h2>
                <span className="count">{document.definitions.conditions.length}</span>
              </div>
              <div className="inline-form">
                <input
                  value={newConditionName}
                  placeholder="course_finish"
                  onChange={(event) => setNewConditionName(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      createConditionDefinition();
                    }
                  }}
                />
                <button onClick={createConditionDefinition}>作成</button>
              </div>
              <ul className="tree-list">
                {document.definitions.conditions.map((definition) => (
                  <li
                    key={definition.name}
                    className={
                      selection?.kind === "condition-definition"
                      && selection.name === definition.name
                        ? "active"
                        : ""
                    }
                  >
                    <button
                      className="link-row"
                      onClick={() =>
                        chooseSelection({
                          kind: "condition-definition",
                          name: definition.name,
                        })
                      }
                    >
                      <span className="anchor-mark">◇</span>
                      {definition.name}
                      <span className="mode-hint">
                        {definition.parameters.length} params
                      </span>
                    </button>
                    <button
                      className="icon"
                      title="共通Conditionを削除"
                      onClick={() => {
                        if (window.confirm(`${definition.name} を削除しますか？`)) {
                          runCommand({
                            type: "delete_condition_definition",
                            name: definition.name,
                          });
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
                <h2>共通Detector</h2>
                <span className="count">{document.definitions.detectors.length}</span>
              </div>
              <div className="inline-form">
                <input
                  value={newDetectorName}
                  placeholder="shared_detector"
                  onChange={(event) => setNewDetectorName(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      createDetectorDefinition();
                    }
                  }}
                />
                <button onClick={createDetectorDefinition}>作成</button>
              </div>
              <ul className="tree-list">
                {document.definitions.detectors.map((definition) => (
                  <li
                    key={definition.name}
                    className={
                      selection?.kind === "detector-definition"
                      && selection.name === definition.name
                        ? "active"
                        : ""
                    }
                  >
                    <button
                      className="link-row"
                      onClick={() =>
                        chooseSelection({
                          kind: "detector-definition",
                          name: definition.name,
                        })
                      }
                    >
                      <span className="anchor-mark">#</span>
                      {definition.name}
                      <span className="mode-hint">
                        {definition.parameters.length} params
                      </span>
                    </button>
                    <button
                      className="icon"
                      title="共通Detectorを削除"
                      onClick={() => {
                        if (window.confirm(`${definition.name} を削除しますか？`)) {
                          runCommand({
                            type: "delete_detector_definition",
                            name: definition.name,
                          });
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
            {rootPath && selection?.kind === "condition-definition" ? (
              <ConditionPane
                document={document}
                rootPath={rootPath}
                selectedPath={activePath ?? rootPath}
                definition
                onSelect={setSelectedPath}
                sendCommand={runCommand}
              />
            ) : rootPath
              && (selection?.kind === "special" || selection?.kind === "rule") ? (
              <ConditionPane
                document={document}
                rootPath={rootPath}
                selectedPath={activePath ?? rootPath}
                definition={false}
                onSelect={setSelectedPath}
                sendCommand={runCommand}
              />
            ) : rootPath && selection?.kind === "detector-definition" ? (
              <DetectorPane document={document} rootPath={rootPath} />
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
                  左の一覧から共通Condition・共通Detector・Start / Reset / Incomplete・Split
                  を選択してください。
                </p>
                <p className="muted">
                  共通Conditionは通常のConditionと同じプロパティで編集できます。
                  使用箇所だけ変更すると、C++がパラメーターを自動生成します。
                </p>
              </div>
            )}
          </section>

          <aside className="pane right-pane">
            {rootPath && inspectorMode ? (
              <>
                <ConditionInspector
                  document={document}
                  schema={schema}
                  workspace={workspace}
                  onAddAsset={addAsset}
                  rootPath={rootPath}
                  selectedPath={activePath ?? rootPath}
                  mode={inspectorMode}
                  sendCommand={runCommand}
                />
                {activePath && rootPath && activePath.join("/") !== rootPath.join("/") ? (
                  <button className="secondary" onClick={() => setSelectedPath(rootPath)}>
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
                  Condition を選択すると、設定と共通定義の利用方法を編集できます。
                </p>
              </div>
            )}
          </aside>
        </main>
      )}

      <footer className="statusbar">
        <span>
          {selection
            ? formatPath(document ?? emptyDemoState().document, rootPath ?? [])
            : "No selection"}
        </span>
        <span>{document?.start_condition ? "start condition ready" : ""}</span>
      </footer>
    </div>
  );
}
