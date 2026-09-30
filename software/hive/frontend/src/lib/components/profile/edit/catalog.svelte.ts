// What the editor looks things up in: the fields a condition can test, the
// colors and categories a value can be, and the parts a value can name. Each
// list is fetched once, on first use, and kept for the life of the page, so ten
// conditions on colors ask for the colors once. Parts are remembered as they
// are picked or read back from the live preview, and asked for only when a saved
// value is one the editor has not seen.

import {
	api,
	type BinConditions,
	type BrickLinkCategory,
	type ProfileBin,
	type ProfileCatalogCategory,
	type ProfileCatalogColor,
	type ProfileCatalogSearchResult,
	type ProfileField
} from '$lib/api';
import { OP_WORDS } from './fields';

export type PartInfo = {
	name: string;
	imgUrl: string | null;
	bricklinkId: string | null;
	partNum: string | null;
};

// A part condition names its parts by Rebrickable number ("part") or by
// BrickLink ID ("bl_part").
export type PartRef = 'part' | 'bl_part';

export function partKey(ref: PartRef, value: unknown): string {
	return `${ref}:${String(value)}`;
}

// A search result's BrickLink IDs: the catalog keeps them as a list, or as an
// object holding one.
export function bricklinkIdsOf(part: ProfileCatalogSearchResult): string[] {
	const raw = part.external_ids?.BrickLink;
	const list = Array.isArray(raw)
		? raw
		: raw && typeof raw === 'object' && Array.isArray((raw as { ext_ids?: unknown }).ext_ids)
			? (raw as { ext_ids: unknown[] }).ext_ids
			: [];
	return list.map((id) => String(id)).filter((id) => id.trim() !== '');
}

export function infoFromSearch(part: ProfileCatalogSearchResult): PartInfo {
	return {
		name: part.name,
		imgUrl: part.part_img_url,
		bricklinkId: bricklinkIdsOf(part)[0] ?? null,
		partNum: part.part_num
	};
}

class Catalog {
	fields = $state.raw<ProfileField[]>([]);
	// A field's older name, still found in saved rules, and the field it is now.
	aliases = $state.raw<Record<string, string>>({});
	opWords = $state.raw<Record<string, string>>(OP_WORDS);
	colors = $state.raw<ProfileCatalogColor[]>([]);
	blCategories = $state.raw<BrickLinkCategory[]>([]);
	rbCategories = $state.raw<ProfileCatalogCategory[]>([]);
	parts = $state.raw<Record<string, PartInfo | null>>({});
	// What went wrong the last time a list would not load.
	error = $state<string | null>(null);

	colorById = $derived(new Map(this.colors.map((color) => [color.id, color])));
	blCategoryById = $derived(new Map(this.blCategories.map((category) => [category.id, category])));
	rbCategoryById = $derived(new Map(this.rbCategories.map((category) => [category.id, category])));

	#loads = new Map<string, Promise<void>>();
	#asked = new Set<string>();

	fieldByKey(key: string): ProfileField | undefined {
		return this.fields.find((field) => field.field === key);
	}

	#once(name: string, load: () => Promise<void>): Promise<void> {
		let pending = this.#loads.get(name);
		if (!pending) {
			pending = load().catch((e: unknown) => {
				// Forget it, so the next use tries again.
				this.#loads.delete(name);
				this.error = (e as { error?: string })?.error ?? 'Could not load the catalog.';
			});
			this.#loads.set(name, pending);
		}
		return pending;
	}

	ensureFields() {
		return this.#once('fields', async () => {
			const res = await api.getProfileFields();
			this.fields = res.fields;
			this.aliases = res.aliases ?? {};
			this.opWords = { ...OP_WORDS, ...res.ops };
		});
	}

	ensureColors() {
		return this.#once('colors', async () => {
			this.colors = (await api.getProfileCatalogColors()).results;
		});
	}

	ensureBlCategories() {
		return this.#once('bl-categories', async () => {
			this.blCategories = (await api.getBrickLinkCategories()).results;
		});
	}

	ensureRbCategories() {
		return this.#once('rb-categories', async () => {
			this.rbCategories = (await api.profileCatalogCategories()).results;
		});
	}

	// --- Parts ----------------------------------------------------------------------

	// undefined: not known yet. null: the catalog has no such part.
	part(ref: PartRef, value: unknown): PartInfo | null | undefined {
		return this.parts[partKey(ref, value)];
	}

	remember(ref: PartRef, value: unknown, info: PartInfo) {
		this.parts = { ...this.parts, [partKey(ref, value)]: info };
	}

	// The parts the live preview names in its conditions, so a saved value shows
	// as a picture and a name without asking for each part on its own.
	learn(bins: Record<string, ProfileBin> | undefined) {
		if (!bins) return;
		const found: Record<string, PartInfo | null> = {};
		const visit = (conditions: BinConditions | undefined) => {
			if (!conditions) return;
			for (const item of conditions.items) {
				const ref = this.fieldByKey(item.field)?.ref;
				if (ref !== 'part' && ref !== 'bl_part') continue;
				for (const value of item.values) {
					if (value.part_num === undefined) continue;
					found[partKey(ref, value.value)] = {
						name: value.label,
						imgUrl: value.img_url ?? null,
						bricklinkId: value.bricklink_id ?? null,
						partNum: value.part_num ?? null
					};
				}
			}
			for (const group of conditions.groups) visit(group);
		};
		for (const bin of Object.values(bins)) visit(bin.conditions);
		if (Object.keys(found).length > 0) this.parts = { ...this.parts, ...found };
	}

	// Ask for one part, once.
	async ensurePart(ref: PartRef, value: unknown) {
		const key = partKey(ref, value);
		if (key in this.parts || this.#asked.has(key)) return;
		this.#asked.add(key);
		try {
			const part = await api.getProfileCatalogPart(String(value));
			this.parts = {
				...this.parts,
				[key]: {
					name: part.name,
					imgUrl: part.img_url,
					bricklinkId: part.bricklink_id,
					partNum: part.part_num
				}
			};
		} catch (e) {
			// A part the catalog does not know is worth saying so; anything else
			// (the network) is worth another try the next time it is shown.
			if ((e as { code?: string })?.code === 'PART_NOT_FOUND') this.parts = { ...this.parts, [key]: null };
			else this.#asked.delete(key);
		}
	}
}

export const catalog = new Catalog();
