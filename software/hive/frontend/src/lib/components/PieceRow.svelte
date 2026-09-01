<script lang="ts">
	import { api, type ColorLabelPieceCard } from '$lib/api';
	import Check from 'lucide-svelte/icons/check';
	import Link2 from 'lucide-svelte/icons/link-2';
	import Palette from 'lucide-svelte/icons/palette';
	import Sparkles from 'lucide-svelte/icons/sparkles';

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
	class="flex w-full items-center gap-3 border-b border-border px-2 py-1.5 text-left hover:bg-bg {selected
		? 'bg-primary-light'
		: ''}"
>
	<div class="relative flex h-10 w-10 shrink-0 items-center justify-center bg-bg">
		{#if card.thumb_seq != null}
			<img
				src={api.colorLabelImageUrl(card.machine_id, card.piece_uuid, card.thumb_seq)}
				alt={card.part.part_name ?? 'piece'}
				loading="lazy"
				class="h-10 w-10 bg-transparent object-contain"
			/>
		{:else}
			<span class="text-[10px] text-text-muted">n/a</span>
		{/if}
	</div>

	<div class="min-w-0 flex-1">
		<div class="flex items-center gap-1.5">
			<span class="truncate text-sm text-text" title={card.part.part_name ?? card.part.part_id ?? ''}>
				{card.part.part_name || card.part.part_id || 'Unidentified'}
			</span>
			{#if card.part.part_id}
				<span class="shrink-0 text-xs text-text-muted">#{card.part.part_id}</span>
			{/if}
		</div>
		<div class="truncate text-xs text-text-muted">{card.machine_name ?? 'machine'}</div>
	</div>

	<div class="flex shrink-0 items-center gap-3 text-xs text-text-muted">
		{#if card.has_candidates}
			<span class="flex items-center text-info" title="has same-piece candidate crops">
				<Sparkles size={13} />
			</span>
		{/if}
		<span class="flex items-center gap-1 tabular-nums" title="color labels by users">
			<Palette size={13} />{card.color_label_count}
		</span>
		<span class="flex items-center gap-1 tabular-nums" title="same-piece labels by users">
			<Link2 size={13} />{card.crop_link_count}
		</span>
		<span class="flex h-5 w-5 items-center justify-center">
			{#if card.my_color}
				<span
					class="flex items-center bg-success p-0.5 text-white"
					title="you labeled this"><Check size={12} /></span
				>
			{/if}
		</span>
	</div>
</button>
