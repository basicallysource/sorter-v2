import { findLegoColor } from '$lib/pieces/colors';
import { sortingProfileStore } from '$lib/stores/sortingProfile.svelte';
import { BIN_KEY_LABELS, parseBinKey, type BinKeyComponent } from './binKey';
import { partName } from './partNames.svelte';
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

function binKeyPartLabel(component: BinKeyComponent, value: string): string {
	if (component === 'category') return formatCategoryName(value);
	if (component === 'color') {
		if (value === 'any_color') return 'Any color';
		return findLegoColor(value, null)?.name ?? `${BIN_KEY_LABELS.color} ${value}`;
	}
	const name = partName(value);
	return name ? `${name} (${value})` : `${BIN_KEY_LABELS.part} ${value}`;
}

// A bin is named by a profile category, a part, a color or a mix of them
// (see binKey.ts): "Bricks", "Part 3001", "Red", "Bricks · Red".
export function formatCategoryName(categoryId: string | null | undefined): string {
	if (!categoryId) return '';
	const key = parseBinKey(categoryId);
	if (key) {
		return (Object.entries(key) as [BinKeyComponent, string][])
			.map(([component, value]) => binKeyPartLabel(component, value))
			.join(' · ');
	}
	const mapped = sortingProfileStore.getCategoryName(categoryId);
	const value = mapped ?? categoryId;
	if (value.toLowerCase() === 'misc') return 'Misc';
	return value;
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
