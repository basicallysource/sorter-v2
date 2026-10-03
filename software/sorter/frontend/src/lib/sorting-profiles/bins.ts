// What the profile pages work out from a profile's bins and versions: how to
// group the bins for showing, when Hive has a newer version than a machine
// runs, and the words for where a version came from.
import type { Bin } from '$lib/components/ui/ProfileBin.svelte';
import type {
	ProfileWarning,
	SortingProfileFallbackMode,
	SortingProfileSummary,
	SortingProfileVersionSummary
} from './types';

export type BinEntry = { id: string; bin: Bin; number?: number; warnings: string[] };

export type BinGroups = {
	// Rules and kits in the order a piece meets them: the first to take it wins.
	// A bin from a version saved before bins were described has no kind and no
	// place in an order, so it is a plain bin here with no number.
	rules: BinEntry[];
	// The bins the fallback makes for the parts no rule takes: one per
	// category or per color, which can be hundreds.
	leftover: BinEntry[];
	// Everything else.
	rest: BinEntry[];
};

export function groupBins(
	categories: Record<string, Bin> | null | undefined,
	order: string[] | null | undefined,
	warnings: ProfileWarning[] | null | undefined
): BinGroups {
	const all = categories ?? {};
	const ordered = order ?? [];
	const ids = [
		...ordered.filter((id) => id in all),
		...Object.keys(all).filter((id) => !ordered.includes(id))
	];
	const groups: BinGroups = { rules: [], leftover: [], rest: [] };
	for (const id of ids) {
		const bin = all[id];
		if (!bin || typeof bin !== 'object') continue;
		const entry: BinEntry = {
			id,
			bin,
			warnings: (warnings ?? []).filter((w) => w.rule_id === id).map((w) => w.message)
		};
		if (bin.kind === 'fallback') groups.leftover.push(entry);
		else if (bin.kind === 'default') groups.rest.push(entry);
		else {
			if (bin.kind) entry.number = groups.rules.length + 1;
			groups.rules.push(entry);
		}
	}
	return groups;
}

// What the fallback does with a part no rule takes. BrickLink categories win
// over Rebrickable ones, and either over color, as Hive reads the three.
export function leftoverSentence(mode: SortingProfileFallbackMode | null | undefined): string {
	if (mode?.bricklink_categories)
		return 'Parts no rule takes go to a bin for their BrickLink category.';
	if (mode?.rebrickable_categories)
		return 'Parts no rule takes go to a bin for their Rebrickable category.';
	if (mode?.by_color) return 'Parts no rule takes go to a bin for their color.';
	return 'Parts no rule takes go to Everything else.';
}

// The version of a profile Hive has that a machine on `current` could be
// updated to: the newest one for the profile's owner, the newest published one
// for anyone else. Null when the machine has it.
export function newerVersion(
	profile: SortingProfileSummary,
	current: number | null | undefined
): number | null {
	const latest = profile.is_owner
		? profile.latest_version_number
		: profile.latest_published_version_number;
	if (latest == null || current == null) return null;
	return latest > current ? latest : null;
}

// Where a version came from, for "Updated 3 minutes ago by the assistant".
export function savedBy(
	version:
		| Pick<SortingProfileVersionSummary, 'created_via' | 'created_via_key_name'>
		| null
		| undefined
): string | null {
	switch (version?.created_via) {
		case 'assistant':
			return 'by the assistant';
		case 'api':
			return version.created_via_key_name
				? `with the key “${version.created_via_key_name}”`
				: 'with an API key';
		case 'system':
			return 'by Hive';
		case 'web':
			return 'in Hive';
		default:
			return null;
	}
}

// The person's own profiles first, then Hive's defaults in their order.
export function ownFirst<T extends { profile: SortingProfileSummary }>(entries: T[]): T[] {
	const own = entries.filter((entry) => !entry.profile.is_default);
	const defaults = entries
		.filter((entry) => entry.profile.is_default)
		.sort(
			(a, b) =>
				(a.profile.default_rank ?? Number.MAX_SAFE_INTEGER) -
				(b.profile.default_rank ?? Number.MAX_SAFE_INTEGER)
		);
	return [...own, ...defaults];
}
