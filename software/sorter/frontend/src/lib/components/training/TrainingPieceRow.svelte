<!--
	One piece of a training run as a row: a small crop, the part, the run's
	label as a color, and the machine's own color beside it only when the two
	differ (a piece worth a look), then the time. Clicking the row excludes
	the piece, and clicking it again brings it back; an excluded piece is
	faded and says so.
-->
<script lang="ts">
	import Badge from '$lib/components/ui/Badge.svelte';
	import ColorChip from '$lib/components/ui/ColorChip.svelte';
	import PartImage from '$lib/components/ui/PartImage.svelte';
	import { findLegoColor } from '$lib/pieces/colors';
	import {
		disagrees,
		formatTime,
		formatWhen,
		machineColorId,
		pieceImageUrl,
		type TrainingPiece
	} from '$lib/training/api';

	let {
		piece,
		base,
		pad = 'px-3',
		ontoggle
	}: {
		piece: TrainingPiece;
		base: string;
		// The row's side padding, to line up with what is around it.
		pad?: string;
		ontoggle: (piece: TrainingPiece) => void;
	} = $props();

	function color(id: string, name: string | null) {
		const known = findLegoColor(id, name);
		return { name: known?.name ?? name ?? `Color ${id}`, rgb: known?.hex ?? null };
	}

	const label = $derived(
		piece.training_color_id ? color(piece.training_color_id, piece.training_color_name) : null
	);
	const machineId = $derived(machineColorId(piece));
	const machine = $derived(
		machineId && disagrees(piece)
			? color(machineId, machineId === piece.color_id ? piece.color_name : null)
			: null
	);
	const fade = $derived(piece.training_excluded ? 'opacity-50' : '');
</script>

<button
	type="button"
	aria-pressed={piece.training_excluded}
	title={piece.training_excluded ? 'Excluded. Click to bring it back.' : 'Click to exclude it.'}
	onclick={() => ontoggle(piece)}
	class="flex w-full min-w-0 items-center gap-3 {pad} py-1.5 text-left transition-colors hover:bg-hover active:bg-pressed"
>
	<PartImage src={pieceImageUrl(base, piece)} class="size-10 shrink-0 {fade}" />
	<span class="flex min-w-0 flex-1 flex-col {fade}">
		<span class="flex min-w-0 items-baseline gap-2">
			<span class="truncate text-sm font-medium text-ink">
				{piece.part_name ?? piece.part_id ?? 'Unknown part'}
			</span>
			{#if piece.part_name && piece.part_id}
				<span class="num shrink-0 text-sm text-ink-muted">{piece.part_id}</span>
			{/if}
		</span>
		<span class="flex min-w-0 flex-wrap items-center gap-x-3 text-sm text-ink-muted">
			{#if label}
				<ColorChip name={label.name} rgb={label.rgb} />
			{:else}
				<span>No label</span>
			{/if}
			{#if machine}
				<span
					class="flex min-w-0 items-center gap-1.5 text-warning-ink"
					title="The machine saw it as {machine.name}"
				>
					Machine <ColorChip name={machine.name} rgb={machine.rgb} />
				</span>
			{/if}
		</span>
	</span>
	<span class="flex shrink-0 flex-col items-end gap-1">
		<span class="num text-xs text-ink-muted" title={formatWhen(piece.seen_at)}>
			{formatTime(piece.seen_at)}
		</span>
		{#if piece.training_excluded}<Badge>Excluded</Badge>{/if}
	</span>
</button>
