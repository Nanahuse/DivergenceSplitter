import assert from "node:assert/strict";
import test from "node:test";
import { listenToHost } from "../src/bridge.ts";

test("remounting the editor leaves one WebView message listener", (t) => {
  const active = new Set();
  const previousWindow = globalThis.window;
  globalThis.window = {
    chrome: {
      webview: {
        addEventListener(type, listener) {
          assert.equal(type, "message");
          active.add(listener);
        },
        removeEventListener(type, listener) {
          assert.equal(type, "message");
          active.delete(listener);
        },
      },
    },
  };
  t.after(() => {
    if (previousWindow === undefined) {
      delete globalThis.window;
    } else {
      globalThis.window = previousWindow;
    }
  });

  const received = [];
  const callbacks = {
    onState: (state) => received.push(state),
    onError: (error) => received.push(error),
    onAssetAdded: (asset) => received.push(asset),
    onInputImage: (image) => received.push(image),
    onReferenceImage: (reference, url) => received.push({ reference, url }),
  };
  const firstDetach = listenToHost(callbacks);
  firstDetach();
  const detach = listenToHost(callbacks);

  const state = { type: "state", version: 3 };
  const asset = "Asset/start.png";
  for (const listener of active) {
    listener({ data: state });
    listener({ data: { type: "assetAdded", asset } });
  }
  assert.deepEqual(received, [state, asset]);

  detach();
  assert.equal(active.size, 0);
});
