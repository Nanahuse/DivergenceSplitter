import { describe, expect, it } from 'vitest';
import { Tree, restoreAnchor } from './tree';
import type { Node } from './contracts';
const node = (id: string, parent = '0'): Node => ({ id, parent, kind: parent === '0' ? 0 : 3, label: id, enabled: true, note: '' });
describe('stable hierarchy and viewport', () => {
  it('retains expansion only for surviving IDs and restores deleted anchor to a neighbour', () => {
    const old = new Tree([node('1'), node('2', '1'), node('3', '1')]);
    const next = new Tree([node('1'), node('3', '1'), node('4', '1')]);
    const expanded = new Set(['1', '2', '3']);
    expect([...next.retain(expanded)]).toEqual(['1', '3']);
    expect(restoreAnchor(old.flatten(expanded), next.flatten(next.retain(expanded)), 37)).toBe(37);
  });
  it('keeps a surviving scroll anchor across insertion and supports 10,220 nodes', () => {
    const old = new Tree([node('1'), node('2')]);
    const next = new Tree([node('9'), node('1'), node('2')]);
    expect(restoreAnchor(old.flatten(new Set()), next.flatten(new Set()), 39)).toBe(71);
    const large = new Tree(Array.from({ length: 10220 }, (_, i) => node(String(i + 1))));
    expect(large.flatten(new Set())).toHaveLength(10220);
    expect(large.path('10220')).toEqual(['10220']);
  });
});
