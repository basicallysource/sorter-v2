import { redirect } from '@sveltejs/kit';

import type { PageLoad } from './$types';

// Server health is a part of the Server page now.
export const load: PageLoad = () => {
	throw redirect(308, '/admin/server');
};
