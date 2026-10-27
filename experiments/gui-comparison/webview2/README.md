# Qt Widgets / WebView2の比較構成

PR #153の共通C++23 mockを使うWindows専用の比較試作。製品移植、Bridge v4クライアント、NDI、実Scenario判定、OpenCV更新は対象外。

```
Qt Widgets / Model-View ─ Qt adapter ─────┐
                                         ├─ standard C++23 common/mock.hpp
React / TypeScript / CSS ─ Win32 WebView2 ─┘
```

CoreにQt、WebView2、COM、JSON、TS、OpenCV型は公開しない。画像処理は既存の共通support層。WebView2へQt Network/WebSocketsを導入せず、Bridge通信ライブラリの評価はGUI選定と分離する。

## ホストの小規模比較

`tools/probe_webview_host.ps1`は固定`webview/webview 0.12.0`公開ヘッダーをSHA256照合してbuild配下へ取得する使い捨てprobe。GUI本体・配布には含めない。

| 確認 | ラッパー | 直接SDK |
| --- | --- | --- |
| Window / 仮想ホスト / 双方向通信 / reload | probeで確認 | GUI契約で確認 |
| native controller | `browser_controller()`で取得 | 直接所有 |
| ProcessFailed / Environment5 | QIとhandler登録を確認 | 実際のRenderer/Browser終了を注入して復旧 |
| UDF・factory・controller再生成 | probeでは未実装 | 本体で管理 |

**直接SDKを採用**。ラッパーのAPI不足という結論ではない。Windows専用の今回の構成では、独自UDF、非同期factory、origin制限、environment/controllerの破棄・再生成を明示して所有する方を選んだ。ラッパーで同等の障害復旧まで作った保守性比較はしていない。二方式の本実装を維持しない。

vcpkg baselineは既存の`9e593bb18ea69cc5095e012465dcd675a822ed0d`。SDK `1.0.3800.47`、nlohmann-json `3.12.0#2`、OpenCV `4.12.0#7[contrib]`。Windows x64 / MSVC / Release。React、TS、Zod、Vite、Vitestはpackage-lockで固定し`npm ci`で構築する。初版のnpm依存は監査後に修正版へ更新した。

## 通信契約 v1

commandは`{version:1, epoch, id, command, args}`、responseは`{version:1,type:"response",epoch,id,ok,result,error}`。未知コマンド、古いepoch、不正な型・過大要求はnativeで拒否する。Core validationはApply結果の`errors`として返す。任意のnative関数名・任意スクリプトを実行するAPIは公開しない。

Snapshotはsequence、revision、running、resets、applied profile、Monitor roots、metrics、必要時だけのtopology、最新JPEG、参照JPEG。64-bit ID/sequenceは10進文字列。request ID/epochはJS安全整数範囲。`protocol.cpp`と`contracts.ts`の型を手で維持し、境界テストを併設する。この二重管理は保守コストに含める。

`ready`はepoch=0から開始し、nativeが現在documentのepochとdraftを返す。navigationでepochを進め古いackを無効化。worker、applied profile、Reset数をWebViewと別に所有し、reload・Renderer再起動・Browser再生成でも維持する。一時的に無効なdraftもApplyせず保持できる。

未確認Snapshotは最大1件。React commit、画像decode、animation frame（background時250ms fallback）のack後、次のtimerでCoreの最新値を読む。古いフレーム・状態を蓄積しない。未応答commandは最大32件。JPEG quality=80をJSON/base64で渡し、共有bufferは追加しない。

## 画面・状態・画像

