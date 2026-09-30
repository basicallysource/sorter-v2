<script lang="ts">
	import { api, type MachineLabeledPiece } from '$lib/api';
	import Spinner from '$lib/components/Spinner.svelte';
	import ZoomImage from '$lib/components/ZoomImage.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import Panel from '$lib/components/Panel.svelte';

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

	const MAX_PER_COLOR = 2;

	// The reference column is for calibrating color, not browsing every piece — a
	// machine with 100 dark bluish gray pieces would otherwise bury every other hue.
	let shown = $derived.by(() => {
		const seen = new Map<number, number>();
		return items.filter((it) => {
			const n = seen.get(it.color_id) ?? 0;
			if (n >= MAX_PER_COLOR) return false;
			seen.set(it.color_id, n + 1);
			return true;
		});
	});

	$effect(() => {
		const mid = machineId;
		const puid = pieceUuid;
		if (mid && puid) void load(mid, puid);
	});
</script>

<Panel
	title="Labeled on this machine"
	description={!loading && total > 0
		? `${total} labeled piece${total === 1 ? '' : 's'}, this machine's color range for reference`
		: "This machine's known colors, for reference"}
	flush
>
	{#if loading}
		<div class="flex justify-center py-8"><Spinner size={32} /></div>
	{:else if error}
		<div class="px-(--pad-panel) pb-(--pad-panel)"><Alert tone="danger">{error}</Alert></div>
	{:else if items.length === 0}
		<p class="px-(--pad-panel) pb-(--pad-panel) text-sm text-ink-muted">This machine has no pieces labeled yet.</p>
	{:else}
		<ul class="divide-y divide-line border-t border-line">
			{#each shown as it (it.piece_uuid)}
				<li>
					<a
						href={`/piece-bboxes/${machineId}/${encodeURIComponent(it.piece_uuid)}`}
						class="flex items-center gap-2 px-(--pad-panel) py-1.5 hover:bg-hover"
						title={`${it.color_name} (${it.color_id}), ${it.label_count} labeler${it.label_count === 1 ? '' : 's'}`}
					>
						<div class="flex size-12 shrink-0 items-center justify-center rounded-item {it.thumb_seq != null ? '' : 'bg-well'}">
							{#if it.thumb_seq != null}
								<ZoomImage
									src={api.machineLabeledPieceImageUrl(machineId, it.piece_uuid, it.thumb_seq)}
									alt={it.color_name}
									class="size-12 object-contain"
								/>
							{/if}
						</div>
						<span
							class="size-4 shrink-0 rounded-check border border-line {it.is_trans ? 'opacity-70' : ''}"
							style={`background:#${it.rgb ?? '000'}`}
						></span>
						<span class="min-w-0 flex-1 truncate text-sm text-ink-muted">{it.color_name}</span>
					</a>
				</li>
			{/each}
		</ul>
	{/if}
</Panel>
