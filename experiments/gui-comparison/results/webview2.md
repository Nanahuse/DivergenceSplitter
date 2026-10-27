# Qt Widgets / WebView2：共通mockと保守性の比較

今回の範囲では **Qt Widgetsを推奨する**。WebView2もMonitor、JPEG Preview、10,220ノードのDiagnostics、設定編集、ZIP配布まで実現できた。一方、同じ小変更でConfigurationが大幅に簡潔になる証拠は得られず、C++/TSの契約、受領確認、仮想階層、ブラウザーの寿命管理を追加で維持する負担が残った。ZIPの小ささを主な選定理由にはしない。製品GUIの移植・mainへのmergeは行わない。

これは実装からの判断で、将来の全仕様変更に対する一般的な優劣の証明ではない。複雑なフォームが主役になる場合、Reactの再利用やWebの表示部品が有利になる余地はある。

## 条件と構成

Qtは既存Widgets Cを再利用し、WebView2はWin32 SDK直接利用＋React/TypeScript/CSSを追加。Coreは標準C++23のまま。OpenCV `4.12.0#7[contrib]`、baseline、MSVC x64、Release、60Hz入力、同じ84/10,220ノード、DEFLATE level 6を共通条件にした。Qt Quick/wx/ImGuiの既存測定を上書き・再実施していない。

`webview/webview 0.12.0`でもWindow、仮想ホスト、双方向bind、reload、native controller、ProcessFailed/Environment5のAPI取得を確認した。必要APIの不足を理由には除外していない。Windows専用のUDF/factory/障害復旧の所有を明示するため直接SDKを選び、ラッパー版のGUIは並行維持しない。[構成・契約・再現手順](../webview2/README.md)を参照。

## 同じ仕様変更

変更前`dbdaf8f`から、独立commit **`6d28196`**で両方にScenario noteを追加した。上限120 UTF-8 bytes、draft/Apply、Discard、Monitorカード、Diagnosticsラベル、Core検証とGUI契約まで同じ変更を適用。依存監査の更新とSDK基盤修正は前の別commitへ分けた。

```powershell
git diff dbdaf8f 6d28196 -- experiments/gui-comparison
```

| 観点 | Qt Widgets | WebView2 / React |
| --- | --- | --- |
| 共通Core | Profile/Nodeのnote、validation、共通契約を追加 | 同じ変更を共有 |
| 設定表示 | 既存tableに列、itemChanged、sync_formを追加 | controlled inputをJSXへ追加しdraftをspreadで更新 |
| Monitor/Diagnostics | 既存ラベル更新にnoteを追加 | JSXとNode schemaへnoteを追加 |
| 型・検証 | C++型とCore validation。列番号・QString変換はadapterに残る | C++ JSON encode/decodeとTS schema、フォームvalidationを両方更新 |
| 状態 | ProfileEditorと既存Model/View | React draft＋native draft＋applied snapshot。epoch/response/ackとも整合させる |
| テスト修正 | 共通GUI valid_draftでtable itemを編集 | 同じGUI valid_draftでDOM入力。UTF-8フォームvalidationとJSON往復の確認も追加 |
| ビルド | C++再コンパイル | C++再コンパイルとTS検査・Vite build |

Qt adapterは1ファイル（10行追加/6行削除）。Webはhostの試験opt-in 1行に加え、JSON codec、TS schema、フォーム、関連テストに分散した。全commitは13ファイル・69行追加/20行削除で、共通Core/試験も含む。行数の大小だけで採否は決めない。変更前の実装時間や開発者間の生産性差は計測していない。

Webは無効なdraftをreload後も編集できるよう、wire schemaとApply時validationを分離した。これは保守性比較中に実際に必要になった追加判断。Qtにもtable列番号と同期フラグの手管理があり、Qtの独自コードがゼロという評価ではない。

## Diagnosticsと追加基盤

