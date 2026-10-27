import { describe, expect, it, vi } from 'vitest';
import { Bridge } from './bridge';
describe('native contract', () => {
  it('correlates responses, rejects errors, ignores stale epochs and bounds pending commands', async () => {
    let receive: (event: MessageEvent) => void = () => {};
    const postMessage = vi.fn();
    const bridge = new Bridge({ postMessage, addEventListener: (_, f) => { receive = f; } });
    const ready = bridge.request('ready');
    receive({ data: { version: 1, type: 'response', epoch: 7, id: 1, ok: true, result: {} } } as MessageEvent);
    await ready;
    const action = bridge.request('apply');
    receive({ data: { version: 1, type: 'response', epoch: 6, id: 2, ok: true } } as MessageEvent);
    receive({ data: { version: 1, type: 'response', epoch: 7, id: 2, ok: false, error: 'Invalid profile' } } as MessageEvent);
    await expect(action).rejects.toThrow('Invalid profile');
    const requests = Array.from({ length: 32 }, () => bridge.request('running'));
    await expect(bridge.request('running')).rejects.toThrow('busy');
    for (let id = 3; id < 35; id++) receive({ data: { version: 1, type: 'response', epoch: 7, id, ok: true } } as MessageEvent);
    await Promise.all(requests);
    expect(postMessage.mock.calls[1][0].epoch).toBe(7);
  });
});
