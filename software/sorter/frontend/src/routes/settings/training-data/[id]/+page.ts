import { redirect } from '@sveltejs/kit';

// Training runs moved into Settings > Data; this address keeps working.
export function load({ params }) {
	throw redirect(307, `/settings/data/training/${params.id}`);
}
