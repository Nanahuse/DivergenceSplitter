# 設定リファレンス

[日本語（正本）](configuration.md) | [English](configuration.en.md)

[ドキュメント一覧](../README.md) · [Profileの操作](user-guide.md#profileの下書き適用済み設定ファイル)

## Profile JSON v2

Profileには共有する入力1つと、独立したシナリオ・Bridge接続の一覧を記録します。[profile.example.json](../examples/profile.example.json) の絶対パスを変更して使ってください。JSONではコメントと末尾のカンマを使えません。Profileとその入れ子のオブジェクトでは、未知のキーを拒否します。キーと列挙値は大文字・小文字を区別します。

| 項目 | 必須 | 値 |
| --- | --- | --- |
| `version` | はい | 整数 `2`。 |
| `source` | はい | 後述するCamera、Video、NDIのいずれかのオブジェクト。 |
| `instances` | はい | インスタンスの配列。JSONローダーは空配列を受理しますが、GUIのApplyでは1件以上必要です。 |
| `instances[].connection` | はい | `port` だけを持つオブジェクト。 |
| `instances[].connection.port` | はい | 整数 `1`～`65535`。同じPCの対応するBridgeのWebSocketポートです。通常は `54000` を使います。 |
| `instances[].scenario` | はい | `.yaml` または `.yml` ファイルへの空でない絶対パス。 |

接続先ホストは `127.0.0.1` 固定です。Profileにホスト名やURLを設定する項目はありません。動画とシナリオのパスは絶対パスなので、Profile JSONの保存場所には依存しません。Windowsでは `C:/folder/file` と書くか、バックスラッシュを `C:\\folder\\file` のようにエスケープします。YAML内の参照画像には[別のパス規則](scenarios/yaml-reference.md#パス)を使います。

## Camera・キャプチャーカード

```json
{
  "type": "camera",
  "device": {
    "backend": "direct_show",
    "name": "USB Video",
    "index": 0
  },
  "mode": {
    "width": 1920,
    "height": 1080,
    "fps": 60.0,
    "subtype_guid": "47504A4D-0000-0010-8000-00AA00389B71"
  },
  "request_60_fps": false,
  "transform": { "crop": null, "resize": null }
}
```

これは `source` オブジェクトの例です。デバイス名とモードは使用する機器の列挙結果に合わせてください。ProfileでDetect camerasを押し、モードを選ぶ方法を推奨します。

| 項目 | 必須 | 値 |
| --- | --- | --- |
| `type` | はい | `"camera"`。 |
| `device.backend` | はい | `"direct_show"` または `"media_foundation"`。 |
| `device.name` | はい | 列挙された空でないデバイス名。完全一致で指定します。 |
| `device.index` | はい | 0以上の列挙インデックス。同名のデバイスを区別します。名前とバックエンドに一致する機器が1つなら、インデックスが変わっても選択できます。 |
| `mode.width`、`mode.height` | はい | モード一覧にある正の整数の幅・高さ。 |
| `mode.fps` | はい | 列挙されたモードに一致する正の数値。 |
| `mode.subtype_guid` | はい | 列挙された空でないメディアサブタイプのGUID。 |
| `request_60_fps` | はい | 真偽値。モード設定後に60 FPSを追加要求します。この場合、通常の設定FPSとの不一致検査を無効にします。60 FPSの受信は保証しません。 |
| `transform` | いいえ | 後述の画像変換。省略するとCrop／Resizeを行いません。 |

機器はバックエンドと名前で特定し、同名の場合はインデックスで区別します。モードの幅、高さ、FPS、サブタイプは列挙結果と一致する必要があります。DirectShowは選択可能なFourCCサブタイプを設定して確認します。厳密なサブタイプ選択に対応しないモードはApplyで拒否します。Media Foundationは列挙内容と、入力を開いたときのサイズ・FPSを検査しますが、OpenCVから厳密なサブタイプを選択できません。そのモードには画面上でsize/FPSと表示します。FPSが報告された場合は値を検査しますが、実測の取得FPSは異なる場合があります。

## Video file

```json
{
  "type": "video",
  "path": "C:/recordings/run.avi",
  "transform": { "crop": null, "resize": null }
}
```

`type` と空でない絶対パス `path` は必須で、`transform` は任意です。報告されたFPSで再生し、FPSが報告されなければ30 FPSを使います。再生にはビルドに含まれるOpenCVの動画バックエンドを使うため、拡張子だけでは再生できるかを判断できません。ファイル末尾に達すると取得を停止してエラーを報告します。自動ループは行いません。Applyするとファイルを開き直します。

動画を開くときはOpenCV内蔵のAVI／MJPEGデコーダー（`CAP_OPENCV_MJPEG`）を先に試し、開けなければ通常のバックエンド選択（`CAP_ANY`）へフォールバックします。デコーダーを選ぶProfile項目はありません。内蔵デコーダーを使うMJPEG AVIはOSのコーデックやGPUの初期化を必要としません。他の形式の対応はOpenCVビルドと利用可能なバックエンドによります。

## NDI®

```json
{
  "type": "ndi",
  "name": "CAPTURE-PC (Game)",
  "transform": { "crop": null, "resize": null }
}
```

`type` と、送信元が公開する空でない名前 `name` は必須で、`transform` は任意です。IPアドレスやURLではなく名前で選択します。Profileの編集可能な一覧は、送信元がオフラインでも保存済みの名前を保持します。Search againで再検索でき、Profileを表示している間も一覧を更新します。

NDI対応ビルドが必要です。公式ZIPは実行ファイルの隣にランタイムを同梱します。送信元の一時停止や通常の受信タイムアウトでは受信機を維持し、同名の送信元が戻るとSDKが再接続します。致命的なSDK・形式エラーでは取得を停止します。フレームはアプリ側で保持するBGR画像に変換してから処理します。[NDIの通知](../licenses/NDI.md)と[NDI対応ビルド](development/building.md#ndi対応ビルド)も参照してください。

## Crop・Resize・参照画像

3種類の入力は共通の任意項目 `transform` を持ちます。指定する場合は `crop` と `resize` の両方が必要です。各項目を `null` にすると、その変換を無効にします。

```json
{
  "crop": { "left": 8, "right": 8, "top": 0, "bottom": 0 },
  "resize": {
    "width": 1280,
    "height": 720,
    "interpolation": "area",
    "resize_references": false
  }
}
```

| 項目 | 値 |
| --- | --- |
| `crop.left`、`right`、`top`、`bottom` | すべて必須。入力画像のピクセル数で指定する0以上の整数です。左右と上下の合計は、それぞれ最低1ピクセルを残す必要があります。 |
| `resize.width`、`height` | 必須の正の整数。指定した寸法に変換します。縦横比の自動維持や余白の追加は行いません。 |
| `resize.interpolation` | 任意。`area` が既定値です。`nearest`、`linear`、`cubic`、`lanczos4` も指定できます。 |
| `resize.resize_references` | 任意の真偽値。既定値は `false`。Resizeが有効な場合だけ作用します。 |

入力画像は「入力 → Crop → Resize → DetectorのROI」の順で処理します。例えば1920×1080の画像を左右8ピクセルずつ切り取ると1904×1080になり、その後1280×720にResizeします。YAMLのROIは最終的な1280×720の座標で指定します。同じ正規化画像をMonitorと全インスタンスで使います。

Resize reference imagesは、シナリオの読み込み時に行う別の処理です。有効にすると、選択した補間方法で各参照画像を次の寸法に変換します。

- ROIがないDetector：ProfileのResize出力の幅・高さ。
- ROIがあるDetector：そのROIの幅・高さ。

参照画像の切り取り、ROI座標の拡大縮小、YAMLや画像ファイルの書き換えは行いません。Resizeが無効、または `resize_references: false` の場合は参照画像の寸法を保ちます。広い画像内から小さなテンプレートを探す場合はオフにしてください。有効にすると、そのテンプレートも出力全体またはROIの寸法に拡大します。透過画像を補間すると中間のalpha値が生じ、二値マスクの検証に失敗する場合があります。`nearest` を使うか、適切な参照画像を用意してください。寸法・チャンネル・alphaの制約は[Detectorリファレンス](scenarios/detectors.md)にまとめています。

Applyではシナリオと参照画像を構築し、変換後の参照画像も検証します。実フレームに依存するROIの範囲、形状、チャンネルの不一致は評価時に検出します。

## 複数インスタンス

LiveSplitプロセスごとに行を追加します。各LiveSplitのBridgeに `54000`、`54001` など異なるポートを設定し、Profileの対応する行に指定してください。行ごとに異なるYAMLを読み込めます。映像の取得と正規化は共有しますが、Conditionの状態とタイマー接続は独立しています。

ローダーはポートの重複を拒否しません。同じポートを複数行に指定すると、複数のシナリオが同じタイマーを操作します。独立したRunには別のポートを使ってください。Crop／Resizeは共有入力の設定なので、インスタンス別には設定できません。

## アプリケーション設定

GUIはProfileと別に `%APPDATA%/DivergenceSplitter/settings.json` を保存します。

```json
{
  "version": 1,
  "log_level": "INFO",
  "reaction_time_ms": 0,
  "last_profile": null,
  "ui": { "theme": "light" }
}
```

必須項目は `version`（`1`）、`log_level`（`OFF`、`DEBUG`、`INFO`、`WARNING`、`ERROR`）、`reaction_time_ms`（0以上の整数）です。`last_profile` は任意で、`null` またはProfileの絶対パスを指定します。`ui` も任意です。その中の任意項目 `theme` は `light`（既定値）または `dark` です。未知の項目は拒否します。各設定の作用と反映時期は[Settings](user-guide.md#settings)を参照してください。
