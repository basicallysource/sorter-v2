<!--
	One piece of a training run, laid out as a part tile: its crop, its part,
	the run's label as a color, and the machine's own color under it only when
	the two differ (a piece worth a look). Clicking it excludes the piece, and
	clicking it again brings it back; an excluded piece is faded and says so.
-->
<script lang="ts">
	import Badge from '$lib/components/ui/Badge.svelte';
	import ColorChip from '$lib/components/ui/ColorChip.svelte';
	import PartTile from '$lib/components/ui/PartTile.svelte';
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
		ontoggle
	}: {
		piece: TrainingPiece;
		base: string;
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
</script>

<PartTile
	layout="tile"
	name={piece.part_name ?? piece.part_id ?? 'Unknown part'}
	bricklinkId={piece.part_name ? piece.part_id : null}
	imgUrl={pieceImageUrl(base, piece)}
	color={label}
	onclick={() => ontoggle(piece)}
	class={piece.training_excluded ? 'opacity-50' : ''}
>
	{#if machine}
		<span
			class="flex min-w-0 items-center gap-1.5 text-sm text-warning-ink"
			title="The machine saw it as {machine.name}"
		>
			Machine <ColorChip name={machine.name} rgb={machine.rgb} />
		</span>
	{:else if !label}
		<span class="text-sm text-ink-muted">No label</span>
	{/if}
	<span class="num text-xs text-ink-muted" title={formatWhen(piece.seen_at)}>
		{formatTime(piece.seen_at)}
	</span>
	{#if piece.training_excluded}<Badge>Excluded</Badge>{/if}
</PartTile>
