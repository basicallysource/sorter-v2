import { error } from '@sveltejs/kit';
import { PARTS, HARDWARE, getPart, getHardware } from '$lib/filament';
import type { EntryGenerator, PageLoad } from './$types';

// One prerendered page per part — the whole point of this route: a static URL a
// link-preview crawler can read, carrying the part's own OpenGraph image + name.
// Every part id is known at build time, so we can enumerate them all.
//
// "Part" here is either half of the unified manifest: a printed part or an
// off-the-shelf (COTS) one. Ids are unique across both, so one URL space covers
// the lot and a link to anything in the calculator resolves the same way.
export const prerender = true;

export const entries: EntryGenerator = () => [...PARTS, ...HARDWARE].map((p) => ({ id: p.id }));

export const load: PageLoad = ({ params }) => {
	const part = getPart(params.id);
	if (part) return { part, hardware: null };

	const hardware = getHardware(params.id);
	if (hardware) return { part: null, hardware };

	error(404, `Unknown part: ${params.id}`);
};