Webは32px固定行、viewport前後4行の独自virtualizer。構造revision時にID indexを作り直し、値更新では再構築しない。展開IDを生存ノードへ絞り、先頭ID＋相対pxのscroll anchorを復元する。削除されたanchorの近傍復元は単体試験、実GUIでは値更新中のscroll/展開保持と動的Detector削除・画像解放を確認した。構造変更時のanchorを物理スクロールで検証したわけではない。

large GUI契約のDOM行数は最大18。QtはQTreeViewがviewport、展開、入力処理を提供するが、安定ID→item管理、差分追加・削除、参照画像の寿命は既存adapterが管理する。Webはこれに加えて行範囲、flatten、anchor、React/native cacheの所有を維持する。

参照画像の同時表示はWeb側で16個に制限した。collapse・非表示・削除時の解放は確認したが、16超を含む完全な機能同等は未達。これを無条件のWeb性能上の優位として扱わない。

通信はversion/epoch/request IDを検証し、64-bit IDを文字列で扱う。最新JPEG/Snapshotは未確認1件に制限し、React commit・decode後にackする。reloadでもCoreの状態を維持。Renderer終了はreload、Browser終了は自分のBrowserProcessExited後にcontrollerを再生成し、再試行を最大3回に制限する。この固有の寿命管理が長期保守の追加対象になる。

## 機能・配布の確認

| 確認 | 結果 |
| --- | --- |
| 共通Core / JSON boundary / TypeScript | Core CTest、JSON CTest、TS 5試験に成功 |
| Qt Widgets note変更 | ローカルCTest 6件、installed small / ZIP largeに成功 |
| WebView2 small/large | ローカルCTest 8件、installed small / ZIP largeに成功 |
| GUI操作 | 実DOM/native control、実ファイル選択取消、実未保存確認取消、hold cancel/一度だけ発火 |
| Diagnostics | 値更新時の展開/scroll保持、構造追加・削除、生存展開、画像解放、DOM行数制限 |
| reload / Renderer / Browser | 実際の故障注入とCore状態保持に成功 |
| 静的配布 | HTTP serverなし、virtual host mapping、開発PATH除去後に起動 |
| UDF | LocalAppData/PIDへ分離。Browser終了確認後の削除をレポートで確認 |
| 依存監査 | 固定依存を修正版へ更新し、npm auditで0件を確認（記録時点） |

