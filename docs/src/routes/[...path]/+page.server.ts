import { error } from '@sveltejs/kit';
import { allPaths, getPage } from '$lib/server/content';
import type { EntryGenerator, PageServerLoad } from './$types';

export const entries: EntryGenerator = () => allPaths().map((path) => ({ path }));

export const load: PageServerLoad = async ({ params }) => {
	const page = await getPage(params.path);
	if (!page) error(404, 'Not found');
	return { page };
};
