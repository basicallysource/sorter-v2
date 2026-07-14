<script lang="ts">
	import { api, type MachineLabeledPiece } from '$lib/api';
	import Spinner from '$lib/components/Spinner.svelte';

	// Color-range reference column: other already-labeled pieces on THIS machine,
	// human ground-truth only (never model output), sorted into a hue gradient so
	// the labeler can calibrate — "this machine's dark tan looks like that, so the
	// lighter one I'm on is probably plain tan."
	let { machineId, pieceUuid }: { machineId: string; pieceUuid: string } = $props();

	let items = $state<MachineLabeledPiece[]>([]);
	let total = $state(0);
	let loading = $state(true);
	let error = $state<string | null>(null);

	async function load(mid: string, puid: string) {
		loading = true;
		error = null;
		try {
			const res = await api.machineLabeledPieces(mid, {
				anchorPiece: puid,
				excludePiece: puid,
				limit: 200
			});
			items = res.items;
			total = res.total;
		} catch {
			error = 'Failed to load';
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		const mid = machineId;
		const puid = pieceUuid;
		if (mid && puid) void load(mid, puid);
	});
</script>

<div class="border border-border bg-surface">
	<div class="border-b border-border px-3 py-2">
		<div class="text-sm font-medium text-text">Labeled on this machine</div>
		<div class="text-xs text-text-muted">
			{#if !loading && total > 0}
				{total} labeled piece{total === 1 ? '' : 's'} · color range for reference
			{:else}
				this machine's known colors, for reference
			{/if}
		</div>
	</div>

	{#if loading}
		<div class="flex justify-center py-8"><Spinner /></div>
	{:else if error}
		<div class="p-3 text-sm text-primary">{error}</div>
	{:else if items.length === 0}
		<p class="p-4 text-sm text-text-muted">This machine has no pieces labeled yet.</p>
	{:else}
		<div class="flex flex-col">
			{#each items as it (it.piece_uuid)}
				<a
					href={`/piece-bboxes/${machineId}/${encodeURIComponent(it.piece_uuid)}`}
					class="flex items-center gap-2 border-b border-border px-2 py-1.5 last:border-b-0 hover:bg-bg"
					title={`${it.color_name} (${it.color_id}) · ${it.label_count} labeler${it.label_count === 1 ? '' : 's'}`}
				>
					<div class="flex h-12 w-12 shrink-0 items-center justify-center bg-bg">
						{#if it.thumb_seq != null}
							<img
								src={api.machineLabeledPieceImageUrl(machineId, it.piece_uuid, it.thumb_seq)}
								alt={it.color_name}
								loading="lazy"
								class="h-12 w-12 bg-transparent object-contain"
							/>
						{/if}
					</div>
					<span
						class="h-4 w-4 shrink-0 border border-border {it.is_trans ? 'opacity-70' : ''}"
						style={`background:#${it.rgb ?? '000'}`}
					></span>
					<span class="min-w-0 flex-1 truncate text-xs text-text-muted">{it.color_name}</span>
				</a>
			{/each}
		</div>
	{/if}
</div>
