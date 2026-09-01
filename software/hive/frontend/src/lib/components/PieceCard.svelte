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
	class="group flex flex-col border bg-surface p-2 text-left hover:border-primary {selected
		? 'border-primary ring-1 ring-primary'
		: 'border-border'}"
>
	<div class="relative flex h-24 w-full items-center justify-center bg-bg">
		{#if card.thumb_seq != null}
			<img
				src={api.colorLabelImageUrl(card.machine_id, card.piece_uuid, card.thumb_seq)}
				alt={card.part.part_name ?? 'piece'}
				loading="lazy"
				class="h-24 w-full bg-transparent object-contain"
			/>
		{:else}
			<span class="text-xs text-text-muted">no image</span>
		{/if}
		{#if card.has_candidates}
			<span
				class="absolute left-1 top-1 flex items-center bg-info/80 p-0.5 text-white"
				title="has same-piece candidate crops"><Sparkles size={11} /></span
			>
		{/if}
		{#if card.my_color}
			<span
				class="absolute right-1 top-1 flex items-center bg-success p-0.5 text-white"
				title="you labeled this"><Check size={12} /></span
			>
		{/if}
	</div>
	<div
		class="mt-1.5 truncate text-sm text-text"
		title={card.part.part_name ?? card.part.part_id ?? ''}
	>
		{card.part.part_name || card.part.part_id || 'Unidentified'}
	</div>
	<div class="mt-1 flex items-center gap-2 text-xs text-text-muted">
		<span class="flex items-center gap-1" title="color labels by users">
			<Palette size={13} />{card.color_label_count}
		</span>
		<span class="flex items-center gap-1" title="same-piece labels by users">
			<Link2 size={13} />{card.crop_link_count}
		</span>
		<span class="ml-auto truncate">· {card.machine_name ?? 'machine'}</span>
	</div>
</button>
