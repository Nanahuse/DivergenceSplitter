import {
  conditionType,
  isMapping,
  isSequence,
  isSharedUse,
  pathEquals,
  scalar,
  sharedUseName,
  type JsonValue,
  type Path,
  type ScenarioDocument,
} from "./model";

function formatValue(value: JsonValue | undefined): string {
  if (value === undefined || value === null) {
    return "(未設定)";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

function assetName(asset: string): string {
  return asset.replace(/^Asset\//, "");
}

function detectorTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    root_mean_square_similarity: "RMSE",
    mean_absolute_similarity: "MAE",
    template_match: "template match",
    histogram_similarity: "histogram",
    perceptual_hash_similarity: "pHash",
    difference_hash_similarity: "dHash",
    mean_brightness: "brightness",
    color_range: "color range",
    phase_correlation: "phase correlation",
  };
  return labels[type] ?? type;
}

function settingLabel(path: Path): string {
  const leaf = String(path[path.length - 1] ?? "");
  if (leaf === "reference") {
    return "参照画像";
  }
  return path
    .map((part) => typeof part === "number" ? `[${part}]` : part)
    .join(".");
}

function settingValue(path: Path, value: JsonValue): string {
  if (value === null) {
    return "(未設定)";
  }
  if (String(path[path.length - 1] ?? "") === "reference" && typeof value === "string") {
    return assetName(value);
  }
  return formatValue(value);
}

export function ConditionSummary({
  document,
  condition,
  resolved,
  path,
  showType = true,
  className,
}: {
  document: ScenarioDocument;
  condition: JsonValue | undefined;
  resolved?: JsonValue;
  path: Path;
  showType?: boolean;
  className?: string;
}) {
  const shared = isSharedUse(condition);
  const usage = (document.condition_usages ?? []).find((item) =>
    pathEquals(item.path, path),
  );
  const resolvedValue = usage?.resolved ?? resolved ?? condition ?? null;
  const mapping = isMapping(resolvedValue) ? resolvedValue : {};
  const type = conditionType(mapping);
  const detector = isMapping(mapping.detector) ? mapping.detector : undefined;
  const detectorType = detector ? scalar(detector.type) : null;
  const reference = detector ? scalar(detector.reference) : null;
  const overrides = usage?.overrides ?? [];
  const referenceOverridden = overrides.some(
    (item) => String(item.path[item.path.length - 1] ?? "") === "reference",
  );
  const conditionCount = isSequence(mapping.conditions)
    ? mapping.conditions.length
    : null;

  return (
    <div className={`condition-summary-block ${className ?? ""}`}>
      {shared ? (
        <div className="condition-summary-heading">
          <span
            className="condition-summary-name"
            title={sharedUseName(condition)}
          >
            {sharedUseName(condition)}
          </span>
          <span className="shared-badge">共通</span>
        </div>
      ) : null}
      <div className="condition-summary-line">
        {showType && type ? <span className="condition-summary-type">{type}</span> : null}
        {mapping.duration !== undefined ? (
          <span>{formatValue(mapping.duration)}</span>
        ) : null}
        {mapping.within !== undefined ? (
          <span>within {formatValue(mapping.within)}</span>
        ) : null}
        {mapping.minimum_score !== undefined ? (
          <span>score {formatValue(mapping.minimum_score)}</span>
        ) : null}
        {conditionCount !== null ? <span>条件{conditionCount}件</span> : null}
        {detectorType ? (
          <span title={detectorType}>{detectorTypeLabel(detectorType)}</span>
        ) : null}
        {reference && !referenceOverridden ? (
          <span title={reference}>参照画像 {assetName(reference)}</span>
        ) : null}
      </div>
      {overrides.length > 0 ? (
        <div className="condition-overrides">
          <span className="condition-overrides-title">個別設定</span>
          {overrides.slice(0, 2).map((item, index) => {
            const text = `${settingLabel(item.path)}：${settingValue(item.path, item.default)} → ${settingValue(item.path, item.value)}`;
            return (
              <span
                key={`${item.parameter}-${index}`}
                className="condition-override"
                title={text}
              >
                {text}
              </span>
            );
          })}
          {overrides.length > 2 ? (
            <span className="condition-override-more">
              ほか{overrides.length - 2}項目
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
