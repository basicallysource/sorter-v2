// The written docs (docs/*.md), for the site's Docs pages. Each file is read
// as it is; links between the files become links between the pages.
import { Marked } from 'marked';

const files = import.meta.glob('/docs/*.md', {
	query: '?raw',
	import: 'default',
	eager: true
}) as Record<string, string>;

// The index first, then the order a newcomer reads them in.
const ORDER = [
	'README',
	'rules',
	'surfaces',
	'color',
	'type',
	'icons',
	'layout',
	'components',
	'overlays',
	'loading',
	'engineering',
	'apps',
	'decisions'
];

export type Doc = { slug: string; title: string; summary: string; source: string };

export const docs: Doc[] = Object.entries(files)
	.map(([path, source]) => {
		const slug = path.replace(/^.*\//, '').replace(/\.md$/, '');
		const title = source.match(/^# (.+)$/m)?.[1] ?? slug;
		const summary =
			source
				.split(/\n\s*\n/)
				.find((block) => block.trim() && !block.startsWith('#'))
				?.replace(/\s+/g, ' ')
				.trim() ?? '';
		return { slug, title, summary, source };
	})
	.sort((a, b) => rank(a.slug) - rank(b.slug));

function rank(slug: string) {
	const i = ORDER.indexOf(slug);
	return i === -1 ? ORDER.length : i;
}

export function slugify(text: string) {
	return text
		.toLowerCase()
		.replace(/<[^>]+>/g, '')
		.replace(/[^a-z0-9]+/g, '-')
		.replace(/^-|-$/g, '');
}

const marked = new Marked({
	gfm: true,
	renderer: {
		heading({ tokens, depth }) {
			const text = this.parser.parseInline(tokens);
			return `<h${depth} id="${slugify(text)}">${text}</h${depth}>\n`;
		},
		link({ href, title, tokens }) {
			const text = this.parser.parseInline(tokens);
			// Another doc: README.md is the index, rules.md#x is /docs/rules#x.
			const doc = href.match(/^([\w-]+)\.md(#.*)?$/);
			const to = doc ? `/docs${doc[1] === 'README' ? '' : '/' + doc[1]}${doc[2] ?? ''}` : href;
			const outside = /^https?:/.test(to);
			return `<a href="${to}"${title ? ` title="${title}"` : ''}${
				outside ? ' target="_blank" rel="noreferrer"' : ''
			}>${text}</a>`;
		}
	}
});

export function render(source: string): string {
	return marked.parse(source, { async: false });
}
