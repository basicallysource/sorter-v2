<script lang="ts">
	import { api, type ColorLabelPieceCard } from '$lib/api';
	import Card from './Card.svelte';
	import Check from '@lucide/svelte/icons/check';
	import Link2 from '@lucide/svelte/icons/link-2';
	import Palette from '@lucide/svelte/icons/palette';
	import Sparkles from '@lucide/svelte/icons/sparkles';

	type Props = {
		card: ColorLabelPieceCard;
		selected?: boolean;
		id?: string;
		onOpen: (card: ColorLabelPieceCard) => void;
	};
	let { card, selected = false, id, onOpen }: Props = $props();
</script>

<div {id}>
	<Card label={card.part.part_name || card.part.part_id || 'Unidentified piece'} onclick={() => onOpen(card)} padded={false} class="overflow-hidden">
		<!-- The crop is shown whole in a square, on the card's own fill: a crop is
		     rarely square, and a backdrop would show as bars beside it. -->
		<div class="relative flex aspect-square items-center justify-center {card.thumb_seq != null ? '' : 'bg-well'}">
			{#if card.thumb_seq != null}
				<img
					src={api.colorLabelImageUrl(card.machine_id, card.piece_uuid, card.thumb_seq)}
					alt={card.part.part_name ?? 'piece'}
					loading="lazy"
					class="absolute inset-0 size-full object-contain"
				/>
			{:else}
				<span class="text-sm text-ink-muted">No picture</span>
			{/if}
			{#if card.has_candidates}
				<span class="absolute top-1 left-1 flex rounded-badge bg-info p-0.5 text-on-info" title="Has same-piece candidate crops"
					><Sparkles size={14} /></span
				>
			{/if}
			{#if card.my_color}
				<span class="absolute top-1 right-1 flex rounded-badge bg-success p-0.5 text-on-success" title="You labeled this"
					><Check size={14} /></span
				>
			{/if}
		</div>
		<div class="flex flex-col gap-1 px-2.5 py-2 {selected ? 'bg-primary-soft' : ''}">
			<div class="truncate text-sm {selected ? 'font-medium text-primary-ink' : 'text-ink'}" title={card.part.part_name ?? card.part.part_id ?? ''}>
				{card.part.part_name || card.part.part_id || 'Unidentified'}
			</div>
			<div class="num flex items-center gap-2 text-sm text-ink-muted">
				<span class="flex items-center gap-1" title="Color labels"><Palette size={14} />{card.color_label_count}</span>
				<span class="flex items-center gap-1" title="Same-piece labels"><Link2 size={14} />{card.crop_link_count}</span>
				<span class="ml-auto truncate">{card.machine_name ?? 'Machine'}</span>
			</div>
		</div>
	</Card>
</div>
