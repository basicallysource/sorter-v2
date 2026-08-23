// A time-based diff of the catalog: what changed between a date and now.
//
// This tracks the catalog, never the reader. Nothing here knows or stores what
// anybody has printed; the date is one end of a comparison and that is all.
//
// Every part carries `created_at`, `updated_at` and, once it has been revised,
// a `versions` list with a date and a message per version. Given one date, a
// part falls into exactly one bucket:
//
//   new      — it did not exist in the catalog then
//   revised  — a new design revision was released after that date
//   touched  — same design revision (no version bump), but its catalog entry
//              changed: description, quantities, colour, pictures, or a
//              re-export of identical geometry. The geometry is unchanged.
//
// The split matters because the third is not a design change at all. `touched`
// is deliberately kept apart rather than folded into "changed", so nobody
// reads a listing edit as a part that moved.

import {
	PARTS,
	type Part,
	type PartCandidate,
	type PartVersion
} from '$lib/filament';

export type UpdateKind = 'new' | 'revised' | 'touched';

export type PartUpdate = {
	part: Part;
	kind: UpdateKind;
	/** The date that put this part in the list — newest qualifying event. */
	date: string;
	/** Versions released after the cutoff, oldest first (revised only). */
	newVersions: PartVersion[];
	/** The revision that was current on the cutoff date, for comparison. */
	atCutoff: PartVersion | null;
};

export type CandidateUpdate = { part: Part; candidate: PartCandidate };

/** ISO `YYYY-MM-DD` comparison is lexicographic, so no Date parsing (and no
 *  timezone shifting a date by a day) is needed anywhere in here. */
const isAfter = (date: string | undefined | null, cutoff: string) => !!date && date > cutoff;

function versionAt(part: Part, cutoff: string): PartVersion | null {
	const past = (part.versions ?? []).filter((v) => !isAfter(v.date, cutoff));
	return past.length ? past[past.length - 1] : null;
}

/** Every printed part that appeared or moved after `cutoff`, newest first.
 *  An empty or malformed cutoff yields nothing rather than the whole catalog. */
export function partUpdatesSince(cutoff: string, parts: Part[] = PARTS): PartUpdate[] {
	if (!/^\d{4}-\d{2}-\d{2}$/.test(cutoff)) return [];
	const out: PartUpdate[] = [];
	for (const part of parts) {
		if (isAfter(part.created_at, cutoff)) {
			out.push({ part, kind: 'new', date: part.created_at, newVersions: [], atCutoff: null });
			continue;
		}
		const newVersions = (part.versions ?? []).filter((v) => isAfter(v.date, cutoff));
		if (newVersions.length) {
			out.push({
				part,
				kind: 'revised',
				date: newVersions[newVersions.length - 1].date,
				newVersions,
				atCutoff: versionAt(part, cutoff)
			});
			continue;
		}
		if (isAfter(part.updated_at, cutoff))
			out.push({ part, kind: 'touched', date: part.updated_at, newVersions: [], atCutoff: null });
	}
	return out.sort(
		(a, b) => b.date.localeCompare(a.date) || a.part.name.localeCompare(b.part.name)
	);
}

/** Candidates raised since the cutoff: revisions under test for a part's slot.
 *  Not part of any build, and carrying no version number, but a change to the
 *  catalog in the window like any other. */
export function candidatesSince(cutoff: string, parts: Part[] = PARTS): CandidateUpdate[] {
	if (!/^\d{4}-\d{2}-\d{2}$/.test(cutoff)) return [];
	const out: CandidateUpdate[] = [];
	for (const part of parts)
		for (const candidate of part.candidates ?? [])
			if (isAfter(candidate.created_at, cutoff) && !candidate.rejected_at)
				out.push({ part, candidate });
	return out.sort(
		(a, b) =>
			b.candidate.created_at.localeCompare(a.candidate.created_at) ||
			a.part.name.localeCompare(b.part.name)
	);
}

/** The oldest date in the catalog — the cutoff at which everything is "new". */
export function catalogStart(parts: Part[] = PARTS): string {
	return parts.reduce((min, p) => (p.created_at < min ? p.created_at : min), parts[0]?.created_at ?? '');
}

/** `today` minus `days`, as `YYYY-MM-DD`, in the viewer's own calendar. */
export function daysAgo(days: number, today: Date = new Date()): string {
	const d = new Date(today.getFullYear(), today.getMonth(), today.getDate() - days);
	const pad = (n: number) => String(n).padStart(2, '0');
	return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
