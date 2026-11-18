import assert from "node:assert/strict";
import test from "node:test";
import { listenToHost } from "../src/bridge.ts";

function webviewMessages(t) {
  const webview = new EventTarget();
  const previousWindow = globalThis.window;
  globalThis.window = { chrome: { webview } };
  t.after(() => {
    if (previousWindow === undefined) {
      delete globalThis.window;
    } else {
      globalThis.window = previousWindow;
    }
  });
  return (data) => webview.dispatchEvent(new MessageEvent("message", { data }));
}

function editorMessages(received) {
  return {
    onState: (state) => received.push(["state", state]),
    onError: (error) => received.push(["error", error]),
    onAssetAdded: (asset) => received.push(["asset", asset]),
    onInputImage: (image) => received.push(["input", image]),
    onReferenceImage: (reference, url) => received.push(["reference", reference, url]),
  };
}

test("only the mounted editor receives WebView messages after a remount", (t) => {
  const send = webviewMessages(t);
  const firstMessages = [];
  const currentMessages = [];
  const firstDetach = listenToHost(editorMessages(firstMessages));
  const initialState = { type: "state", version: 1 };
  send(initialState);
  firstDetach();

  const detach = listenToHost(editorMessages(currentMessages));
  const state = { type: "state", version: 2 };
  const asset = "Asset/start.png";
  send(state);
  send({ type: "assetAdded", asset });
  detach();
  send({ type: "state", version: 3 });

  assert.deepEqual(firstMessages, [["state", initialState]]);
  assert.deepEqual(currentMessages, [["state", state], ["asset", asset]]);
});

test("preview messages reach the matching callback when their data is usable", (t) => {
  const send = webviewMessages(t);
  const received = [];
  const detach = listenToHost(editorMessages(received));
  t.after(detach);

  send({ type: "inputImage", name: "missing.png" });
  send({ type: "referenceImage", url: "https://app.local/reference.png" });
  const image = { name: "input.png", path: "Asset/input.png", url: "https://app.local/input.png" };
  send({ type: "inputImage", ...image });
  send({ type: "referenceImage", reference: "Asset/start.png", url: "https://app.local/start.png" });

  assert.deepEqual(received, [
    ["input", image],
    ["reference", "Asset/start.png", "https://app.local/start.png"],
  ]);
});
