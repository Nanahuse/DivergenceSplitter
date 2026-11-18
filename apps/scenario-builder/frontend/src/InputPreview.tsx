import { useEffect, useState } from "react";
import type { JsonValue, PreviewImage } from "./model";
import { isMapping } from "./model";
import { ReferencePreview } from "./ReferencePreview";

interface Roi {
  x: number;
  y: number;
  width: number;
  height: number;
}

function numeric(value: JsonValue | undefined): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function roiValues(value: JsonValue | undefined): Roi | null {
  if (!isMapping(value)) {
    return null;
  }
  const x = numeric(value.x);
  const y = numeric(value.y);
  const width = numeric(value.width);
  const height = numeric(value.height);
  if (x === null || y === null || width === null || height === null
      || width <= 0 || height <= 0) {
    return null;
  }
  return { x, y, width, height };
}

function PreviewFrame({
  image,
  roi,
  showRoi,
  large = false,
  onSize,
}: {
  image: PreviewImage;
  roi: Roi | null;
  showRoi: boolean;
  large?: boolean;
  onSize?: (width: number, height: number) => void;
}) {
  return (
    <div className={large ? "input-preview-frame zoomed" : "input-preview-frame"}>
      <img
        src={image.url}
        alt={`入力画像 ${image.name}`}
        draggable={false}
        onLoad={(event) => {
          onSize?.(
            event.currentTarget.naturalWidth,
            event.currentTarget.naturalHeight,
          );
        }}
      />
      {showRoi && roi ? (
        <div
          className="roi-overlay"
          style={{
            left: `${roi.x}%`,
            top: `${roi.y}%`,
            width: `${roi.width}%`,
            height: `${roi.height}%`,
          }}
        />
      ) : null}
    </div>
  );
}

export function DetectorPreview({
  detector,
  inputImage,
  referenceImages,
  onPickInputImage,
  onRequestReferenceImage,
}: {
  detector: JsonValue | undefined;
  inputImage?: PreviewImage | null;
  referenceImages?: Record<string, string>;
  onPickInputImage?: () => void;
  onRequestReferenceImage?: (reference: string) => void;
}) {
  const reference = isMapping(detector) && typeof detector.reference === "string"
    ? detector.reference
    : null;
  const roi = isMapping(detector) ? roiValues(detector.roi) : null;
  const hasRoi = isMapping(detector) && isMapping(detector.roi);
  const [showRoi, setShowRoi] = useState(true);
  const [zoomed, setZoomed] = useState(false);
  const [natural, setNatural] = useState<{ width: number; height: number } | null>(
    null,
  );
  const referenceUrl = reference ? referenceImages?.[reference] : undefined;

  useEffect(() => {
    setNatural(null);
  }, [inputImage?.url]);

  useEffect(() => {
    if (reference && !referenceUrl) {
      onRequestReferenceImage?.(reference);
    }
  }, [reference, referenceUrl, onRequestReferenceImage]);

  useEffect(() => {
    if (!zoomed) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setZoomed(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [zoomed]);

  const invalidRoi = hasRoi && roi === null;
  const outside = roi && natural
    ? roi.x < 0
      || roi.y < 0
      || roi.x + roi.width > natural.width
      || roi.y + roi.height > natural.height
    : false;
  const roiPercent = roi && natural
    ? {
        x: (roi.x / natural.width) * 100,
        y: (roi.y / natural.height) * 100,
        width: (roi.width / natural.width) * 100,
        height: (roi.height / natural.height) * 100,
      }
    : null;

  return (
    <section className="detector-preview">
      <div className="detector-preview-header">
        <div>
          <h3>入力画像プレビュー</h3>
          <span className="muted">
            {inputImage ? inputImage.name : "入力画像が選択されていません"}
          </span>
        </div>
        <div className="detector-preview-actions">
          {onPickInputImage ? (
            <button type="button" onClick={onPickInputImage}>
              {inputImage ? "入力画像を変更" : "入力画像を選択"}
            </button>
          ) : null}
          {inputImage ? (
            <button type="button" onClick={() => setZoomed(true)}>
              拡大
            </button>
          ) : null}
        </div>
      </div>

      {inputImage ? (
        <PreviewFrame
          image={inputImage}
          roi={roiPercent}
          showRoi={showRoi}
          onSize={(width, height) => setNatural({ width, height })}
        />
      ) : (
        <div className="input-preview-placeholder">
          入力画像を選択すると ROI を重ねて確認できます。
        </div>
      )}

      <div className="roi-toggle-row">
        <label>
          <input
            type="checkbox"
            checked={showRoi}
            onChange={(event) => setShowRoi(event.target.checked)}
          />
          ROI を表示
        </label>
        {!hasRoi ? <span className="muted">ROI 未設定（入力画像全体）</span> : null}
      </div>
      {invalidRoi ? (
        <p className="error-text">ROI の座標が不正です。</p>
      ) : null}
      {outside ? (
        <p className="error-text">
          ROI が入力画像の範囲を超えています。座標は自動で切り詰めていません。
        </p>
      ) : null}

      <ReferencePreview reference={reference} url={referenceUrl} />

      {zoomed && inputImage ? (
        <div
          className="preview-zoom-backdrop"
          onMouseDown={() => setZoomed(false)}
        >
          <div
            className="preview-zoom-dialog"
            role="dialog"
            aria-modal="true"
            aria-label="入力画像プレビュー"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="preview-zoom-header">
              <h2>入力画像プレビュー</h2>
              <button
                type="button"
                className="icon"
                title="閉じる"
                onClick={() => setZoomed(false)}
              >
                ×
              </button>
            </div>
            <PreviewFrame
              image={inputImage}
              roi={roiPercent}
              showRoi={showRoi}
              large
            />
          </div>
        </div>
      ) : null}
    </section>
  );
}
