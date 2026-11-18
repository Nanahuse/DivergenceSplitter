import type { EditorState, HostError, PreviewImage } from "./model";

type MessageListener = (event: { data: unknown }) => void;

interface WebView2Api {
  postMessage: (message: unknown) => void;
  addEventListener: (type: "message", listener: MessageListener) => void;
  removeEventListener: (type: "message", listener: MessageListener) => void;
}

type HostRequest =
  | {
      type: "ready" | "new" | "open" | "save" | "saveAs" | "openWorkspace"
        | "addAsset" | "pickInputImage";
    }
  | { type: "openScenario"; name: string }
  | { type: "loadReferenceImage"; reference: string }
  | { type: "command"; command: Record<string, unknown> };

interface HostListeners {
  onState: (state: EditorState) => void;
  onError: (error: HostError) => void;
  onAssetAdded: (asset: string) => void;
  onInputImage: (image: PreviewImage) => void;
  onReferenceImage: (reference: string, url: string) => void;
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

export function sendToHost(message: HostRequest): void {
  window.chrome?.webview?.postMessage(message);
}

export function sendCommand(command: Record<string, unknown>): void {
  sendToHost({ type: "command", command });
}

export function listenToHost(listeners: HostListeners): () => void {
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
      listeners.onState(event.data as EditorState);
    } else if (message.type === "error") {
      listeners.onError(event.data as HostError);
    } else if (message.type === "assetAdded") {
      const asset = (event.data as { asset?: string }).asset;
      if (typeof asset === "string") {
        listeners.onAssetAdded(asset);
      }
    } else if (message.type === "inputImage") {
      const image = event.data as Partial<PreviewImage>;
      if (typeof image.url === "string" && typeof image.name === "string") {
        listeners.onInputImage({
          name: image.name,
          path: typeof image.path === "string" ? image.path : undefined,
          url: image.url,
        });
      }
    } else if (message.type === "referenceImage") {
      const payload = event.data as { reference?: string; url?: string };
      if (typeof payload.reference === "string" && typeof payload.url === "string") {
        listeners.onReferenceImage(payload.reference, payload.url);
      }
    }
  };
  webview.addEventListener("message", listener);
  return () => webview.removeEventListener("message", listener);
}
