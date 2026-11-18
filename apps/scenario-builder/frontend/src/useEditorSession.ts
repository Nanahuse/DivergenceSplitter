import { useCallback, useEffect, useRef, useState } from "react";
import { isWebViewHost, listenToHost, sendCommand, sendToHost } from "./bridge";
import {
  emptyDemoState,
  type DefinitionKind,
  type EditorState,
  type Path,
  type PreviewImage,
} from "./model";
import {
  adjustSelectionForSplitMutation,
  inverseSplitMutation,
  selectionPath,
  splitMutationForCommand,
  type Selection,
  type SplitMutation,
} from "./selection";

type PendingCommand =
  | { action: "command"; mutation: SplitMutation | null }
  | { action: "undo" | "redo" };

type PendingRename = {
  kind: "condition-definition" | "detector-definition";
  to: string;
};

interface EditorSelection {
  selection: Selection;
  selectedPath: Path | null;
}

export function useEditorSession() {
  const preview = !isWebViewHost();
  const [state, setState] = useState<EditorState | null>(() =>
    preview ? emptyDemoState() : null,
  );
  const [error, setError] = useState<string | null>(null);
  const [inputImage, setInputImage] = useState<PreviewImage | null>(null);
  const [referenceImages, setReferenceImages] = useState<Record<string, string>>({});
  const [location, setLocation] = useState<EditorSelection>({
    selection: null,
    selectedPath: null,
  });
  const locationRef = useRef(location);
  const pendingAsset = useRef<((asset: string) => void) | null>(null);
  const pendingRename = useRef<PendingRename | null>(null);
  const pendingCommands = useRef<PendingCommand[]>([]);
  const undoHistory = useRef<(SplitMutation | null)[]>([]);
  const redoHistory = useRef<(SplitMutation | null)[]>([]);

  const select = useCallback((selection: Selection, selectedPath = selectionPath(selection)) => {
    const next = { selection, selectedPath };
    locationRef.current = next;
    setLocation(next);
  }, []);

  const selectPath = useCallback((path: Path) => {
    select(locationRef.current.selection, path);
  }, [select]);

  useEffect(() => {
    const detach = listenToHost({
      onState(nextState) {
        const pending = pendingCommands.current.shift();
        let mutation: SplitMutation | null | undefined;
        if (pending?.action === "command") {
          mutation = pending.mutation;
          undoHistory.current.push(mutation);
          redoHistory.current = [];
        } else if (pending?.action === "undo") {
          const entry = undoHistory.current.pop();
          if (entry !== undefined) {
            redoHistory.current.push(entry);
            mutation = entry && inverseSplitMutation(entry);
          }
        } else if (pending?.action === "redo") {
          mutation = redoHistory.current.pop();
          if (mutation !== undefined) {
            undoHistory.current.push(mutation);
          }
        }

        if (mutation) {
          const current = locationRef.current;
          const next = adjustSelectionForSplitMutation(
            current.selection,
            current.selectedPath,
            mutation,
            nextState.document.splits.length,
          );
          if (next.selection !== current.selection || next.selectedPath !== current.selectedPath) {
            select(next.selection, next.selectedPath);
          }
        }
        if (!nextState.canUndo && !nextState.canRedo && pendingCommands.current.length === 0) {
          undoHistory.current = [];
          redoHistory.current = [];
        }

        const rename = pendingRename.current;
        if (rename) {
          const definitions = rename.kind === "condition-definition"
            ? nextState.document.definitions.conditions
            : nextState.document.definitions.detectors;
          if (definitions.some((definition) => definition.name === rename.to)) {
            pendingRename.current = null;
            select({ kind: rename.kind, name: rename.to });
          }
        }
        setState(nextState);
        setError(null);
      },
      onError(hostError) {
        pendingAsset.current = null;
        pendingRename.current = null;
        pendingCommands.current.shift();
        setError(hostError.message);
      },
      onAssetAdded(asset) {
        const apply = pendingAsset.current;
        pendingAsset.current = null;
        apply?.(asset);
      },
      onInputImage: setInputImage,
      onReferenceImage(reference, url) {
        setReferenceImages((images) => ({ ...images, [reference]: url }));
      },
    });
    sendToHost({ type: "ready" });
    return detach;
  }, [select]);

  const workspaceRoot = state?.workspace?.root ?? null;
  useEffect(() => {
    setInputImage(null);
    setReferenceImages({});
  }, [workspaceRoot]);

  const { selection, selectedPath } = location;
  const splits = state?.document.splits;
  useEffect(() => {
    if (!splits || !selection) {
      return;
    }
    if (selection.kind === "split" && selection.index >= splits.length) {
      select(null);
    } else if (selection.kind === "rule" && !splits[selection.split]?.rules[selection.rule]) {
      select(null);
    } else if (selection.kind === "sequence-rule"
        && !splits[selection.split]?.rules[selection.rule]?.sequence?.[selection.step]) {
      select(null);
    }
  }, [select, selection, splits]);

  const runCommand = useCallback((command: Record<string, unknown>) => {
    if (preview) {
      return;
    }
    const action = command.type;
    pendingCommands.current.push(action === "undo" || action === "redo"
      ? { action }
      : { action: "command", mutation: splitMutationForCommand(command) });
    sendCommand(command);
  }, [preview]);

  const requestRenameDefinition = useCallback((kind: DefinitionKind, from: string, to: string) => {
    if (preview || from === to) {
      return;
    }
    pendingRename.current = {
      kind: kind === "condition" ? "condition-definition" : "detector-definition",
      to,
    };
    runCommand({
      type: kind === "condition" ? "rename_condition_definition" : "rename_detector_definition",
      from,
      to,
    });
  }, [preview, runCommand]);

  const addAsset = useCallback((apply: (asset: string) => void) => {
    if (!preview) {
      pendingAsset.current = apply;
      sendToHost({ type: "addAsset" });
    }
  }, [preview]);

  const pickInputImage = useCallback(() => {
    if (!preview) {
      sendToHost({ type: "pickInputImage" });
    }
  }, [preview]);

  const requestReferenceImage = useCallback((reference: string) => {
    if (!preview && reference) {
      sendToHost({ type: "loadReferenceImage", reference });
    }
  }, [preview]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey)) {
        return;
      }
      const key = event.key.toLowerCase();
      if (key === "z" && !event.shiftKey) {
        event.preventDefault();
        runCommand({ type: "undo" });
      } else if (key === "y" || (key === "z" && event.shiftKey)) {
        event.preventDefault();
        runCommand({ type: "redo" });
      } else if (key === "s") {
        event.preventDefault();
        sendToHost({ type: event.shiftKey ? "saveAs" : "save" });
      } else if (key === "o") {
        event.preventDefault();
        sendToHost({ type: "open" });
      } else if (key === "n") {
        event.preventDefault();
        sendToHost({ type: "new" });
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [runCommand]);

  return {
    state,
    preview,
    error,
    clearError: () => setError(null),
    selection,
    selectedPath,
    select,
    selectPath,
    runCommand,
    requestRenameDefinition,
    addAsset,
    inputImage,
    referenceImages,
    pickInputImage,
    requestReferenceImage,
  };
}
