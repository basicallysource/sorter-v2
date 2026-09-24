// How finished the hardware instructions are, counted at build time from the
// pages themselves rather than written into prose that nobody updates.
//
// The convention this reads is the one every hardware page already follows: a
// `warning:` in the frontmatter means the page is an unverified first draft,
// and its absence means somebody has built from it. Landing pages and
// references are excluded, because "verified on a real machine" only means
// something for a page with steps on it (`type: how-to`).
//
// Add or verify a page and this moves on the next build. Same idea as
// ./build-scale.ts, which computes the whole-machine figures from the catalog.
import yaml from 'js-yaml';

const hardwarePages = import.meta.glob('/src/content/hardware/**/*.md', {
	query: '?raw',
	import: 'default',
	eager: true
}) as Record<string, string>;

const FRONTMATTER = /^---\r?\n([\s\S]*?)\r?\n---/;

let howTo = 0;
let drafts = 0;

for (const raw of Object.values(hardwarePages)) {
	const m = FRONTMATTER.exec(raw);
	if (!m) continue;
	let fm: Record<string, any>;
	try {
		fm = (yaml.load(m[1]) as Record<string, any>) ?? {};
	} catch {
		// A page whose frontmatter will not parse is not a page we can classify.
		// content.ts tolerates these too; skipping one only makes the count
		// smaller, never wrong about a page it did count.
		continue;
	}
	if (fm.type !== 'how-to') continue;
	howTo++;
	if (fm.warning) drafts++;
}

/** What `/getting-started/` renders when it tells a newcomer how far along the
 *  instructions are. `verified` + `drafts` === `how_to`. */
export const docsStatus = {
	how_to: howTo,
	verified: howTo - drafts,
	drafts
};
