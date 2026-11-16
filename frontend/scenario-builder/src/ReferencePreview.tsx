export function ReferencePreview({
  reference,
  url,
}: {
  reference: string | null;
  url?: string;
}) {
  if (!reference) {
    return null;
  }
  const name = reference.replace(/^Asset\//, "");
  return (
    <div className="reference-preview">
      <div className="reference-preview-title" title={reference}>
        参照画像: {name}
      </div>
      {url ? (
        <img src={url} alt={`参照画像 ${name}`} />
      ) : (
        <div className="reference-preview-placeholder">読み込み中...</div>
      )}
    </div>
  );
}
