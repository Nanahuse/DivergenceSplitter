# 設定リファレンス

[ドキュメント一覧](../README.md) · [Profileの操作](user-guide.md#profileの操作)

## 目次

- [Profile JSON v2](#profile-json-v2)
- [Camera・キャプチャーカード](#cameraキャプチャーカード)
- [Video file](#video-file)
- [NDI®](#ndi)
- [Crop・Resize・参照画像](#cropresize参照画像)
  - [入力映像の変換](#入力映像の変換)
  - [参照画像のサイズ変更](#参照画像のサイズ変更)
- [複数インスタンス](#複数インスタンス)
- [アプリケーション設定](#アプリケーション設定)

## Profile JSON v2

Profileは映像入力と、各LiveSplitで使うシナリオをまとめて保存するJSONファイルです。1つのシナリオとBridge接続の組をインスタンスと呼びます。映像入力は全インスタンスで共有しますが、条件の計測・回数やタイマーへの接続は、それぞれ独立しています。

[profile.example.json](../examples/profile.example.json) のファイルパスを、自分の環境の絶対パスに変えて使ってください。JSONではコメントや末尾のカンマは使えません。未定義のキーがあると、入れ子の項目を含めて読み込みに失敗します。キー名と選択肢の値は、大文字・小文字を区別します。

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

このオブジェクトはProfileの `source` に指定します。機器名とモードは、Profileに表示される値を使います。

| 項目 | 必須 | 値 |
| --- | --- | --- |
| `type` | はい | `"camera"`。 |
| `device.backend` | はい | `"direct_show"` または `"media_foundation"`。 |
| `device.name` | はい | 機器一覧に表示された名前を、そのまま指定します。空文字は使えません。 |
| `device.index` | はい | 機器一覧の番号を表す0以上の整数。同じ名前の機器を区別するために使います。名前とバックエンドに一致する機器が1つなら、インデックスが変わっても選択できます。 |
| `mode.width`、`mode.height` | はい | モード一覧にある幅・高さを正の整数で指定します。 |
| `mode.fps` | はい | モード一覧にあるFPSを、0より大きい数値で指定します。 |
| `mode.subtype_guid` | はい | 列挙された空でないメディアサブタイプのGUID。 |
| `request_60_fps` | はい | 真偽値。モード設定後に60 FPSを追加要求します。この場合、通常の設定FPSとの不一致検査を無効にします。60 FPSの受信は保証しません。 |
| `transform` | いいえ | 後述の画像変換。省略するとCrop／Resizeを行いません。 |

DirectShowでは、指定したサブタイプを選択して確認できるモードを使います。Media Foundationでは、モード一覧の寸法とFPSを照合します。画面上でsize/FPSと表示されるモードでは、サブタイプを厳密には選択できません。

入力側からFPSの報告があれば設定値と照合しますが、実際に受信するFPSが同じになるとは限りません。

## Video file

```json
{
  "type": "video",
  "path": "C:/recordings/run.avi",
  "transform": { "crop": null, "resize": null }
}
```

`type` と `path` は必須です。`path` には動画ファイルの絶対パスを指定し、空文字は使えません。`transform` は省略できます。

動画側から報告されたFPSで再生し、報告がなければ30 FPSで再生します。ファイルの末尾に達すると映像取得を止め、エラーを表示します。繰り返し再生には対応していません。

再生できる形式は、そのビルドのOpenCVが使える動画バックエンドによって決まります。拡張子だけでは再生できるかどうかを判断できません。

AVI／MJPEGには内蔵デコーダーを使えます。Profileにデコーダーを指定する項目はありません。

## NDI®

```json
{
  "type": "ndi",
  "name": "CAPTURE-PC (Game)",
  "transform": { "crop": null, "resize": null }
}
```

`type` と `name` は必須です。`name` には送信元が公開している名前を指定し、空文字は使えません。IPアドレスやURLを指定する項目ではありません。`transform` は省略できます。

送信元がオフラインの間も、保存済みの名前を保持します。

NDI入力を使用するには、NDI Runtimeを別途インストールする必要があります。配布ZIPにはNDI Runtimeは含まれません。起動時にインストール済みRuntimeを検出し、見つからない場合はNDI入力だけが利用できません。

同じ名前の送信元が戻ると受信を再開できます。受信できない場合は[入力の問題](troubleshooting.md#入力の問題)を参照してください。

利用条件は[NDIの通知](../licenses/NDI.md)を参照してください。

## Crop・Resize・参照画像

### 入力映像の変換

Camera、Video、NDIのいずれも、`transform` で画像を変換できます。この項目自体は省略できます。指定する場合は、`crop` と `resize` の両方を記述してください。それぞれ `null` を指定すると、その変換だけを無効にできます。

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

入力映像はCropで切り取り、Resizeでサイズを変えます。DetectorのROIは、変換後の画像の中から判定する範囲を選びます。たとえば1920×1080の映像を左右8ピクセルずつ切り取ると、1904×1080になります。その画像を1280×720にResizeした場合、YAMLのROIも1280×720の画像上の座標で指定します。Monitorに表示する画像と、各インスタンスが判定する画像は同じです。

### 参照画像のサイズ変更

`resize_references: true` を指定すると、シナリオの読み込み時に参照画像をサイズ変更します。補間方法には `resize.interpolation` を使い、寸法は次のように決まります。

- ROIがないDetector：ProfileのResize出力の幅・高さ。
- ROIがあるDetector：そのROIの幅・高さ。

参照画像を切り取ったり、ROIの座標を拡大縮小したりはしません。YAMLや元の画像ファイルも書き換えません。Resizeが無効な場合や `resize_references: false` の場合は、元の参照画像の寸法を使います。

小さなテンプレートを広い映像の中から探すときは、`resize_references: false` を指定してください。有効にすると、小さな画像も出力全体またはROIと同じ寸法になります。

透過画像のサイズを変えると、補間によって半透明のピクセルができ、二値マスクの検証に失敗する場合があります。その場合は `nearest` を選ぶか、条件に合う参照画像を用意してください。画像の寸法・チャンネル・alphaの制約は、[Detectorリファレンス](scenarios/detectors.md)で説明します。

Apply時にはシナリオと参照画像を読み込み、サイズ変更後の参照画像も検証します。ただし、ROIが実際の映像内に収まるか、映像と参照画像の寸法・チャンネルが合うかは、フレームを受信して判定するまで確認できません。

## 複数インスタンス

`instances` の各要素に、操作するLiveSplitのBridgeポートとシナリオを指定します。映像入力とCrop／Resizeは共通です。接続やConditionの時間・回数はインスタンスごとに管理します。

別々のLiveSplitを操作するには、Bridgeごとに異なるポートを設定し、`instances[].connection.port` をそれぞれに合わせます。同じポートを複数の要素に指定すると、それらのシナリオが同じLiveSplitを操作します。

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

`version` は `1`、`log_level` は `OFF`、`DEBUG`、`INFO`、`WARNING`、`ERROR` のいずれか、`reaction_time_ms` は0以上の整数を指定します。この3項目は必須です。

`last_profile` は省略できます。指定する場合は、Profileの絶対パスまたは `null` にします。`ui` も省略でき、その中の `theme` には `light`（既定値）または `dark` を指定できます。`theme` 自体も省略できます。

未定義の項目があると読み込みに失敗します。画面での設定方法と、変更が反映されるタイミングは[Settings](user-guide.md#settings)を参照してください。
