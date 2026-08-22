/**
 * How each kind of result looks. One table, because the whole point is that a
 * part, a superseded version of that part and a rejected test print of it are
 * three different answers that carry the same name — the chip and the icon are
 * the only things telling them apart, so they have to be decided together.
 *
 * Colour carries state rather than category: current things are inked, history
 * is grey, anything under test is amber. Category is carried by the icon and
 * the word.
 */
import { Bolt, Box, Boxes, FileText, FlaskConical, Folder, History, Ruler, Scissors } from 'lucide-svelte';
import type { ComponentType } from 'svelte';
import type { ResultKind } from '$lib/search';

export type KindStyle = {
	icon: ComponentType;
	/** Classes for the chip: border, background, text. */
	chip: string;
	/** Classes for the icon square to the left of the row. */
	mark: string;
};

const CURRENT_PART = 'border-primary/40 bg-primary/[0.07] text-primary';
const CURRENT_ASM = 'border-success/40 bg-success/[0.07] text-success';
const HISTORIC = 'border-border bg-[var(--color-bg)] text-text-muted';
const TESTING = 'border-warning/60 bg-warning/[0.12] text-warning-dark';
const THING = 'border-border bg-[var(--color-bg)] text-text';

export const KIND_STYLES: Record<ResultKind, KindStyle> = {
	part: { icon: Box, chip: CURRENT_PART, mark: 'text-primary' },
	'part-version': { icon: History, chip: HISTORIC, mark: 'text-text-muted' },
	'part-candidate': { icon: FlaskConical, chip: TESTING, mark: 'text-warning-dark' },
	assembly: { icon: Boxes, chip: CURRENT_ASM, mark: 'text-success' },
	'assembly-version': { icon: History, chip: HISTORIC, mark: 'text-text-muted' },
	'assembly-candidate': { icon: FlaskConical, chip: TESTING, mark: 'text-warning-dark' },
	hardware: { icon: Bolt, chip: THING, mark: 'text-text' },
	lasercut: { icon: Scissors, chip: THING, mark: 'text-text' },
	framing: { icon: Ruler, chip: THING, mark: 'text-text' },
	section: { icon: Folder, chip: HISTORIC, mark: 'text-text-muted' },
	page: { icon: FileText, chip: HISTORIC, mark: 'text-text-muted' }
};
