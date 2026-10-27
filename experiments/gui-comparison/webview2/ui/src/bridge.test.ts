import { describe, expect, it, vi } from 'vitest';
import { Bridge } from './bridge';
describe('native contract', () => {
  it('acknowledges snapshots only after UI consumption finishes', async () => {
    let receive: (event: MessageEvent) => void = () => {};
    const postMessage = vi.fn();
    const bridge = new Bridge({ postMessage, addEventListener: (_, f) => { receive = f; } });
    const ready = bridge.request('ready');
    receive({ data: { version: 1, type: 'response', epoch: 7, id: 1, ok: true } } as MessageEvent);
    await ready;
    let finish: () => void = () => {};
    bridge.onSnapshot = () => new Promise(resolve => { finish = () => resolve({ page: 'monitor', expanded: false, dirty: false, errors: false, references: 0, draft_count: 1, scroll: 0, busy: false, rendered_rows: 0, tree_builds: 0, value_updates: 0 }); });
    receive({ data: { version: 1, type: 'snapshot', epoch: 7, delivery: 9, sequence: '9007199254740993', revision: '1', running: true, resets: '0',
      metrics: [], roots: [], initial_dark: false, references: {}, profile: { source: 0, file: '', scenarios: [{ id: '1', name: 'Scenario', port: 16834, enabled: true, note: '' }] } } } as MessageEvent);
    expect(postMessage).toHaveBeenCalledTimes(1);
    finish(); await Promise.resolve(); await Promise.resolve();
    expect(postMessage.mock.calls[1][0]).toMatchObject({ command: 'ack', epoch: 7, args: { delivery: 9 } });
  });
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
