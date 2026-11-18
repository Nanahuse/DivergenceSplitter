import {
  actions,
  type Path,
  type ScenarioDocument,
  type ScenarioRule,
} from "./model";
import { Tooltip } from "./Tooltip";
import { ConditionSummary } from "./ConditionSummary";

export function RulesEditor({
  document,
  splitIndex,
  onSelectCondition,
  sendCommand,
}: {
  document: ScenarioDocument;
  splitIndex: number;
  onSelectCondition: (path: Path) => void;
  sendCommand: (command: Record<string, unknown>) => void;
}) {
  const split = document.splits[splitIndex];
  const rules = split?.rules ?? [];

  return (
    <div className="rules-editor">
      <div className="condition-pane-header">
        <h2>Split {splitIndex + 1}</h2>
        <span className={`mode-badge ${split ? "inline" : "reference"}`}>
          {split ? "automatic" : "manual"}
        </span>
      </div>
      <div className="inline-form">
        <button
          onClick={() =>
            sendCommand({
              type: "set_split_manual",
              index: splitIndex,
              manual: Boolean(split),
            })
          }
        >
          {split ? "手動区間に変更" : "自動区間に変更"}
        </button>
        {split ? (
          <>
            <Tooltip
              align="start"
              content={
                <>
                  <strong>+ Rule</strong>
                  <span>1つの条件と1つの Action を設定します。</span>
                  <span>例：画像を検出したら Split</span>
                </>
              }
            >
              <button
                onClick={() => sendCommand({ type: "add_rule", split: splitIndex })}
              >
                + Rule
              </button>
            </Tooltip>
            <Tooltip
              align="start"
              content={
                <>
                  <strong>+ Sequence</strong>
                  <span>
                    条件と Action の組を順番に並べます。各ステップの条件が成立すると、
                    そのステップの Action を実行します。
                  </span>
                  <span>例：画像を検出して Split → 3秒後に再び Split</span>
                </>
              }
            >
              <button
                onClick={() =>
                  sendCommand({ type: "add_rule", split: splitIndex, sequence: true })
                }
              >
                + Sequence
              </button>
            </Tooltip>
          </>
        ) : null}
      </div>
      {!split ? (
        <p className="muted">この区間は手動操作です（YAML では null）。</p>
      ) : rules.length === 0 ? (
        <p className="muted">Rule はありません。</p>
      ) : (
        <div className="rule-list">
          {rules.map((rule: ScenarioRule, index) => (
            <div key={index} className="rule-card">
              <div className="rule-header">
                <span className="rule-index">Rule {index + 1}</span>
                {rule.sequence ? (
                  <span className="mode-badge inherits">sequence</span>
                ) : null}
                <div className="child-actions">
                  <button
                    className="icon"
                    title="上へ"
                    disabled={index === 0}
                    onClick={() =>
                      sendCommand({
                        type: "move_rule",
                        split: splitIndex,
                        from: index,
                        to: index - 1,
                      })
                    }
                  >
                    ↑
                  </button>
                  <button
                    className="icon"
                    title="下へ"
                    disabled={index === rules.length - 1}
                    onClick={() =>
                      sendCommand({
                        type: "move_rule",
                        split: splitIndex,
                        from: index,
                        to: index + 1,
                      })
                    }
                  >
                    ↓
                  </button>
                  <button
                    className="icon"
                    title="削除"
                    onClick={() =>
                      sendCommand({ type: "remove_rule", split: splitIndex, index })
                    }
                  >
                    ×
                  </button>
                </div>
              </div>
              {rule.sequence ? (
                <div className="sequence-steps">
                  {rule.sequence.map((step, stepIndex) => (
                    <div key={stepIndex} className="sequence-step">
                      <button
                        type="button"
                        className="sequence-condition-link"
                        onClick={() =>
                          onSelectCondition([
                            "splits",
                            splitIndex,
                            "rules",
                            index,
                            "sequence",
                            stepIndex,
                            "condition",
                          ])
                        }
                      >
                        <ConditionSummary
                          document={document}
                          condition={step.condition}
                          resolved={step.condition_resolved}
                          path={[
                            "splits",
                            splitIndex,
                            "rules",
                            index,
                            "sequence",
                            stepIndex,
                            "condition",
                          ]}
                        />
                      </button>
                      <select
                        value={step.action}
                        onChange={(event) =>
                          sendCommand({
                            type: "set_action",
                            split: splitIndex,
                            index,
                            step: stepIndex,
                            action: event.target.value,
                          })
                        }
                      >
                        {actions.map((action) => (
                          <option key={action} value={action}>
                            {action}
                          </option>
                        ))}
                      </select>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="rule-body">
                  <button
                    className="condition-link"
                    onClick={() =>
                      onSelectCondition([
                        "splits",
                        splitIndex,
                        "rules",
                        index,
                        "condition",
                      ])
                    }
                  >
                    <ConditionSummary
                      document={document}
                      condition={rule.condition ?? null}
                      resolved={rule.condition_resolved}
                      path={["splits", splitIndex, "rules", index, "condition"]}
                    />
                  </button>
                  <select
                    value={rule.action}
                    onChange={(event) =>
                      sendCommand({
                        type: "set_action",
                        split: splitIndex,
                        index,
                        action: event.target.value,
                      })
                    }
                  >
                    {actions.map((action) => (
                      <option key={action} value={action}>
                        {action}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
