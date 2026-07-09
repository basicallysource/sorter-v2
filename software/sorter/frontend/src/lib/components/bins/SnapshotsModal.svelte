<script lang="ts">
	import Modal from '$lib/components/Modal.svelte';
	import { ArrowLeft, Download, Loader2 } from 'lucide-svelte';
	import { formatCategoryName, formatLastSeen } from './pieces';
	import type { SnapshotDetail, SnapshotLayer, SnapshotSummary } from './types';

	let { open = $bindable(false), baseUrl }: { open?: boolean; baseUrl: string } = $props();

	let snapshots = $state<SnapshotSummary[]>([]);
	let snapshotsLoading = $state(false);
	let snapshotsError = $state<string | null>(null);
	let detail = $state<SnapshotDetail | null>(null);
	let detailLoading = $state(false);
	let lastOpen = false;

	$effect(() => {
		if (open && !lastOpen) {
			detail = null;
			void loadSnapshots();
		}
		lastOpen = open;
	});

	async function loadSnapshots() {
		snapshotsLoading = true;
		snapshotsError = null;
		try {
			const res = await fetch(`${baseUrl}/api/bins/snapshots`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			snapshots = data.snapshots ?? [];
		} catch (e) {
			snapshotsError = `Failed to load snapshots: ${e}`;
		} finally {
			snapshotsLoading = false;
		}
	}

	async function openDetail(id: string) {
		detailLoading = true;
		snapshotsError = null;
		try {
			const res = await fetch(`${baseUrl}/api/bins/snapshots/${encodeURIComponent(id)}`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			detail = await res.json();
		} catch (e) {
			snapshotsError = `Failed to load snapshot: ${e}`;
		} finally {
			detailLoading = false;
		}
	}

	function csvUrl(id: string): string {
		return `${baseUrl}/api/bins/snapshots/${encodeURIComponent(id)}/export.csv`;
	}

	function binLabel(layer: SnapshotLayer): string {
		return `Layer ${layer.layer_index + 1} · Section ${layer.section_index + 1} · Bin ${layer.bin_index + 1}`;
	}
</script>

<Modal bind:open title={detail ? 'Snapshot Details' : 'Bin Snapshots'} wide={true}>
	{#if snapshotsError}
		<div class="mb-3 border border-danger bg-danger/[0.06] px-3 py-2 text-sm text-danger">{snapshotsError}</div>
	{/if}
	{#if detail}
		<div class="space-y-4">
			<div class="flex items-center justify-between gap-3">
				<button
					type="button"
					onclick={() => (detail = null)}
					class="flex items-center gap-2 border border-[#E2E0DB] bg-white px-3 py-1.5 text-sm font-medium text-[#1A1A1A] transition-colors hover:bg-[#F7F6F3]"
				>
					<ArrowLeft size={14} />
					All snapshots
				</button>
				<a
					href={csvUrl(detail.id)}
					download
					class="flex items-center gap-2 border border-[#E2E0DB] bg-white px-3 py-1.5 text-sm font-medium text-[#1A1A1A] transition-colors hover:bg-[#F7F6F3]"
				>
					<Download size={14} />
					Export CSV
				</a>
			</div>
			<div class="grid gap-4 border border-border bg-surface px-4 py-4 text-sm text-text-muted md:grid-cols-4">
				<div>
					<div class="text-xs uppercase tracking-wide">Status</div>
					<div class="mt-1 text-base font-medium text-text capitalize">{detail.status}</div>
				</div>
				<div>
					<div class="text-xs uppercase tracking-wide">Started</div>
					<div class="mt-1 text-base font-medium text-text">{formatLastSeen(detail.created_at)}</div>
				</div>
				<div>
					<div class="text-xs uppercase tracking-wide">Closed</div>
					<div class="mt-1 text-base font-medium text-text">{formatLastSeen(detail.closed_at)}</div>
				</div>
				<div>
					<div class="text-xs uppercase tracking-wide">Pieces</div>
					<div class="mt-1 text-base font-medium text-text">{detail.piece_count}</div>
				</div>
			</div>
			{#each detail.layers as layer (layer.id)}
				<div class="border border-border bg-bg p-4">
					<div class="mb-2 flex flex-wrap items-center justify-between gap-2">
						<div class="text-sm font-semibold text-text">{binLabel(layer)}</div>
						<div class="flex items-center gap-2 text-xs text-text-muted">
							<span class="border border-border bg-surface px-2 py-1">{layer.piece_count} {layer.piece_count === 1 ? 'piece' : 'pieces'}</span>
							<span class="border border-border bg-surface px-2 py-1">emptied {formatLastSeen(layer.flushed_at)}</span>
						</div>
					</div>
					{#if layer.category_ids.length > 0}
						<div class="mb-3 text-sm text-text-muted">
							Assigned: {layer.category_ids.map((id) => formatCategoryName(id) || id).join(', ')}
						</div>
					{/if}
					{#if layer.items.length > 0}
						<div class="overflow-x-auto">
							<table class="w-full text-left text-sm">
								<thead>
									<tr class="border-b border-border text-xs uppercase tracking-wide text-text-muted">
										<th class="py-1.5 pr-4">Part</th>
										<th class="py-1.5 pr-4">Color</th>
										<th class="py-1.5 pr-4">Category</th>
										<th class="py-1.5 pr-4">Count</th>
										<th class="py-1.5">Last seen</th>
									</tr>
								</thead>
								<tbody>
									{#each layer.items as item (item.item_key)}
										<tr class="border-b border-border/60">
											<td class="py-1.5 pr-4 font-medium text-text">{item.part_id ?? 'unknown'}</td>
											<td class="py-1.5 pr-4">{item.color_name ?? item.color_id ?? 'n/a'}</td>
											<td class="py-1.5 pr-4">{formatCategoryName(item.category_id) || item.category_id || 'n/a'}</td>
											<td class="py-1.5 pr-4">{item.count}</td>
											<td class="py-1.5">{formatLastSeen(item.last_distributed_at)}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					{/if}
				</div>
			{/each}
		</div>
	{:else if detailLoading || snapshotsLoading}
		<div class="flex items-center justify-center gap-2 py-10 text-sm text-text-muted">
			<Loader2 size={16} class="animate-spin" />
			Loading…
		</div>
	{:else if snapshots.length === 0}
		<p class="py-8 text-center text-sm text-text-muted">
			No snapshots yet. Emptying a bin (or all bins) automatically saves a snapshot of what was in it.
		</p>
	{:else}
		<div class="space-y-2">
			{#each snapshots as snapshot (snapshot.id)}
				<div class="flex flex-wrap items-center justify-between gap-3 border border-border bg-bg px-4 py-3">
					<div>
						<div class="text-sm font-medium text-text">
							{formatLastSeen(snapshot.closed_at ?? snapshot.created_at)}
							{#if snapshot.status === 'open'}
								<span class="ml-2 border border-primary bg-primary/[0.08] px-1.5 py-0.5 text-xs text-text">accumulating</span>
							{/if}
						</div>
						<div class="mt-0.5 text-xs text-text-muted">
							{snapshot.piece_count} {snapshot.piece_count === 1 ? 'piece' : 'pieces'} · {snapshot.bin_count} {snapshot.bin_count === 1 ? 'bin' : 'bins'} · {snapshot.layer_count} {snapshot.layer_count === 1 ? 'wipe' : 'wipes'}
						</div>
					</div>
					<div class="flex items-center gap-2">
						<button
							type="button"
							onclick={() => void openDetail(snapshot.id)}
							class="border border-[#E2E0DB] bg-white px-3 py-1.5 text-sm font-medium text-[#1A1A1A] transition-colors hover:bg-[#F7F6F3]"
						>
							View
						</button>
						<a
							href={csvUrl(snapshot.id)}
							download
							class="flex items-center gap-1.5 border border-[#E2E0DB] bg-white px-3 py-1.5 text-sm font-medium text-[#1A1A1A] transition-colors hover:bg-[#F7F6F3]"
						>
							<Download size={13} />
							CSV
						</a>
					</div>
				</div>
			{/each}
		</div>
	{/if}
</Modal>
