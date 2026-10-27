import type { Node } from './contracts';
export type Row = { node: Node; depth: number };
// Indexed only on topology revisions. Metric updates never rebuild the hierarchy.
export class Tree {
  readonly byId: Map<string, Node>;
  readonly children = new Map<string, Node[]>();
  constructor(readonly nodes: Node[]) {
    this.byId = new Map(nodes.map(n => [n.id, n]));
    for (const n of nodes) {
      const siblings = this.children.get(n.parent) ?? [];
      siblings.push(n); this.children.set(n.parent, siblings);
    }
  }
  retain(expanded: Set<string>) { return new Set([...expanded].filter(id => this.byId.has(id))); }
  flatten(expanded: Set<string>): Row[] {
    const result: Row[] = [];
    const walk = (parent: string, depth: number) => {
      for (const node of this.children.get(parent) ?? []) {
        result.push({ node, depth });
        if (expanded.has(node.id)) walk(node.id, depth + 1);
      }
    };
    walk('0', 0); return result;
  }
  path(id: string) {
    const result: string[] = [];
    for (let n = this.byId.get(id); n; n = this.byId.get(n.parent)) result.push(n.id);
    return result;
  }
}
export function restoreAnchor(oldRows: Row[], rows: Row[], scroll: number, height = 32) {
  const top = Math.floor(scroll / height);
  const positions = new Map(rows.map((r, i) => [r.node.id, i]));
  // First surviving neighbour when the anchor itself was removed.
  for (let distance = 0; distance <= oldRows.length; distance++) {
    for (const index of [top + distance, top - distance]) {
      const id = oldRows[index]?.node.id;
      if (id && positions.has(id)) return positions.get(id)! * height + scroll % height;
    }
  }
  return 0;
}
