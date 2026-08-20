// Build-time content pipeline. Mirrors what Jekyll did for docs/: markdown
// files carry the same frontmatter and Liquid includes as before, but here
// they are rendered once at build time (liquidjs → unified) and the output is
// prerendered static HTML. Nothing in this module runs in the browser.
import yaml from 'js-yaml';
import { Liquid } from 'liquidjs';
import { unified } from 'unified';
import remarkParse from 'remark-parse';
import remarkGfm from 'remark-gfm';
import remarkRehype from 'remark-rehype';
import rehypeRaw from 'rehype-raw';
import rehypeSlug from 'rehype-slug';
import rehypeStringify from 'rehype-stringify';

// ── Raw sources ──────────────────────────────────────────────────────────────

const contentFiles = import.meta.glob('/src/content/**/*.md', {
	query: '?raw',
	import: 'default',
	eager: true
}) as Record<string, string>;

const includeFiles = import.meta.glob('/src/liquid/_includes/**/*.html', {
	query: '?raw',
	import: 'default',
	eager: true
}) as Record<string, string>;

const dataFiles = import.meta.glob('/src/liquid/_data/*.yml', {
	query: '?raw',
	import: 'default',
	eager: true
}) as Record<string, string>;

// ── Site data (_data/*.yml) ──────────────────────────────────────────────────

const data: Record<string, any> = {};
for (const [path, raw] of Object.entries(dataFiles)) {
	const name = path.split('/').pop()!.replace(/\.yml$/, '');
	data[name] = yaml.load(raw);
}

// Harness drawing URLs are literal strings in _data/harness.yml, pasted from
// the render that produced them, exactly like every other asset in the images
// bucket. Nothing about them is derived here on purpose. The scheme this
// replaced built them from the branch name plus a ?v=<this build's sha>, which
// meant the docs could emit a URL for bytes that had not been uploaded yet —
// the harness render and the docs build start on the same push — and the
// reader who lost that race cached a stale or truncated drawing under a
// year-long immutable header. See electronics/wire_harness/AGENTS.md.

export const site = {
	title: 'Sorter V2 Documentation',
	description:
		'Documentation for Sorter, the LEGO sorting machine. Assembly, operation, and software.',
	url: 'https://docs.basically.website',
	data
};

// ── Nav (verbatim port of _data/nav.yml semantics) ───────────────────────────

export type NavItem = { title: string; url: string; lede?: string; children?: NavItem[] };
export type NavGroup = { title: string; pages: NavItem[] };
export type NavSection = {
	id: string;
	title: string;
	url: string;
	description?: string;
	pages: NavItem[];
	groups?: NavGroup[];
};

const rawNavSections: NavSection[] = data.nav?.sections ?? [];

// ── Frontmatter ──────────────────────────────────────────────────────────────

export type Frontmatter = Record<string, any>;

function parseFrontmatter(raw: string): { fm: Frontmatter; body: string } {
	const m = raw.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?/);
	if (!m) return { fm: {}, body: raw };
	let fm: Frontmatter;
	try {
		fm = (yaml.load(m[1]) as Frontmatter) ?? {};
	} catch {
		// A few pages have frontmatter that is not strictly valid YAML (e.g. an
		// unquoted value containing ": "). Fall back to flat key: value lines.
		fm = {};
		for (const line of m[1].split('\n')) {
			const kv = line.match(/^([A-Za-z_][\w-]*):\s*(.*)$/);
			if (kv) fm[kv[1]] = kv[2];
		}
	}
	return { fm, body: raw.slice(m[0].length) };
}

// Per-section defaults, ported from docs/_config.yml. Later scopes win; page
// frontmatter wins over everything.
const FM_DEFAULTS: Array<{ prefix: string; values: Frontmatter }> = [
	{
		prefix: '',
		values: { owner: 'docs', audience: 'all readers', applies_to: 'site', last_verified: '2026-04-08' }
	},
	{
		prefix: 'hardware',
		values: { section: 'hardware', owner: 'hardware', audience: 'self-builder', applies_to: 'hardware-v2' }
	},
	{
		prefix: 'installation',
		values: { section: 'installation', owner: 'docs', audience: 'self-hosting operator', applies_to: 'sorter 2.x' }
	},
	{
		prefix: 'sorter',
		values: { section: 'sorter', owner: 'sorter', audience: 'self-hosting operator', applies_to: 'sorter 2.x' }
	},
	{
		prefix: 'hive',
		values: { section: 'hive', owner: 'hive', audience: 'operator linking a Sorter to Hive', applies_to: 'hive 0.x' }
	},
	{
		prefix: 'lab',
		values: { section: 'lab', owner: 'lab', audience: 'contributor', applies_to: '2026-04-06 measurement set' }
	}
];

