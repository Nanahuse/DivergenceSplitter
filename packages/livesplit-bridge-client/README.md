# livesplit-bridge-client

`LiveSplit.Bridge` v1向けのPython client libraryです。DivergenceSplitterと同じGit
repositoryに置かれますが、uv workspaceの独立projectとしてinstallできます。

## Protocol authority

protocol schemaの唯一の正本はGit submodule
[`external/LiveSplit.Bridge`](../../external/LiveSplit.Bridge)の`proto/`です。現在のgitlinkは
commit `a55747d500eaa6d1e79dd95bf5f799c3da81376a`を指します。checkout後は次のように
submoduleを初期化してください。更新や再調査時も同じrepositoryを参照します。

```powershell
git submodule update --init --recursive
git -C external/LiveSplit.Bridge fetch origin main
git -C external/LiveSplit.Bridge checkout origin/main
uv lock
```

protobuf codeはuv syncやwheel build時に正本schemaから生成されます。sdist buildでは
正本schemaをsdistへ取り込み、そこからwheelをbuildする際にcodeを生成します。生成された
`src/livesplit/`はbuild artifactでGit管理しません。手動で開発用生成物を作る場合は次を
実行できます。

```powershell
uv run --package livesplit-bridge-client python packages/livesplit-bridge-client/proto_codegen.py
```

runtimeでは`protoc`を必要としません。generated typesは内部実装であり、
`livesplit_bridge_client`の公開APIには含めません。sdistには正本submoduleから取得した
schemaを含め、sdistからwheelをbuildする場合も同じschemaから生成します。

## Usage

```python
from livesplit_bridge_client import LiveSplitBridgeClient, TimerOperation

with LiveSplitBridgeClient() as client:
    attached = client.attach()
    event = client.poll_event(timeout_ms=100)
    result = client.execute_timer_operation(TimerOperation.SPLIT)
```

`poll_event`のtimeoutは`None`を返します。RPC timeoutは`BridgeTimeoutError`を送出し、
timer operationでは`operation_may_have_completed`が`True`になります。

## Safety boundary

現在のBridge v1は期待session/revision/phase/split位置を同一UI-threadで照合する
atomic compare-and-actを提供していません。また、外部UI/hotkeyイベントに対する
`state_revision`の意味論もScenarioRuntimeの必要条件を満たしていません。このlibraryは
現行wire contractを正確に扱いますが、これらの未提供保証を補完したとは主張しません。

clientはZeroMQ socketを生成した単一threadから利用してください。timer operationがtimeout
した場合、操作結果は不明です。libraryは自動再送しません。また、現行BridgeではRPCによる
timer operationのeventが`state_revision`のincrementより先にpublishされるため、eventの
snapshotが操作直前の古いrevisionを含む場合があります。
