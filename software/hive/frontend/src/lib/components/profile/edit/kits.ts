// What a kit rule collects, as lines to show: a kit's own parts, or for a rule
// made before kits, the set's inventory or the parts the rule carried.

import { api, type CustomSetPart, type Kit } from '$lib/api';
import { kitSource } from '$lib/profile-display';
import { catalog } from './catalog.svelte';
import type { Rule } from './rules';

export type KitLine = {
	key: string;
	name: string;
	imgUrl: string | null;
	bricklinkId: string | null;
	partNum: string | null;
	color: { name: string | null; rgb: string | null } | null;
	quantity: number;
};

export type KitContents = {
	lines: KitLine[];
	// The kit itself, when the rule names one (a rule from before kits has none).
	kit: Kit | null;
};

const ANY_COLOR = -1;

// One read of each kit at a time: the editor and the list beside it both want
// the same kit, and ask again only when `key` says the page has been away.
const reads = new Map<string, { key: number; kit: Promise<Kit> }>();

function readKit(id: string, key: number): Promise<Kit> {
	const hit = reads.get(id);
	if (hit && hit.key === key) return hit.kit;
	const kit = api.getKit(id);
	reads.set(id, { key, kit });
	kit.catch(() => reads.delete(id));
	return kit;
}

function colorOf(colorId: number | null | undefined, name: string | null | undefined, rgb?: string | null) {
	if (colorId === null || colorId === undefined || colorId === ANY_COLOR) return { name: 'Any color', rgb: null };
	return { name: name ?? catalog.colorById.get(colorId)?.name ?? null, rgb: rgb ?? catalog.colorById.get(colorId)?.rgb ?? null };
}

function fromKit(kit: Kit): KitLine[] {
	return kit.parts.map((part, index) => ({
		key: `${part.part_num}-${part.color_id ?? 'any'}-${index}`,
		name: part.part_name ?? part.part_num,
		imgUrl: part.img_url,
		bricklinkId: part.bricklink_id,
		partNum: part.part_num,
		color: part.color_id === null ? { name: 'Any color', rgb: null } : { name: part.color_name, rgb: part.rgb },
		quantity: part.quantity
	}));
}

function fromCustomParts(parts: CustomSetPart[]): KitLine[] {
	return parts.map((part, index) => ({
		key: `${part.part_num}-${part.color_id}-${index}`,
		name: part.part_name ?? part.part_num,
		imgUrl: part.img_url ?? null,
		bricklinkId: part.part_source === 'bricklink' ? part.part_num : null,
		partNum: part.part_source === 'bricklink' ? null : part.part_num,
		color: colorOf(part.color_id, part.color_name),
		quantity: part.quantity
	}));
}

export async function loadKitContents(rule: Rule, key = 0): Promise<KitContents> {
	if (rule.rule_type === 'kit') {
		if (!rule.kit_id) return { lines: [], kit: null };
		const kit = await readKit(rule.kit_id, key);
		return { lines: fromKit(kit), kit };
	}
	const custom = rule.set_source === 'custom' || (rule.custom_parts?.length ?? 0) > 0;
	if (custom) return { lines: fromCustomParts(rule.custom_parts ?? []), kit: null };
	if (!rule.set_num) return { lines: [], kit: null };
	const { inventory } = await api.getProfileCatalogSet(rule.set_num);
	const lines = inventory
		.filter((item) => rule.include_spares || !item.is_spare)
		.map((item, index) => ({
			key: `${item.part_num}-${item.color_id}-${index}`,
			name: item.part_name ?? item.part_num,
			imgUrl: item.part_img_url,
			bricklinkId: null,
			partNum: item.part_num,
			color: colorOf(item.color_id, item.color_name),
			quantity: item.quantity
		}));
	return { lines, kit: null };
}

// Where the lines of a kit, or of a rule from before kits, came from.
export function kitSourceText(kit: Kit | null, rule: Rule): string | null {
	if (kit) return kitSource(kit);
	if (rule.rule_type !== 'set') return null;
	if (rule.set_source === 'custom' || (rule.custom_parts?.length ?? 0) > 0) return 'Made by hand';
	return rule.set_num ? `From set ${rule.set_num}` : null;
}
