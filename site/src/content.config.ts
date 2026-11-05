import { defineCollection } from 'astro:content';
import { docsLoader } from '@astrojs/starlight/loaders';
import { docsSchema } from '@astrojs/starlight/schema';

/**
 * Docs live in src/content/docs/ but are served under /docs/ so the custom
 * landing page can own the site root. A file at src/content/docs/reference/cli.md
 * becomes the entry `docs/reference/cli` (URL: /repo-ai/docs/reference/cli/).
 */
function slugSegment(segment: string): string {
  return segment
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

export const collections = {
  docs: defineCollection({
    loader: docsLoader({
      generateId: ({ entry, data }) => {
        if (data.slug) return String(data.slug);
        const parts = entry
          .replace(/\.(mdx?|markdown|mdown|mkdn|mkd|mdwn)$/i, '')
          .split('/')
          .map(slugSegment)
          .filter(Boolean);
        if (parts[parts.length - 1] === 'index') parts.pop();
        return ['docs', ...parts].join('/');
      },
    }),
    schema: docsSchema(),
  }),
};
