import { redirect } from '@sveltejs/kit';

// Sample capture moved into Settings > Data; this address keeps working.
export function load() {
	throw redirect(307, '/settings/data');
}
