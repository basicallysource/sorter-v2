// Words for what a profile page shows, kept in one place so the profile's
// page, its list and the notice that a version changed all say it the same way.

import { relativeTime } from '$lib/time';

// Who saved a version, in words: "in the editor", "by Assistant (API key)",
// "by the editor's chat", "by Hive". Versions from before Hive recorded it
// have no origin, and nothing is said.
export function savedBy(via: string | null | undefined, keyName: string | null | undefined): string | null {
	switch (via) {
		case 'web':
			return 'in the editor';
		case 'api':
			return keyName ? `by ${keyName} (API key)` : 'by an API key';
		case 'assistant':
			return "by the editor's chat";
		case 'system':
			return 'by Hive';
		default:
			return null;
	}
}

// "Saved 2 hours ago in the editor".
export function savedLine(version: {
	created_at: string;
	created_via: string | null;
	created_via_key_name: string | null;
}): string {
	const by = savedBy(version.created_via, version.created_via_key_name);
	return `Saved ${relativeTime(version.created_at)}${by ? ` ${by}` : ''}`;
}

export function plural(count: number, one: string, many = `${one}s`): string {
	return `${count.toLocaleString('en-US')} ${count === 1 ? one : many}`;
}

// Where a kit's lines came from.
export function kitSource(kit: { source: string; set_num: string | null }): string {
	if (kit.source === 'set') return kit.set_num ? `From set ${kit.set_num}` : 'From a LEGO set';
	if (kit.source === 'bricklink') return 'From a BrickLink list';
	return 'Made by hand';
}
