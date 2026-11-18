import { sendToHost } from "./bridge";
import { ConditionInspector } from "./ConditionInspector";
import { ConditionPane, DetectorPane } from "./ConditionPanes";
import type { ConditionInspectorMode } from "./conditionExposure";
import {
  conditionAtPath,
  emptyDemoState,
  formatPath,
  isSharedUse,
  pathEquals,
  type Path,
} from "./model";
import { RulesEditor } from "./RulesEditor";
import { ScenarioNavigation } from "./ScenarioNavigation";
import { selectionPath } from "./selection";
import { useEditorSession } from "./useEditorSession";

export default function App() {
  const {
    state,
    preview,
    error,
    clearError,
    selection,
    selectedPath,
    select,
    selectPath,
    runCommand,
    requestRenameDefinition,
    addAsset,
    inputImage,
    referenceImages,
    pickInputImage,
    requestReferenceImage,
  } = useEditorSession();

  const document = state?.document;
  const workspace = state?.workspace ?? null;
  const rootPath = selectionPath(selection);
  const activePath = selectedPath ?? rootPath;
  const splitSelection = selection?.kind === "split" ? selection : null;

  let inspectorMode: ConditionInspectorMode | null = null;
  if (document && rootPath) {
    if (selection?.kind === "condition-definition") {
      inspectorMode = "definition-condition";
    } else if (selection?.kind === "detector-definition") {
      inspectorMode = "definition-detector";
    } else {
      inspectorMode = isSharedUse(conditionAtPath(document, rootPath))
        ? "usage-condition"
        : "inline";
    }
  }

  const navigateToSplit = (index: number) => select({ kind: "split", index });
  const extractConditionDefinition = (path: Path, name: string) =>
    runCommand({ type: "extract_condition_definition", path, name });

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
        <div className="error-banner" onClick={clearError}>
          {error}
        </div>
      ) : null}

      {!state || !document ? (
        <main className="loading">C++ ホストからの状態を待っています…</main>
      ) : (
        <main className="panes">
          <ScenarioNavigation
            document={document}
            workspace={workspace}
            selection={selection}
            chooseSelection={select}
            runCommand={runCommand}
          />

          <section className="pane center-pane">
            {rootPath && selection?.kind !== "detector-definition" ? (
              <ConditionPane
                document={document}
                rootPath={rootPath}
                selectedPath={activePath ?? rootPath}
                definition={selection?.kind === "condition-definition"}
                onSelect={selectPath}
                sendCommand={runCommand}
                onNavigateSplit={navigateToSplit}
                onRenameDefinition={(from, to) =>
                  requestRenameDefinition("condition", from, to)
                }
              />
            ) : rootPath && selection?.kind === "detector-definition" ? (
              <DetectorPane
                document={document}
                rootPath={rootPath}
                onRenameDefinition={(from, to) =>
                  requestRenameDefinition("detector", from, to)
                }
              />
            ) : splitSelection ? (
              <RulesEditor
                document={document}
                splitIndex={splitSelection.index}
                onSelectCondition={(path) => {
                  const rule = path[3];
                  if (typeof rule !== "number") {
                    return;
                  }
                  const split = splitSelection.index;
                  const step = path[5];
                  if (path[4] === "sequence" && typeof step === "number") {
                    select({ kind: "sequence-rule", split, rule, step }, path);
                  } else {
                    select({ kind: "rule", split, rule }, path);
                  }
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
                  共通Conditionの設定は共通定義側で編集し、
                  「公開」した項目だけを使用箇所から変更できます。
                </p>
              </div>
            )}
          </section>

          <aside className="pane right-pane">
            {rootPath && inspectorMode ? (
              <>
                <ConditionInspector
                  document={document}
                  schema={state.schema}
                  workspace={workspace}
                  onAddAsset={addAsset}
                  rootPath={rootPath}
                  selectedPath={activePath ?? rootPath}
                  mode={inspectorMode}
                  sendCommand={runCommand}
                  onExtractCondition={extractConditionDefinition}
                  inputImage={inputImage}
                  referenceImages={referenceImages}
                  onPickInputImage={pickInputImage}
                  onRequestReferenceImage={requestReferenceImage}
                />
                {activePath && rootPath && !pathEquals(activePath, rootPath) ? (
                  <button className="secondary" onClick={() => selectPath(rootPath)}>
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