- Monitor: 複数Scenarioカード、applied設定、最新JPEG。入力60Hz、共通PreviewCadenceで送信を15Hzへ制限。Windows timerを8msでpollし、動作中だけ1msのtimer resolutionを要求する。ackは実画面scanoutの証明ではない。
- Diagnostics: revisionでID indexを更新。値更新はmetricsだけを交換し、階層を再生成しない。固定32px行とviewport前後4行だけをDOMへ置く。生存IDの展開、先頭ID＋相対pxのscroll anchorを維持。アンカー削除時は近い生存行へ移る。
- 参照画像: 展開Detectorの最大16個を下部へ表示。collapse、ページ離脱、削除、document破棄でnative cacheとReact画像参照を解放。16超の同時表示は未実装で、Qtとの完全同等とは扱わない。
- Configuration: React draftを編集してnativeにも保持し、TSとCoreで検証。Source/file、Scenario追加・削除、name/port/enabled/note。native dialogはpostしたWindow messageから表示し、WebMessageのCOM callbackをmodal dialogで塞がない。
- Reset: 共通ResetHold。pointer up/cancel、focus loss、ページ移動、停止、最小化、破棄でcancel。2秒holdで一度だけ発火。

## セキュリティ・寿命・Runtime

配布`bin/ui`を`https://comparison.local`へ仮想ホストmappingし、HTTP serverを起動しない。navigationとWebMessage Sourceは`https://comparison.local/index.html`への完全一致。popup、permission、host objects、default dialogs/context menuを無効化し、CSPで外部script/connect/frameを禁止。DevToolsはself-testまたは明示した`GUI_WEBVIEW2_DEVTOOLS`環境変数で有効化する。

Renderer終了/応答停止はreload、Browser終了はBrowserProcessExited後にcontroller再生成。復旧は最大3回で打ち切り失敗をレポート。ack timeoutもreload対象。最小化中は送信停止。closing/generationを確認し、handler解除後にcontrollerをCloseする。

UDFは`%LOCALAPPDATA%/DivergenceSplitter/gui-comparison-webview2/<PID>`。ZIP外に置き他アプリ・実行と分離する。通常終了は自身のBrowserProcessExitedを最大5秒待ち、終了確認したPIDディレクトリだけを削除。通知がない場合やhost強制終了時は残す。実パスとcleanup結果は`*.webview2.json`。残存cacheの自動回収・容量制限は未実装。

Evergreen Runtimeを起動時に検出し、未導入なら公式導入先を表示して終了する。自動download/installはしない。RuntimeをZIPへ含めないため、アプリ容量と実行環境全体の負担を分ける。

## 再現と試験

Developer PowerShell、Node.js、固定vcpkgを用意してrootから実行する。以前の出力は上書きしない。

```powershell
tools/build_gui_comparison.ps1 -Candidate webview2
tools/gui_dev_shell.ps1 -Script tools/probe_webview_host.ps1
```

CMakeがnpm ci、TS検査、Vite静的buildを実行。CTestはCore、C++ JSON契約、TS単体、small/large DOM GUI契約、Diagnostics/Configuration capture、hold中終了を実行する。GUI契約は実DOM handlerを操作し、実native dialogを取消する。RendererはPage.crash、Browserはhostが取得した自身のBrowser PIDだけを終了させる。self-test以外に故障注入UIは公開しない。

配布ツールはWebView2Loader、assets、MSVC/OpenCV、vcpkg/npm noticesを検証。開発PATH除去後のinstalled smallと別フォルダーへのZIP展開largeで契約を再実行する。通常CIはWebView2と変更したWidgets C。既存42ケース・30分試験・Qt Quick測定を繰り返さない。

任意のプロセス全体telemetryはpsutil 7.1.3を使用する。

```powershell
.venv/Scripts/python.exe tools/measure_gui_process_tree.py dist/gui-comparison/webview2/bin/comparison-webview2.exe build/webview2-monitor-small --seconds 20
```

CPUはhost＋子孫の最終観測値を保持。private bytesとRSS合計を分離する。RSSの共有ページ二重計上、短命processの取りこぼしがある。desktop負荷・前景・遮蔽を統制しない値から性能順位を決めない。GPU、実scanout、物理IME、モニター間DPI、ファイル確定は別の未検証項目。

## 一次資料

- [仮想ホストとローカルコンテンツ](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/working-with-local-content)
- [origin確認とセキュリティ](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/security)
- [ProcessFailed / BrowserProcessExited](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/process-related-events)
- [Runtime検出と配布](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution)
- [webview 0.12.0公開ヘッダー](https://github.com/webview/webview/blob/0.12.0/core/include/webview/webview.h)
