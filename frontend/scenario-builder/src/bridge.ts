import type { EditorState, HostError } from "./model";

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
    }
  };
  webview.addEventListener("message", listener);
  return () => undefined;
}
