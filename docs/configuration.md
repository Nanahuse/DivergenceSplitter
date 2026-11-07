# 設定リファレンス

[日本語（正本）](configuration.md) | [English](configuration.en.md)

[ドキュメント一覧](../README.md) · [Profileの操作](user-guide.md#profileの下書き適用済み設定ファイル)

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

上の例はProfileの `source` に指定する内容です。機器名やモードの値を手で推測せず、ProfileのDetect camerasで表示された一覧から選んでください。

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

機器はバックエンドと名前で選び、同じ名前の機器が複数ある場合は一覧の番号で区別します。幅、高さ、FPS、サブタイプは、モード一覧の値に合わせる必要があります。

DirectShowでは選んだFourCCサブタイプを設定できたかを確認します。サブタイプを厳密に選べないモードはApply時に拒否します。Media Foundationではモード一覧の内容と、入力を開いたときの寸法・FPSを確認します。ただしOpenCVからサブタイプを厳密には選べないため、そのモードは画面にsize/FPSと表示します。

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

動画側から報告されたFPSで再生し、報告がなければ30 FPSで再生します。ファイルの末尾に達すると映像取得を止め、エラーを表示します。自動で繰り返し再生はしません。先頭から再生し直すにはApplyを押してください。

再生できる形式は、そのビルドのOpenCVが使える動画バックエンドによって決まります。拡張子だけでは再生できるかどうかを判断できません。

動画を開くときは、まずOpenCV内蔵のAVI／MJPEGデコーダー（`CAP_OPENCV_MJPEG`）を試します。開けなければ、他の利用可能なバックエンドから選ぶ方法（`CAP_ANY`）に切り替えます。Profileからデコーダーを指定することはできません。

内蔵デコーダーで再生するMJPEG AVIでは、OSのコーデックやGPUを初期化する必要がありません。他の形式への対応はOpenCVのビルド内容と利用可能なバックエンドによります。

## NDI®

```json
{
  "type": "ndi",
  "name": "CAPTURE-PC (Game)",
  "transform": { "crop": null, "resize": null }
}
```

`type` と `name` は必須です。`name` には送信元が公開している名前を指定し、空文字は使えません。IPアドレスやURLを指定する項目ではありません。`transform` は省略できます。

Profileの一覧では、送信元がオフラインでも保存済みの名前を編集できます。Search againで再検索でき、Profile画面を開いている間も一覧を更新します。

NDI入力を使用するには、NDI Runtimeを別途インストールする必要があります。配布ZIPにはNDI Runtimeは含まれません。起動時にインストール済みRuntimeを検出し、見つからない場合はNDI入力だけが利用できません。

送信元が一時停止した場合や、通常の受信タイムアウトが起きた場合も、受信機は作り直しません。同じ名前の送信元が戻ると、SDKが再接続します。処理を続けられないSDKエラーや映像形式のエラーでは、映像取得を止めます。受信したフレームは、アプリが保持するBGR画像に変換して判定します。

利用条件は[NDIの通知](../licenses/NDI.md)、ソースから有効にする方法は[NDI対応ビルド](development/building.md#ndi対応ビルド)を参照してください。

## Crop・Resize・参照画像

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

Resize reference imagesは、入力映像ではなく、シナリオの参照画像のサイズを変える設定です。シナリオを読み込むときに、選んだ補間方法で各参照画像を次の寸法に変換します。

- ROIがないDetector：ProfileのResize出力の幅・高さ。
- ROIがあるDetector：そのROIの幅・高さ。

参照画像を切り取ったり、ROIの座標を拡大縮小したりはしません。YAMLや元の画像ファイルも書き換えません。Resizeが無効な場合や `resize_references: false` の場合は、元の参照画像の寸法を使います。

小さなテンプレートを広い映像の中から探すときは、Resize reference imagesをオフにしてください。有効にすると、その小さな画像も出力全体またはROIの寸法まで拡大されます。

透過画像のサイズを変えると、補間によって半透明のピクセルができ、二値マスクの検証に失敗する場合があります。その場合は `nearest` を選ぶか、条件に合う参照画像を用意してください。画像の寸法・チャンネル・alphaの制約は、[Detectorリファレンス](scenarios/detectors.md)で説明します。

Apply時にはシナリオと参照画像を読み込み、サイズ変更後の参照画像も検証します。ただし、ROIが実際の映像内に収まるか、映像と参照画像の寸法・チャンネルが合うかは、フレームを受信して判定するまで確認できません。

## 複数インスタンス

複数のLiveSplitを使う場合は、それぞれに対応する行をProfileへ追加します。Bridgeには `54000`、`54001` など別々のポートを設定し、Profileの各行に同じポートを指定してください。行ごとに違うYAMLを選べます。映像の取得とCrop／Resizeは共通ですが、各条件の状態とタイマーへの接続は独立しています。

同じポートを複数行に指定しても、設定エラーにはなりません。その場合は、複数のシナリオが同じLiveSplitを操作します。別々のRunを操作したい場合は、必ず別のポートを使ってください。Crop／Resizeは全行で共有する入力設定なので、行ごとには変えられません。

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