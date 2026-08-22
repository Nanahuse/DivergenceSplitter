# livesplit-bridge-client

`LiveSplit.Bridge` v1向けのPython client libraryです。DivergenceSplitterと同じGit
repositoryに置かれますが、uv workspaceの独立projectとしてinstallできます。

## Protocol authority

同梱schemaは
[`Nanahuse/LiveSplit.Bridge`](https://github.com/Nanahuse/LiveSplit.Bridge)
のcommit `7bcb4ec3896a3fb95099da8f101e4565c3f3daf8`から同期しています。
更新時は`proto/`を正本commitから同期し、次を実行してgenerated filesとlockを更新します。

```powershell
uv run --package livesplit-bridge-client python packages/livesplit-bridge-client/scripts/generate_proto.py
uv lock
```

runtimeでは`protoc`を必要としません。protobuf generated typesは内部実装であり、
`livesplit_bridge_client`の公開APIには含めません。

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
