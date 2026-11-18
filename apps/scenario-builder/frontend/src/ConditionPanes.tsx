import { useEffect, useState } from "react";
import {
  childConditionKeys,
  conditionAtPath,
  conditionType,
  detectorDefinitionByName,
  formatPath,
  isMapping,
  isParameterReference,
  isSequence,
  isSharedUse,
  pathEquals,
  resolvedRootAtPath,
  sharedUseName,
  type JsonValue,
  type Path,
  type ScenarioDocument,
} from "./model";
import { Breadcrumb, type BreadcrumbItem } from "./Breadcrumb";
import { compactValue } from "./ConditionFields";
import { ConditionSummary } from "./ConditionSummary";

const defaultCondition: JsonValue = { type: "elapsed", duration: "1s" };

function ConditionTree({
  document,
  value,
  nodePath,
  selectedPath,
  onSelect,
  editable,
  sendCommand,
  depth = 0,
}: {
  document: ScenarioDocument;
  value: JsonValue;
  nodePath: Path;
  selectedPath: Path;
  onSelect: (path: Path) => void;
  editable: boolean;
  sendCommand: (command: Record<string, unknown>) => void;
  depth?: number;
}) {
  const selected = pathEquals(nodePath, selectedPath);
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  if (isParameterReference(value)) {
    return (
      <div className="condition-card reference">
        <span className="condition-type">parameter</span>
        <code>{value.$param}</code>
      </div>
    );
  }
  if (isSharedUse(value)) {
    return (
      <div
        className={`condition-card shared-condition ${selected ? "selected" : ""}`}
        onClick={(event) => {
          event.stopPropagation();
          onSelect(nodePath);
        }}
      >
        <ConditionSummary
          document={document}
          condition={value}
          path={nodePath}
        />
      </div>
    );
  }  if (!isMapping(value)) {
    return <div className="condition-card scalar">{compactValue(value)}</div>;
  }
  const type = conditionType(value);
  const childKeys = childConditionKeys(type);
  return (
    <div
      className={`condition-card ${selected ? "selected" : ""} depth-${Math.min(depth, 5)}`}
      onClick={(event) => {
        event.stopPropagation();
        onSelect(nodePath);
      }}
    >
      <div className="condition-header">
        <span className="condition-type">{type || "condition"}</span>
      </div>
      <ConditionSummary
        document={document}
        condition={value}
        path={nodePath}
        showType={false}
      />
      {childKeys.map((key) => {
        const child = value[key];
        if (key === "conditions") {
          if (!isSequence(child)) {
            return null;
          }
          return (
            <div key={key} className="child-list">
              {child.map((item, index) => (
                <div
                  key={index}
                  className="child-row"
                  draggable={editable}
                  onDragStart={() => setDragIndex(index)}
                  onDragOver={(event) => {
                    if (editable) {
                      event.preventDefault();
                    }
                  }}
                  onDrop={(event) => {
                    event.preventDefault();
                    if (editable && dragIndex !== null && dragIndex !== index) {
                      sendCommand({
                        type: "move_condition",
                        path: nodePath,
                        from: dragIndex,
                        to: index,
                      });
                    }
                    setDragIndex(null);
                  }}
                >
                  <div className="child-content">
                    <ConditionTree
                      document={document}
                      value={item}
                      nodePath={[...nodePath, "conditions", index]}
                      selectedPath={selectedPath}
                      onSelect={onSelect}
                      editable={editable}
                      sendCommand={sendCommand}
                      depth={depth + 1}
                    />
                  </div>
                  {editable ? (
                    <div className="child-actions">
                      <button
                        className="icon"
                        title="上へ"
                        disabled={index === 0}
                        onClick={(event) => {
                          event.stopPropagation();
                          sendCommand({
                            type: "move_condition",
                            path: nodePath,
                            from: index,
                            to: index - 1,
                          });
                        }}
                      >
                        ↑
                      </button>
                      <button
                        className="icon"
                        title="下へ"
                        disabled={index === child.length - 1}
                        onClick={(event) => {
                          event.stopPropagation();
                          sendCommand({
                            type: "move_condition",
                            path: nodePath,
                            from: index,
                            to: index + 1,
                          });
                        }}
                      >
                        ↓
                      </button>
                      <button
                        className="icon"
                        title="削除"
                        onClick={(event) => {
                          event.stopPropagation();
                          sendCommand({
                            type: "remove_condition",
                            path: nodePath,
                            index,
                          });
                        }}
                      >
                        ×
                      </button>
                    </div>
                  ) : null}
                </div>
              ))}
              {editable ? (
                <button
                  className="add-child"
                  onClick={(event) => {
                    event.stopPropagation();
                    sendCommand({
                      type: "add_condition",
                      path: nodePath,
                      value: defaultCondition,
                    });
                  }}
                >
                  + 子 Condition を追加
                </button>
              ) : null}
            </div>
          );
        }
        if (child === undefined) {
          return null;
        }
        return (
          <div key={key} className="slot">
            <div className="slot-title">{key}</div>
            <ConditionTree
              document={document}
              value={child}
              nodePath={[...nodePath, key]}
              selectedPath={selectedPath}
              onSelect={onSelect}
              editable={editable}
              sendCommand={sendCommand}
              depth={depth + 1}
            />
          </div>
        );
      })}
    </div>
  );
}

