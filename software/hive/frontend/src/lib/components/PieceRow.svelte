<script lang="ts">
	import { api, type ColorLabelPieceCard } from '$lib/api';
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

<button
	{id}
	type="button"
	onclick={() => onOpen(card)}
	aria-pressed={selected}
	class="flex w-full items-center gap-3 px-(--pad-panel) py-2 text-left {selected ? 'bg-primary-soft' : 'hover:bg-hover'}"
>
	<div class="flex size-10 shrink-0 items-center justify-center rounded-item {card.thumb_seq != null ? '' : 'bg-well'}">
		{#if card.thumb_seq != null}
			<img
				src={api.colorLabelImageUrl(card.machine_id, card.piece_uuid, card.thumb_seq)}
				alt={card.part.part_name ?? 'piece'}
				loading="lazy"
				class="size-10 object-contain"
			/>
		{/if}
	</div>
	<div class="min-w-0 flex-1">
		<div class="flex items-center gap-1.5">
			<span class="truncate text-sm text-ink" title={card.part.part_name ?? card.part.part_id ?? ''}>
				{card.part.part_name || card.part.part_id || 'Unidentified'}
			</span>
			{#if card.part.part_id}<span class="shrink-0 font-mono text-sm text-ink-muted">{card.part.part_id}</span>{/if}
		</div>
		<div class="truncate text-sm text-ink-muted">{card.machine_name ?? 'Machine'}</div>
	</div>
	<div class="num flex shrink-0 items-center gap-3 text-sm text-ink-muted">
		{#if card.has_candidates}
			<span class="flex text-info-ink" title="Has same-piece candidate crops"><Sparkles size={14} /></span>
		{/if}
		<span class="flex items-center gap-1" title="Color labels"><Palette size={14} />{card.color_label_count}</span>
		<span class="flex items-center gap-1" title="Same-piece labels"><Link2 size={14} />{card.crop_link_count}</span>
		<span class="flex size-5 items-center justify-center">
			{#if card.my_color}
				<span class="flex rounded-badge bg-success p-0.5 text-on-success" title="You labeled this"><Check size={14} /></span>
			{/if}
		</span>
	</div>
</button>
