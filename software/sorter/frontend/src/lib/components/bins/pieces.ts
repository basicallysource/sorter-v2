import { sortingProfileStore } from '$lib/stores/sortingProfile.svelte';
import { currentPalette } from '$lib/pieces/palette.svelte';
import type { BinContentItem } from './types';

export function previewUrl(item: Pick<BinContentItem, 'part_id' | 'brickognize_preview_url' | 'thumbnail' | 'top_image' | 'bottom_image'> | null): string | null {
	if (!item) return null;
	if (item.brickognize_preview_url) return item.brickognize_preview_url;
	if (item.thumbnail) return `data:image/jpeg;base64,${item.thumbnail}`;
	if (item.top_image) return `data:image/jpeg;base64,${item.top_image}`;
	if (item.bottom_image) return `data:image/jpeg;base64,${item.bottom_image}`;
	return null;
}

export function pieceTooltip(item: BinContentItem): string {
	const label = item.part_id ? `${item.part_id}${item.color_name ? ` · ${item.color_name}` : ''}` : 'Unknown part';
	const status = item.classification_status ? ` (${item.classification_status})` : '';
	return `${label}${status}`;
}

export function itemDisplayName(item: BinContentItem): string {
	return item.part_id || 'Unknown part';
}

export function itemSecondaryText(item: BinContentItem): string {
	const bits = [item.part_id, item.color_name].filter((value): value is string => Boolean(value));
	return bits.join(' · ') || 'Unrecognized item';
}

export function formatCategoryName(categoryId: string | null | undefined): string {
	if (!categoryId) return '';
	const mapped = sortingProfileStore.getCategoryName(categoryId);
	if (mapped) {
		if (mapped.toLowerCase() === 'misc') return 'Misc';
		return mapped;
	}
	// A dynamic part+color category ("3001:15"): the base category's name plus
	// the BrickLink color's name, once the palette is loaded.
	const split = categoryId.match(/^(.*):(\d+)$/);
	if (split) {
		const baseName = sortingProfileStore.getCategoryName(split[1]) ?? split[1];
		const colorName = currentPalette().find((c) => String(c.id) === split[2])?.name;
		if (colorName) return `${baseName} · ${colorName}`;
	}
	if (categoryId.toLowerCase() === 'misc') return 'Misc';
	return categoryId;
}

export function categoryLabel(categoryIds: string[]): string {
	if (!categoryIds || categoryIds.length === 0) return '';
	return categoryIds.map((id) => formatCategoryName(id)).join(', ');
}

export function formatLastSeen(timestamp: number | null | undefined): string {
	if (!timestamp) return 'n/a';
	return new Date(timestamp * 1000).toLocaleString();
}

export function formatRelativeTime(timestamp: number | null | undefined): string | null {
	if (!timestamp) return null;
	const delta = Date.now() / 1000 - timestamp;
	if (delta < 0) return 'just now';
	if (delta < 60) return 'just now';
	if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
	if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`;
	return `${Math.floor(delta / 86400)}d ago`;
}
