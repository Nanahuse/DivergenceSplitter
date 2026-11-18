import type { EditorState, HostError, PreviewImage } from "./model";

interface WebView2Api {
  postMessage: (message: unknown) => void;
  addEventListener: (
    type: "message",
    listener: (event: { data: unknown }) => void,
  ) => void;
}

declare global {
  interface Window {
    chrome?: {
      webview?: WebView2Api;
    };
  }
}

export function isWebViewHost(): boolean {
  return Boolean(window.chrome?.webview);
}

export function sendToHost(message: unknown): void {
  window.chrome?.webview?.postMessage(message);
}

export function sendCommand(command: Record<string, unknown>): void {
  sendToHost({ type: "command", command });
}

export function listenToHost(
  onState: (state: EditorState) => void,
  onError: (error: HostError) => void,
  onAssetAdded?: (asset: string) => void,
  onInputImage?: (image: PreviewImage) => void,
  onReferenceImage?: (reference: string, url: string) => void,
): () => void {
  const webview = window.chrome?.webview;
  if (!webview) {
    return () => undefined;
  }
  const listener = (event: { data: unknown }) => {
    if (typeof event.data !== "object" || event.data === null) {
      return;
    }
    const message = event.data as { type?: string };
    if (message.type === "state") {
      onState(event.data as EditorState);
    } else if (message.type === "error") {
      onError(event.data as HostError);
    } else if (message.type === "assetAdded") {
      const asset = (event.data as { asset?: string }).asset;
      if (typeof asset === "string") {
        onAssetAdded?.(asset);
      }
    } else if (message.type === "inputImage") {
      const image = event.data as Partial<PreviewImage>;
      if (typeof image.url === "string" && typeof image.name === "string") {
        onInputImage?.({
          name: image.name,
          path: typeof image.path === "string" ? image.path : undefined,
          url: image.url,
        });
      }
    } else if (message.type === "referenceImage") {
      const payload = event.data as { reference?: string; url?: string };
      if (typeof payload.reference === "string" && typeof payload.url === "string") {
        onReferenceImage?.(payload.reference, payload.url);
      }
    }
  };
  webview.addEventListener("message", listener);
  return () => undefined;
}