function DefinitionNameEditor({
  label,
  name,
  existingNames,
  onRename,
}: {
  label: string;
  name: string;
  existingNames: string[];
  onRename?: (from: string, to: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(name);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setEditing(false);
    setDraft(name);
    setError(null);
  }, [name]);

  const cancel = () => {
    setDraft(name);
    setEditing(false);
    setError(null);
  };

  const commit = () => {
    const next = draft.trim();
    if (!next) {
      setError("名前を入力してください。");
      return;
    }
    if (next === name) {
      setEditing(false);
      setError(null);
      return;
    }
    if (existingNames.includes(next)) {
      setError("同名の定義が既に存在します。");
      return;
    }
    setEditing(false);
    setError(null);
    onRename?.(name, next);
  };

  return (
    <div className="definition-heading">
      {editing ? (
        <div className="definition-name-editor">
          <input
            autoFocus
            value={draft}
            aria-label={`${label}の名前`}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                commit();
              } else if (event.key === "Escape") {
                event.preventDefault();
                cancel();
              }
            }}
          />
          <button type="button" onClick={commit}>保存</button>
          <button type="button" className="secondary" onClick={cancel}>取消</button>
          {error ? <span className="error-text">{error}</span> : null}
        </div>
      ) : (
        <>
          <h2>{label}: {name}</h2>
          {onRename ? (
            <button
              type="button"
              className="icon rename-button"
              title="名前を変更"
              aria-label="名前を変更"
              onClick={() => {
                setDraft(name);
                setError(null);
                setEditing(true);
              }}
            >
              ✎
            </button>
          ) : null}
        </>
      )}
    </div>
  );
}

