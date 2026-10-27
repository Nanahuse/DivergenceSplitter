import { Response, Snapshot, type Probe } from './contracts';
type WebView = { postMessage: (value: unknown) => void; addEventListener: (name: string, handler: (event: MessageEvent) => void) => void };
declare global { interface Window { chrome: { webview: WebView }; comparison?: { perform: (action: number) => void } } }
export class Bridge {
  private next = 1;
  private epoch = 0;
  private pending = new Map<number, { resolve: (value: unknown) => void; reject: (error: Error) => void; timeout: ReturnType<typeof setTimeout> }>();
  onSnapshot: (snapshot: Snapshot) => Promise<Probe> = async () => { throw new Error('UI not mounted'); };
  onTestAction: (action: number) => void = () => {};
  constructor(private transport: WebView) {
    transport.addEventListener('message', event => { void this.receive(event.data); });
  }
  async start() { await this.request('ready'); }
  request(command: string, args: unknown = {}): Promise<unknown> {
    if (this.pending.size >= 32) return Promise.reject(new Error('Native command queue busy'));
    const id = this.next++;
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => { this.pending.delete(id); reject(new Error(`Native timeout: ${command}`)); }, 10000);
      this.pending.set(id, { resolve, reject, timeout });
      this.transport.postMessage({ version: 1, epoch: this.epoch, id, command, args });
    });
  }
  private async receive(data: unknown) {
    const response = Response.safeParse(data);
    if (response.success) {
      const r = response.data, pending = this.pending.get(r.id);
      if (!pending || (this.epoch !== 0 && r.epoch !== this.epoch)) return;
      if (!this.epoch) this.epoch = r.epoch;
      clearTimeout(pending.timeout); this.pending.delete(r.id);
      if (r.ok) pending.resolve(r.result); else pending.reject(new Error(r.error ?? 'Native error'));
      return;
    }
    if (typeof data === 'object' && data && 'testAction' in data && typeof data.testAction === 'number') {
      this.onTestAction(data.testAction); return;
    }
    const s = Snapshot.parse(data);
    if (s.epoch !== this.epoch) return;
    try {
      const probe = await this.onSnapshot(s);
      // One outstanding snapshot, acknowledged after React commit + image decode + animation frame.
      this.transport.postMessage({ version: 1, epoch: this.epoch, id: 0, command: 'ack', args: { delivery: s.delivery, probe } });
    } catch (error) {
      this.transport.postMessage({ version: 1, epoch: this.epoch, id: 0, command: 'uiError', args: { error: String(error) } });
    }
  }
}