function applyDefaults(relPath: string, fm: Frontmatter): Frontmatter {
	const merged: Frontmatter = {};
	for (const { prefix, values } of FM_DEFAULTS) {
		if (prefix === '' || relPath === prefix || relPath.startsWith(prefix + '/')) {
			Object.assign(merged, values);
		}
	}
	Object.assign(merged, fm);
	// js-yaml parses bare YYYY-MM-DD as a Date — normalize back to a string.
	if (merged.last_verified instanceof Date) {
		merged.last_verified = merged.last_verified.toISOString().slice(0, 10);
	}
	return merged;
}

// ── Liquid ───────────────────────────────────────────────────────────────────

// Includes served from memory, keyed the way content refers to them
// ("step.html", "harness/pin-swap.html").
const includes = new Map<string, string>();
for (const [path, raw] of Object.entries(includeFiles)) {
	includes.set(path.replace('/src/liquid/_includes/', ''), raw);
}

const liquid = new Liquid({
	jekyllInclude: true,
	relativeReference: false,
	// Tags on their own line would otherwise leave blank lines behind, and a
	// blank line terminates an HTML block for the markdown parser (breaking
	// e.g. Liquid loops that emit <tr> rows inside a <table>).
	trimTagRight: true,
	greedy: false,
	fs: {
		readFileSync: (file: string) => includes.get(file) ?? '',
		readFile: async (file: string) => includes.get(file) ?? '',
		existsSync: (file: string) => includes.has(file),
		exists: async (file: string) => includes.has(file),
		contains: async () => true,
		resolve: (_root: string, file: string) => file,
		sep: '/',
		dirname: (file: string) => file.split('/').slice(0, -1).join('/')
	}
});
liquid.registerFilter('relative_url', (v: string) => v);
liquid.registerFilter('absolute_url', (v: string) => site.url + v);

// The affiliate-link include mutates page-level Liquid state (accumulating
// footnotes across calls), which include scoping does not reliably support
// outside Jekyll. Handled deterministically here instead.
function expandAffiliateLinks(body: string): string {
	const notes: string[] = [];
	let out = body.replace(
		/\{%-?\s*include affiliate-link\.html\s+url="([^"]+)"\s+text="([^"]+)"\s*-?%\}/g,
		(_m, url: string, text: string) => {
			const tagged = url + (url.includes('?') ? '&' : '?') + 'tag=sorterv2-20';
			notes.push(`<li><a href="${url}" target="_blank" rel="noopener">${text}</a></li>`);
			return (
				`<span class="affiliate-link"><a href="${tagged}" target="_blank" rel="noopener">${text}</a>` +
				`<sup class="affiliate-star"><a href="#affiliate-notes" title="Affiliate link — non-affiliate version at the bottom of the page">*</a></sup></span>`
			);
		}
	);
	out = out.replace(/\{%-?\s*include affiliate-footnotes\.html\s*-?%\}/g, () =>
		notes.length
			? `<div class="affiliate-notes" id="affiliate-notes">\n` +
				`<p>* Links marked with an asterisk carry our Amazon affiliate tag — as an Amazon Associate we earn from qualifying purchases. The same listings without the tag:</p>\n` +
				`<ul>\n${notes.join('\n')}\n</ul>\n</div>`
			: ''
	);
	return out;
}

