import { redirect } from '@sveltejs/kit';

// StallGuard moved to a tab on each motor's page; this address keeps working.
export function load() {
	throw redirect(307, '/settings/chute/stallguard');
}
