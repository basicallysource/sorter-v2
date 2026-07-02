import { bricklinkParts } from '$lib/stores/bricklinkParts.svelte';
import { sortingProfileStore } from '$lib/stores/sortingProfile.svelte';
import type { BinContentItem } from './types';

export function previewUrl(item: Pick<BinContentItem, 'part_id' | 'brickognize_preview_url' | 'thumbnail' | 'top_image' | 'bottom_image'> | null): string | null {
	if (!item) return null;
	if (item.part_id) {
		const partInfo = bricklinkParts.get(item.part_id);
		if (partInfo?.image_url) return partInfo.image_url;
		if (partInfo?.thumbnail_url) return partInfo.thumbnail_url;
	}
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
	const partInfo = bricklinkParts.get(item.part_id);
	return partInfo?.name || item.part_id || 'Unknown part';
}

export function itemSecondaryText(item: BinContentItem): string {
	const bits = [item.part_id, item.color_name].filter((value): value is string => Boolean(value));
	return bits.join(' · ') || 'Unrecognized item';
}

export function formatCategoryName(categoryId: string | null | undefined): string {
	if (!categoryId) return '';
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
