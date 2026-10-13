<script lang="ts">
	import { api, type ColorLabelPieceCard } from '$lib/api';
	import { band, bandText, percent } from '$lib/colorModels';
	import Checkbox from './Checkbox.svelte';
	import ColorChip from './ColorChip.svelte';
	import Check from '@lucide/svelte/icons/check';
	import GraduationCap from '@lucide/svelte/icons/graduation-cap';
	import Link2 from '@lucide/svelte/icons/link-2';
	import Palette from '@lucide/svelte/icons/palette';
	import Sparkles from '@lucide/svelte/icons/sparkles';
	import SwatchBook from '@lucide/svelte/icons/swatch-book';

	type Props = {
		card: ColorLabelPieceCard;
		selected?: boolean;
		id?: string;
		onOpen: (card: ColorLabelPieceCard) => void;
		// Picked for a bulk action: a box before the row; shift-click picks a range.
		picked?: boolean;
		onPick?: (card: ColorLabelPieceCard, range: boolean) => void;
		// The pointer rests on it (or leaves): the page fetches it ahead.
		onHover?: (card: ColorLabelPieceCard | null) => void;
	};
	let { card, selected = false, id, onOpen, picked = false, onPick, onHover }: Props = $props();
</script>

<div
	class="flex items-center {selected ? 'bg-primary-soft' : ''}"
	role="presentation"
	onpointerenter={() => onHover?.(card)}
	onpointerleave={() => onHover?.(null)}
>
{#if onPick}
	<span class="flex shrink-0 pl-(--pad-panel)">
		<Checkbox checked={picked} aria-label="Pick this piece" onclick={(e: MouseEvent) => onPick?.(card, e.shiftKey)} />
	</span>
{/if}
<button
	{id}
	type="button"
	onclick={() => onOpen(card)}
	aria-pressed={selected}
	class="flex min-w-0 flex-1 items-center gap-3 px-(--pad-panel) py-2 text-left {selected ? '' : 'hover:bg-hover'}"
>
	<div class="flex size-10 shrink-0 items-center justify-center rounded-item {card.thumb_seq != null ? '' : 'bg-well'}">
		{#if card.thumb_seq != null}
			<img
				src={card.thumb_url ?? api.colorLabelImageUrl(card.machine_id, card.piece_uuid, card.thumb_seq)}
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
	{#if card.model_color}
		{@const mc = card.model_color}
		<div class="flex w-44 shrink-0 items-center gap-1.5 text-sm text-ink" title={`The model's color: ${mc.color_name ?? mc.color_id}, ${percent(mc.confidence)} sure`}>
			<ColorChip name={mc.color_name ?? `Color ${mc.color_id}`} rgb={mc.rgb} class="min-w-0 flex-1" />
			<span class="num shrink-0 font-medium {bandText(band(mc.confidence))}">{percent(mc.confidence)}</span>
		</div>
	{/if}
	<div class="num flex shrink-0 items-center gap-3 text-sm text-ink-muted">
		{#if card.has_training_label}
			<span class="flex text-info-ink" title="A training run labeled this piece's color"><GraduationCap size={14} /></span>
		{/if}
		{#if card.has_palette}
			<span class="flex text-info-ink" title="The color reference palette was in view near this piece"><SwatchBook size={14} /></span>
		{/if}
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
</div>