// kramdown heading IALs: `## Title {#explicit-id}`. remark has no attribute
// syntax, so emit the heading as raw HTML with the explicit id.
function expandHeadingIds(body: string): string {
	return body.replace(
		/^(#{1,6})\s+(.+?)\s*\{#([A-Za-z0-9_-]+)\}\s*$/gm,
		(_m, hashes: string, text: string, id: string) =>
			`<h${hashes.length} id="${id}">${text}</h${hashes.length}>`
	);
}

// ── Markdown ─────────────────────────────────────────────────────────────────

const markdown = unified()
	.use(remarkParse)
	.use(remarkGfm)
	.use(remarkRehype, { allowDangerousHtml: true })
	.use(rehypeRaw)
	.use(rehypeSlug)
	.use(rehypeStringify, { allowDangerousHtml: true });

// ── Parts / credits resolution (page-requirements.html, page-author.html) ────

export type ResolvedPart = {
	id: string;
	name: string;
	image?: string;
	page?: string;
	qty?: number;
	notes?: string;
	caption?: string;
	// Screw length in mm, stamped on the corner of the card image. One photo
	// stands in for a whole family of screws, so the length is the one thing it
	// cannot show, the same reason the parts calculator's hardware list carries it.
	length_mm?: number;
	not_in_calc?: boolean;
	// Interchangeable alternative (e.g. socket vs button head): true for a bare
	// tag, or a string naming the alternative. Renders the green "A" badge.
	alternative?: string | boolean;
	missing?: boolean;
};
export type PartsGroup = { category: string; parts: ResolvedPart[] };
export type ResolvedPerson = { name: string; url?: string };

function resolvePeople(ids: unknown): ResolvedPerson[] {
	const values = Array.isArray(ids) ? ids : ids ? [ids] : [];
	return values.map((id) => {
		const person = data.authors?.[id];
		return person ? { name: person.name, url: person.url } : { name: String(id) };
	});
}

function resolveParts(partsNeeded: any[]): { groups: PartsGroup[]; notes: ResolvedPart[] } {
	const catalog = data.parts ?? {};
	const resolved: Array<ResolvedPart & { category: string }> = partsNeeded.map((entry) => {
		const id = typeof entry === 'string' ? entry : entry.part;
		const qty = typeof entry === 'object' ? entry.qty : undefined;
		const part = catalog[id];
		if (!part) return { id, name: id, qty, missing: true, category: 'Other' };
		return {
			id,
			name: part.name,
			image: part.image,
			page: part.page,
			notes: part.notes,
			caption: part.caption,
			length_mm: part.length_mm,
			not_in_calc: part.not_in_calc,
			alternative: part.alternative,
			qty,
			category: part.category ?? 'Other'
		};
	});
	const groups: PartsGroup[] = [];
	for (const p of resolved) {
		let g = groups.find((g) => g.category === p.category);
		if (!g) groups.push((g = { category: p.category, parts: [] }));
		g.parts.push(p);
	}
	return { groups, notes: resolved.filter((p) => p.notes) };
}

// ── Page assembly ────────────────────────────────────────────────────────────

export type Page = {
	url: string;
	fm: Frontmatter;
	html: string;
	authors?: ResolvedPerson[];
	contributors?: ResolvedPerson[];
	parts?: { groups: PartsGroup[]; notes: ResolvedPart[] };
	tools?: string[];
	/** Rendered `warning:` front matter, shown above the parts block so a caveat
	 *  about the whole page is read before its contents. */
	warning?: string;
	ogImage?: string;
};

function urlFor(relPath: string, fm: Frontmatter): string {
	if (fm.permalink) return fm.permalink.endsWith('/') ? fm.permalink : fm.permalink + '/';
	const noExt = relPath.replace(/\.md$/, '');
	if (noExt === 'index') return '/';
	if (noExt.endsWith('/index')) return '/' + noExt.slice(0, -'/index'.length) + '/';
	return '/' + noExt + '/';
}

const sources = new Map<string, { relPath: string; raw: string; fm: Frontmatter }>();
for (const [path, raw] of Object.entries(contentFiles)) {
	const relPath = path.replace('/src/content/', '');
	const { fm } = parseFrontmatter(raw);
	sources.set(urlFor(relPath, fm), { relPath, raw, fm: applyDefaults(relPath, fm) });
}

// Nav items don't carry their own frontmatter (nav.yml is just title/url), so
// stitch each item's `lede` on from the matching content source by URL. This
// rides along with the nav data every page already loads, so search results
// can show a subtitle with no extra fetch.
function withLede(items: NavItem[]): NavItem[] {
	return items.map((item) => ({
		...item,
		lede: sources.get(item.url)?.fm.lede,
		children: item.children ? withLede(item.children) : undefined
	}));
}

export const navSections: NavSection[] = rawNavSections.map((section) => ({
	...section,
	pages: withLede(section.pages),
	groups: section.groups?.map((g) => ({ ...g, pages: withLede(g.pages) }))
}));

const rendered = new Map<string, Page>();

export function allPaths(): string[] {
	return [...sources.keys()].map((url) => url.replace(/^\/|\/$/g, ''));
}

export async function getPage(pathParam: string): Promise<Page | null> {
	const url = '/' + (pathParam ? pathParam.replace(/\/$/, '') + '/' : '');
	const cached = rendered.get(url);
	if (cached) return cached;

	const src = sources.get(url);
	if (!src) return null;

	const { fm } = src;
	let { body } = parseFrontmatter(src.raw);
	body = expandAffiliateLinks(body);
	body = expandHeadingIds(body);
	body = await liquid.parseAndRender(body, { site, page: { ...fm, url } });
	const html = String(await markdown.process(body));

	const page: Page = { url, fm, html };

	const authorIds = Array.isArray(fm.authors) ? fm.authors : fm.author ? [fm.author] : [];
	page.authors = resolvePeople(authorIds);
	page.contributors = resolvePeople(fm.contributors).filter(
		(contributor) => !page.authors?.some((author) => author.name === contributor.name)
	);
	if (fm.parts_needed) page.parts = resolveParts(fm.parts_needed);
	if (fm.tools_needed) page.tools = fm.tools_needed;
	if (fm.warning) {
		const warned = await liquid.parseAndRender(String(fm.warning), { site, page: { ...fm, url } });
		page.warning = String(await markdown.process(warned));
	}

	const img = html.match(/<img[^>]*src="([^"]+)"/);
	if (img) page.ogImage = img[1].startsWith('http') ? img[1] : site.url + img[1];

	rendered.set(url, page);
	return page;
}
