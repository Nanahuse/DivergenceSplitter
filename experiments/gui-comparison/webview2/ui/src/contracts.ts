import { z } from 'zod';
export const Scenario = z.object({ id: z.string(), name: z.string().max(256), port: z.number().int(), enabled: z.boolean() });
export const Profile = z.object({ source: z.number().int().min(0).max(1), file: z.string().max(32768), scenarios: z.array(Scenario).min(1).max(100) });
export type Profile = z.infer<typeof Profile>;
export const Node = z.object({ id: z.string(), parent: z.string(), kind: z.number().int().min(0).max(3), label: z.string(), enabled: z.boolean() });
export type Node = z.infer<typeof Node>;
export const Metric = z.tuple([z.string(), z.number(), z.boolean(), z.boolean(), z.boolean()]);
export type Metric = z.infer<typeof Metric>;
export const Snapshot = z.object({
  version: z.literal(1), type: z.literal('snapshot'), epoch: z.number().int(), delivery: z.number().int(),
  sequence: z.string(), revision: z.string(), running: z.boolean(), resets: z.string(),
  nodes: z.array(Node).optional(), metrics: z.array(Metric), profile: Profile,
  roots: z.array(Node),
  frame: z.object({ sequence: z.string(), jpeg: z.string() }).optional(),
  references: z.record(z.string(), z.string()),
});
export type Snapshot = z.infer<typeof Snapshot>;
export const Response = z.object({ version: z.literal(1), type: z.literal('response'), epoch: z.number().int(), id: z.number().int(), ok: z.boolean(), result: z.unknown().optional(), error: z.string().optional() });
export type Page = 'monitor' | 'diagnostics' | 'profile';
export type Probe = { page: Page; expanded: boolean; dirty: boolean; errors: boolean; references: number; draft_count: number; scroll: number; busy: boolean; rendered_rows: number; tree_builds: number; value_updates: number };
