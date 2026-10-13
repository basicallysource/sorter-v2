<script lang="ts">
	import { api, type ColorLabelPieceCard } from '$lib/api';
	import { band, bandText, percent } from '$lib/colorModels';
	import Card from './Card.svelte';
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
		// Picked for a bulk action: a box on the picture; shift-click picks a range.
		picked?: boolean;
		onPick?: (card: ColorLabelPieceCard, range: boolean) => void;
		// The pointer rests on it (or leaves): the page fetches it ahead.
		onHover?: (card: ColorLabelPieceCard | null) => void;
	};
	let { card, selected = false, id, onOpen, picked = false, onPick, onHover }: Props = $props();
</script>

<div {id} role="presentation" onpointerenter={() => onHover?.(card)} onpointerleave={() => onHover?.(null)}>
	<Card label={card.part.part_name || card.part.part_id || 'Unidentified piece'} onclick={() => onOpen(card)} padded={false} class="overflow-hidden">
		<!-- The crop is shown whole in a square, on the card's own fill: a crop is
		     rarely square, and a backdrop would show as bars beside it. -->
		<div class="relative flex aspect-square items-center justify-center {card.thumb_seq != null ? '' : 'bg-well'}">
			{#if card.thumb_seq != null}
				<img
					src={card.thumb_url ?? api.colorLabelImageUrl(card.machine_id, card.piece_uuid, card.thumb_seq)}
					alt={card.part.part_name ?? 'piece'}
					loading="lazy"
					class="absolute inset-0 size-full object-contain"
				/>
			{:else}
				<span class="text-sm text-ink-muted">No picture</span>
			{/if}
			{#if card.has_candidates || card.has_palette || card.has_training_label}
				<span class="absolute top-1 left-1 flex gap-1">
					{#if card.has_candidates}
						<span class="flex rounded-badge bg-info p-0.5 text-on-info" title="Has same-piece candidate crops"><Sparkles size={14} /></span>
					{/if}
					{#if card.has_palette}
						<span
							class="flex items-center gap-1 rounded-badge bg-scrim px-1 py-0.5 text-xs leading-none font-medium text-white"
							title="The color reference palette was in view near this piece"><SwatchBook size={12} />Palette</span
						>
					{/if}
					{#if card.has_training_label}
						<span
							class="flex items-center gap-1 rounded-badge bg-scrim px-1 py-0.5 text-xs leading-none font-medium text-white"
							title="A training run labeled this piece's color"><GraduationCap size={12} />Training</span
						>
					{/if}
				</span>
			{/if}
			{#if card.my_color}
				<span class="absolute top-1 right-1 flex rounded-badge bg-success p-0.5 text-on-success" title="You labeled this"
					><Check size={14} /></span
				>
			{/if}
			{#if onPick}
				<span class="absolute bottom-1 left-1 flex rounded-badge bg-surface p-1">
					<Checkbox checked={picked} aria-label="Pick this piece" onclick={(e: MouseEvent) => onPick?.(card, e.shiftKey)} />
				</span>
			{/if}
		</div>
		<div class="flex flex-col gap-1 px-2.5 py-2 {selected ? 'bg-primary-soft' : ''}">
			<div class="truncate text-sm {selected ? 'font-medium text-primary-ink' : 'text-ink'}" title={card.part.part_name ?? card.part.part_id ?? ''}>
				{card.part.part_name || card.part.part_id || 'Unidentified'}
			</div>
			{#if card.model_color}
				{@const mc = card.model_color}
				<div class="flex min-w-0 text-sm text-ink" title={`The model's color: ${mc.color_name ?? mc.color_id}, ${percent(mc.confidence)} sure`}>
					<ColorChip name={mc.color_name ?? `Color ${mc.color_id}`} rgb={mc.rgb} class="min-w-0 flex-1" />
				</div>
			{/if}
			<div class="num flex items-center gap-2 text-sm text-ink-muted">
				{#if card.model_color}
					<!-- With a model chosen, how sure it is takes the counts' place. -->
					<span class="font-medium {bandText(band(card.model_color.confidence))}" title="How sure the model is"
						>{percent(card.model_color.confidence)}</span
					>
				{:else}
					<span class="flex items-center gap-1" title="Color labels"><Palette size={14} />{card.color_label_count}</span>
					<span class="flex items-center gap-1" title="Same-piece labels"><Link2 size={14} />{card.crop_link_count}</span>
				{/if}
				<span class="ml-auto truncate">{card.machine_name ?? 'Machine'}</span>
			</div>
		</div>
	</Card>
</div>