[source `79d600c`のWindows CI](https://github.com/Nanahuse/DivergenceSplitter/actions/runs/40480148118)はWebView2とWidgets Cの両jobに成功。各jobの配布ツール49試験、CTest、installed/ZIP契約を確認した。[通常CI](https://github.com/Nanahuse/DivergenceSplitter/actions/runs/40480148196)も成功。[CI情報](webview2/ci-evidence.json)と[ローカル生データ](webview2/local)を保存した。起動時dark指定の後続修正は`bf352fc`で、性能測定sourceとは分ける。

初回`6d28196`のGUI CIも成功したが、通常CIはPython formatで失敗した。`79d600c`で修正して成功を確認。短時間captureの白画面は終了がready前だったため、描画済みprobeを待つ修正で解消し、保存PNGも確認した。`--dark`の初期反映漏れも画面確認で修正した。未描画のcaptureを機能合格の証拠として残さない。

## 配布容量

以下はsource `79d600c`の値。起動時theme修正後の最新配布物はCI artifactで別途確認する。容量はMB=1,000,000 bytes。

| 候補 | ローカル展開後 bytes | ローカルZIP bytes | Windows CI展開後 bytes | Windows CI ZIP bytes | CI外側artifact bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Qt Widgets C + note | 45,210,105 | 17,562,887 | 45,207,140 | 17,555,568 | 17,914,278 |
| WebView2 + note | 16,502,698 | 5,841,869 | 16,501,831 | 5,841,730 | 6,104,413 |

WebView2のZIPはRuntimeを含まない。Evergreenの導入確認を起動時に行い、不在時は公式導入先を示して終了する。アプリZIPとRuntime全体の負担を混同しない。React/Zod等の通知、静的assets・source map、MSVC/OpenCVを含む。Qt Cの過去17.55MB実績は元の記録に保持した。

同じversion/feature/Release条件でもローカルとCIのSDK・依存バイナリ、metadata、ZIP hashは一致しない。byte再現性は主張しない。ローカルのWeb用依存導入は既存binary cacheが使われず約21分、うちOpenCV約12分だった。WebView2固有のbuild時間として扱わない。CIはWeb18/Qt28 packageをcache復元した。

起動時theme修正後の**source `bf352fc`**も[Windows GUI CI](https://github.com/Nanahuse/DivergenceSplitter/actions/runs/40481002156)と[通常CI](https://github.com/Nanahuse/DivergenceSplitter/actions/runs/40481002119)に成功した。[別記録](webview2/theme-ci-evidence.json)のWebは展開後16,502,805 / ZIP **5,841,982** bytes、Qt Cは45,207,140 / **17,555,570** bytes。Webの[配布artifact](https://github.com/Nanahuse/DivergenceSplitter/actions/runs/40481002156/artifacts/12723008265)は外側6,105,498 bytes、[Qt artifact](https://github.com/Nanahuse/DivergenceSplitter/actions/runs/40481002156/artifacts/12722568597)は17,914,668 bytes。上表の測定sourceや外側artifactとは区別する。

## 代表的な機能telemetry

source `79d600c`、Runtime `155.0.4283.62`。旧42ケースや30分試験を再実施せず、WebのMonitor/Diagnostics・small/largeを各5秒warmup＋20秒だけ記録した。[生データと集計](webview2/telemetry-summary.json)。

| ケース | Preview decode ack | 生成→decode確認 p95 | 観測process数 | private bytes合計peak |
| --- | ---: | ---: | ---: | ---: |
| Monitor small | 300 | 32.98ms | 7 | 699.65MB |
| Monitor large | 300 | 40.39ms | 7 | 746.75MB |
| Diagnostics small | 対象外 | 対象外 | 7 | 240.92MB |
| Diagnostics large | 対象外 | 対象外 | 7 | 315.62MB |

Monitorは要求20秒の区間に300枚を受領し15Hz相当。Sessionのmeasurement_secondsはBrowser終了待ち約0.36秒も含むため、単純除算では14.7Hzになる。これは画面scanoutの実測ではない。Diagnosticsは両規模ともtopology build 1回・参照生成1回に対してvalue update 340回で、値更新時に階層/画像を再構築していないことをカウンターで確認した。

最初の67ms Win32 timerでは約12Hzだった。timerの丸めを避けるため、動作中だけ1ms resolutionを要求し、8ms poll＋共通PreviewCadenceへ修正した。producerはlatest-onlyのままで、キューを増やして補償していない。

CPU・private/RSSはhost＋全子孫processを記録した。privateはprivate commitの合計で、物理resident全体やGPUメモリの値ではない。RSS単純合計には共有ページの二重計上がある。desktop負荷・遮蔽は未統制で、small Monitorは別GUI契約と一部重複するため、これらのCPU/メモリからQtとの性能順位を決めない。初回/再起動の統制比較、GPU、実scanout、物理操作応答は未測定。

## 採用判断と残る範囲

長期保守とUI変更を最重視すると、今回の小規模変更ではReactフォームの利点が通信・仮想化・寿命管理の追加負担を上回る証拠はない。**現状のDivergenceSplitterではQt Widgetsを基準に進める**。WebView2の小さいアプリZIPとCSS/JSXの柔軟さは利点として残すが、優先度の低い容量だけで逆転させない。

物理IMEの変換候補・確定、実モニター間DPI、ファイル選択の確定、100回操作の新規反復、Webの長時間soak、16超の同時参照、残存UDFの自動回収は未検証/未実装。UTF-8入力の単体/JSON試験を実IME試験の合格にはしない。これらを含む製品品質の完成を主張せず、GUI方式の比較と推奨までを今回の成果とする。
