import { error } from '@sveltejs/kit';
import { allUids, resolveUid } from '$lib/filament';
import type { EntryGenerator, PageLoad } from './$types';

// The page behind the id stamped into a print: /u/<uid>. One prerendered page
// per uid the catalog has ever minted -- current parts, superseded versions,
// candidates, assemblies, hardware, laser-cut sheets -- so the four characters
// on a part found in a drawer a year from now still say what it is. Uids are
// lowercase in the catalog; the search palette lowercases what is typed and
// resolves it before navigating, so this route's 404 is now the rare case.
export const prerender = true;

export const entries: EntryGenerator = () => allUids().map((uid) => ({ uid }));

export const load: PageLoad = ({ params }) => {
	const match = resolveUid(params.uid);
	if (!match) error(404, `No part carries the id ${params.uid}`);
	return { uid: params.uid.toLowerCase(), match };
};
