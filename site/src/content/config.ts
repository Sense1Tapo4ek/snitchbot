import { defineCollection, z } from 'astro:content';

const sections = ['api', 'guide', 'cookbook'] as const;

const docs = defineCollection({
  type: 'content',
  schema: z.object({
    title: z.string(),
    section: z.enum(sections),
    order: z.number().int().positive(),
    summary: z.string(),
    watermark: z.string().min(1).max(2),

    // API-only
    symbol: z.string().optional(),
    kind: z.enum(['function', 'class']).optional(),
    since: z.string().optional(),

    // Guide/cookbook-only
    slug: z.string().optional(),
    read_time: z.string().optional(),
  }).superRefine((data, ctx) => {
    if (data.section === 'api') {
      if (!data.symbol) ctx.addIssue({ code: 'custom', message: 'api page requires `symbol`', path: ['symbol'] });
      if (!data.kind)   ctx.addIssue({ code: 'custom', message: 'api page requires `kind`', path: ['kind'] });
      if (!data.since)  ctx.addIssue({ code: 'custom', message: 'api page requires `since`', path: ['since'] });
    }
  }),
});

export const collections = { docs };