export function ConditionPane({
  document,
  rootPath,
  selectedPath,
  definition,
  onSelect,
  sendCommand,
  onNavigateSplit,
  onRenameDefinition,
}: {
  document: ScenarioDocument;
  rootPath: Path;
  selectedPath: Path;
  definition: boolean;
  onSelect: (path: Path) => void;
  sendCommand: (command: Record<string, unknown>) => void;
  onNavigateSplit?: (index: number) => void;
  onRenameDefinition?: (from: string, to: string) => void;
}) {
  const raw = conditionAtPath(document, rootPath);
  if (raw === undefined || raw === null) {
    return <p className="muted">Condition が設定されていません。</p>;
  }
  const shared = !definition && isSharedUse(raw);
  const display = shared
    ? (resolvedRootAtPath(document, rootPath) ?? raw)
    : raw;
  const splitIndex = rootPath[0] === "splits" && typeof rootPath[1] === "number"
    ? rootPath[1]
    : null;
  const ruleIndex = splitIndex !== null && typeof rootPath[3] === "number"
    ? rootPath[3]
    : null;
  const stepIndex = splitIndex !== null && rootPath[4] === "sequence"
    && typeof rootPath[5] === "number"
    ? rootPath[5]
    : null;
  const breadcrumbItems: BreadcrumbItem[] = splitIndex === null
    ? []
    : [
        {
          label: `Split ${splitIndex + 1}`,
          onClick: onNavigateSplit
            ? () => onNavigateSplit(splitIndex)
            : undefined,
        },
        ...(ruleIndex === null
          ? []
          : [{ label: `Rule ${ruleIndex + 1}` }]),
        ...(stepIndex === null
          ? []
          : [{ label: `Step ${stepIndex + 1}` }]),
      ];
  const definitionName = definition ? String(rootPath[2] ?? "") : "";
  const definitionNames = document.definitions.conditions.map(
    (item) => item.name,
  );
  return (
    <div className="condition-pane">
      <div className="condition-pane-header">
        {definition && definitionName ? (
          <DefinitionNameEditor
            label="共通Condition"
            name={definitionName}
            existingNames={definitionNames}
            onRename={onRenameDefinition}
          />
        ) : breadcrumbItems.length > 0 ? (
          <Breadcrumb
            items={breadcrumbItems}
            className="condition-pane-breadcrumb"
          />
        ) : (
          <h2>{formatPath(document, rootPath)}</h2>
        )}
        <span className={`mode-badge ${shared ? "inherits" : "inline"}`}>
          {shared ? `use ${sharedUseName(raw)}` : definition ? "共通定義" : "inline"}
        </span>
      </div>
      {definition ? (
        <p className="muted">共通定義を編集しています。変更はすべての使用箇所に反映されます。</p>
      ) : shared ? (
        <>
          <p className="muted">共通定義の内容を表示しています。構造変更は共通定義側で行います。</p>
          <button
            onClick={() => sendCommand({ type: "inline_condition", path: rootPath })}
          >
            この使用箇所を独立したConditionにする
          </button>
        </>
      ) : null}
      <ConditionTree
        document={document}
        value={display}
        nodePath={rootPath}
        selectedPath={selectedPath}
        onSelect={onSelect}
        editable={!shared && !isSharedUse(raw)}
        sendCommand={sendCommand}
      />
    </div>
  );
}

export function DetectorPane({
  document,
  rootPath,
  onRenameDefinition,
}: {
  document: ScenarioDocument;
  rootPath: Path;
  onRenameDefinition?: (from: string, to: string) => void;
}) {
  const definition = detectorDefinitionByName(document, String(rootPath[2]));
  if (!definition) {
    return <p className="muted">Detector 定義が見つかりません。</p>;
  }
  const detector = definition.detector_resolved;
  return (
    <div className="condition-pane">
      <div className="condition-pane-header">
        <DefinitionNameEditor
          label="共通Detector"
          name={definition.name}
          existingNames={document.definitions.detectors.map((item) => item.name)}
          onRename={onRenameDefinition}
        />
        <span className="mode-badge inherits">共通定義</span>
      </div>
      <div className="condition-card">
        <div className="condition-header">
          <span className="condition-type">{conditionType(detector) || "detector"}</span>
        </div>
        <div className="condition-summary">
          {isMapping(detector) && detector.reference !== undefined ? (
            <span>reference {compactValue(detector.reference)}</span>
          ) : null}
          {isMapping(detector) && detector.roi !== undefined ? <span>roi</span> : null}
        </div>
      </div>
      <pre>{JSON.stringify(detector, null, 2)}</pre>
    </div>
  );
}
