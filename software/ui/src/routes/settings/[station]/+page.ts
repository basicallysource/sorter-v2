import { error, redirect } from '@sveltejs/kit';
import { getStationPageConfig } from '$lib/settings/stations';

const aliases: Record<string, string> = {
	cameras: '/settings/c-channel-2',
	zones: '/settings/c-channel-2',
	runtime: '/settings'
};

export function load({ params }) {
	const alias = aliases[params.station];
	if (alias) {
		throw redirect(307, alias);
	}

	const station = getStationPageConfig(params.station);
	if (!station) {
		throw error(404, 'Unknown settings page');
	}

	return { station };
}
