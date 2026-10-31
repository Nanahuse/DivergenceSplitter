# Getting started

[日本語（正本）](getting-started.md) | [English](getting-started.en.md)

[Documentation home](../README.en.md)

This walkthrough uses a time-based scenario so that you can check the connection
before tuning image detection. With this scenario, LiveSplit starts after two
seconds of start-condition evaluation. Its first segment completes three seconds
after that segment begins evaluation. Keep a working video input active throughout
the test.

## Download and launch

1. Open the repository's [C++23 Actions workflow](https://github.com/Nanahuse/DivergenceSplitter/actions/workflows/cpp23.yml).
   Select a successful trusted run for the revision you intend to use and download
   the `DivergenceSplitter-cpp23-windows-x64` artifact. GitHub artifact downloads
   require sign-in. Availability depends on a successful NDI-enabled job and
   artifact retention; if no artifact is available, [build from source](development/building.en.md).
2. Extract the artifact, then extract the application ZIP inside it into a writable
   local directory. Keep the DLLs, plugin directories, and license files together.
   The official ZIP includes the NDI runtime; installing the SDK is unnecessary.
3. Run `DivergenceSplitter.exe`. A fresh installation has no active input. If the
   profile remembered from the previous session still exists, the application
   opens and applies it at startup.
   That profile's scenario may start controlling LiveSplit as soon as input and
   Bridge are ready.

## Connect LiveSplit.Bridge

1. Install LiveSplit and a LiveSplit.Bridge release supporting Protocol v4.
   Follow the [Bridge installation instructions](https://github.com/Nanahuse/LiveSplit.Bridge#インストール):
   close LiveSplit, copy `LiveSplit.Bridge.dll` from its release ZIP into LiveSplit's
   `Components` directory, reopen LiveSplit, then add **Control > LiveSplit Bridge**
   in **Edit Layout...** and save the layout.
2. Open the Bridge component's settings. Leave its WebSocket port at `54000` and
   check that its status is **Running**. DivergenceSplitter connects on the same PC.
3. In LiveSplit, create a test run with **one segment**, save it, and leave the timer
   stopped. Use a test run because the next steps send real timer controls.

## Configure a working input and scenario

1. Download [minimal-scenario.yaml](../examples/minimal-scenario.yaml) from this
   revision and save it to a known local path, for example
   `C:/DivergenceSplitter/minimal-scenario.yaml`.
2. Open **Profile**. Choose one input:
   - **Camera**: click **Detect cameras**, select your camera or capture card, and
     select an enumerated mode. Leave **Request 60 fps** off for this test.
   - **Video file**: browse to a playable local recording longer than ten seconds.
     Codec support depends on the build. An AVI recording with MJPEG is useful for
     a first check. It also plays in the draft preview; Apply restarts playback
     from the beginning.
   - **NDI®**: start your sender, click **Search again**, and select its advertised
     name. This requires an NDI-enabled build.
3. Leave **Crop margins** and **Resize** unchecked. Click **Add instance**, enter
   Bridge port `54000`, select the row, and use **Browse scenario...** to choose the
   saved YAML. Remove extra rows for this test.
4. Enable **Preview input** under **Draft input preview**. Check the image,
   input dimensions, received FPS, and output dimensions. If a Session is active,
   click **Stop Session and preview draft** first. This preview does not evaluate
   scenarios or control LiveSplit. Fix input errors before continuing; see
   [draft preview](user-guide.en.md#draft-input-preview).
5. Click **Apply**. Input and scenario evaluation start immediately; Apply does
   not require a separate Start command in the application.

## Observe the first automatic split

1. Open **Monitor**. Check that the preview updates, the frame count increases,
   and the instance becomes **Ready**.
2. LiveSplit starts after approximately two seconds of available evaluation.
   After approximately three more seconds, the first split completes and the
   one-segment test run ends. Timing depends on frame delivery and Bridge readiness;
   these waits are not measured from the mouse click on Apply.
3. Open **Diagnostics** to inspect Start, Splits, condition statuses, and scores.
   The sample uses `elapsed`, so no reference image or score threshold is needed.
4. Use **File > Save Profile As...** to save the configured profile. Saving and
   applying are separate operations; see the [user guide](user-guide.en.md).

The sample starts again after a timer reset when frames continue arriving. Close
the application when finished testing. For game-specific behavior, replace the
sample with [image detection examples](scenarios/examples.en.md). For errors, start
with [troubleshooting](troubleshooting.en.md).
