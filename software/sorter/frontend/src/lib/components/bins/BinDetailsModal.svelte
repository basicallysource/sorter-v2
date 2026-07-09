<script lang="ts">
	import Modal from '$lib/components/Modal.svelte';
	import PieceStatusBadge from '$lib/components/PieceStatusBadge.svelte';
	import PieceThumb from '$lib/components/PieceThumb.svelte';
	import { Button, SelectMenu } from '$lib/components/primitives';
	import { bricklinkParts } from '$lib/stores/bricklinkParts.svelte';
	import { sortingProfileStore } from '$lib/stores/sortingProfile.svelte';
	import { Plus, Tag, X } from 'lucide-svelte';
	import { categoryLabel, formatCategoryName, itemDisplayName, itemSecondaryText, pieceTooltip, previewUrl } from './pieces';
	import QuantityBadge from './QuantityBadge.svelte';
	import type { BinContents, BinInfo, LayerInfo, SetMeta } from './types';

	let {
		open = $bindable(false),
		detailsBin,
		baseUrl,
		layers,
		onSaved,
		onError
	}: {
		open?: boolean;
		detailsBin: { bin: BinInfo; layerIndex: number; contents: BinContents | null } | null;
		baseUrl: string;
		layers: LayerInfo[];
		onSaved: (message: string) => void;
		onError: (message: string) => void;
	} = $props();

	// Working set the operator is editing. Seeded from the bin's saved
	// category_ids when the modal opens for a bin; the live layout/contents
	// refresh never clobbers an in-progress edit because we only reseed when the
	// modal targets a different bin (or reopens).
	let assignSelected = $state<string[]>([]);
	let assignSearch = $state('');
	let savingAssign = $state(false);
	let assignDropdownOpen = $state(false);
	let seededKey: string | null = null;

	$effect(() => {
		if (!open || !detailsBin) {
			seededKey = null;
			return;
		}
		const key = `${detailsBin.layerIndex}:${detailsBin.bin.section_index}:${detailsBin.bin.bin_index}`;
		if (key === seededKey) return;
		seededKey = key;
		assignSelected = [...detailsBin.bin.category_ids];
		assignSearch = '';
		assignDropdownOpen = false;
		for (const item of detailsBin.contents?.items ?? []) {
			if (item.part_id) void bricklinkParts.fetch(baseUrl, item.part_id);
		}
	});

	const setMeta = $derived.by((): SetMeta | null => {
		const categoryIds = detailsBin?.bin.category_ids;
		if (!categoryIds || categoryIds.length !== 1) return null;
		const categoryId = categoryIds[0];
		const match = sortingProfileStore.data?.rules.find((rule) => {
			const candidate = rule as any;
			return candidate.id === categoryId && candidate.rule_type === 'set';
		}) as any;
		if (!match) return null;
		return { name: match.name, set_num: match.set_num, img_url: match.set_meta?.img_url };
	});

	function availableCategories(): { id: string; name: string }[] {
		const cats = sortingProfileStore.data?.categories ?? {};
		return Object.entries(cats)
			.map(([id, cat]) => ({ id, name: cat?.name ?? id }))
			.sort((a, b) => a.name.localeCompare(b.name));
	}

	// Where each category is currently assigned across the persisted layout, so
	// the picker can flag categories already living in another bin (assigning
	// here will move them). Keyed by category_id → that bin's global index.
	function categoryLocations(): Record<string, { layerIndex: number; globalIndex: number }> {
		const map: Record<string, { layerIndex: number; globalIndex: number }> = {};
		for (const layer of layers) {
			for (const bin of layer.bins) {
				for (const id of bin.category_ids) {
					if (!(id in map)) {
						map[id] = { layerIndex: layer.layer_index, globalIndex: bin.global_index };
					}
				}
			}
		}
		return map;
	}

	function assignedElsewhereLabel(id: string): string | null {
		const loc = categoryLocations()[id];
		if (!loc) return null;
		if (detailsBin && loc.globalIndex === detailsBin.bin.global_index) return null;
		return `Bin ${loc.globalIndex + 1}`;
	}

	function pickableCategories(): { id: string; name: string }[] {
		const query = assignSearch.trim().toLowerCase();
		return availableCategories().filter((cat) => {
			if (assignSelected.includes(cat.id)) return false;
			if (!query) return true;
			return cat.name.toLowerCase().includes(query) || cat.id.toLowerCase().includes(query);
		});
	}

	function addAssignCategory(id: string) {
		if (!assignSelected.includes(id)) assignSelected = [...assignSelected, id];
		assignSearch = '';
		assignDropdownOpen = false;
	}

	function removeAssignCategory(id: string) {
		assignSelected = assignSelected.filter((c) => c !== id);
	}

	function assignDirty(): boolean {
		if (!detailsBin) return false;
		const current = [...detailsBin.bin.category_ids].sort();
		const next = [...assignSelected].sort();
		return current.length !== next.length || current.some((c, i) => c !== next[i]);
	}

	async function saveAssignment() {
		if (!detailsBin || savingAssign) return;
		savingAssign = true;
		try {
			const res = await fetch(`${baseUrl}/api/bins/categories/assign`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					layer_index: detailsBin.layerIndex,
					section_index: detailsBin.bin.section_index,
					bin_index: detailsBin.bin.bin_index,
					category_ids: assignSelected
				})
			});
			if (!res.ok) {
				const detail = await res.json().catch(() => null);
				throw new Error(detail?.detail ?? `HTTP ${res.status}`);
			}
			const data = await res.json();
			assignSelected = Array.isArray(data.category_ids) ? data.category_ids : assignSelected;
			assignDropdownOpen = false;
			onSaved(data?.message ?? 'Bin categories updated.');
		} catch (e: unknown) {
			onError(e instanceof Error ? e.message : 'Failed to assign categories');
		} finally {
			savingAssign = false;
		}
	}

	function openSetChecklist(categoryIds: string[]) {
		if (!categoryIds || categoryIds.length !== 1) return;
		const categoryId = categoryIds[0];
		const target = `${window.location.origin}/bins/set-view/${encodeURIComponent(categoryId)}?base=${encodeURIComponent(baseUrl)}`;
		window.open(target, '_blank', 'noopener,noreferrer');
	}
</script>

<Modal bind:open title={detailsBin ? `Bin ${detailsBin.bin.global_index + 1} Details` : 'Bin Details'} wide={true}>
	{#if detailsBin}
		<div class="space-y-4">
			<div class="grid gap-4 border border-border bg-surface px-4 py-4 text-sm text-text-muted md:grid-cols-3">
				<div>
					<div class="text-xs uppercase tracking-wide">Layer</div>
					<div class="mt-1 text-base font-medium text-text">{detailsBin.layerIndex + 1}</div>
				</div>
				<div>
					<div class="text-xs uppercase tracking-wide">Assigned Category</div>
					<div class="mt-1 text-base font-medium text-text">{categoryLabel(detailsBin.bin.category_ids) || 'None'}</div>
				</div>
				<div>
					<div class="text-xs uppercase tracking-wide">Recorded Pieces</div>
					<div class="mt-1 text-base font-medium text-text">{detailsBin.contents?.piece_count ?? 0} {(detailsBin.contents?.piece_count ?? 0) === 1 ? 'piece' : 'pieces'}</div>
				</div>
			</div>

			<!-- Manual category assignment. Pick one or more sorting-profile
			     categories to route into this bin. Assigning a category here
			     removes it from any other bin (a category lives in one bin). -->
			<div class="border border-border bg-bg p-4">
				<div class="mb-2 flex items-center justify-between gap-3">
					<div class="flex items-center gap-2 text-sm font-semibold text-text">
						<Tag size={15} />
						Assign categories
					</div>
					<Button
						size="sm"
						variant="primary"
						loading={savingAssign}
						disabled={!assignDirty()}
						onclick={() => void saveAssignment()}
					>
						Save
					</Button>
				</div>
				<p class="mb-3 text-sm text-text-muted">
					Choose one or more categories from your sorting profile to route into this bin.
					Assigning a category here moves it out of whatever bin it was in before.
				</p>

				<div class="flex flex-wrap items-center gap-2">
					{#each assignSelected as id (id)}
						{@const elsewhere = assignedElsewhereLabel(id)}
						<span class="inline-flex items-center gap-1.5 border border-primary bg-primary/[0.08] px-2 py-1 text-sm text-text">
							{formatCategoryName(id) || id}
							{#if elsewhere}
								<span class="text-xs text-text-muted">(was {elsewhere})</span>
							{/if}
							<button
								type="button"
								class="text-text-muted transition-colors hover:text-danger"
								onclick={() => removeAssignCategory(id)}
								aria-label={`Remove ${formatCategoryName(id) || id}`}
							>
								<X size={13} />
							</button>
						</span>
					{/each}

					<SelectMenu
						bind:open={assignDropdownOpen}
						bind:search={assignSearch}
						searchPlaceholder="Search categories…"
						width={320}
					>
						{#snippet trigger()}
							<span class="inline-flex items-center gap-1 border border-border bg-white px-2 py-1 text-sm text-text transition-colors hover:bg-surface">
								<Plus size={14} />
								Add category
							</span>
						{/snippet}
						{#if availableCategories().length === 0}
							<div class="px-3 py-3 text-sm text-text-muted">
								No categories in the active sorting profile.
							</div>
						{:else}
							{#each pickableCategories() as cat (cat.id)}
								{@const elsewhere = assignedElsewhereLabel(cat.id)}
								<button
									type="button"
									onclick={() => addAssignCategory(cat.id)}
									class="flex w-full items-center justify-between gap-2 border-b border-border bg-white px-3 py-2 text-left text-sm transition-colors last:border-b-0 hover:bg-surface"
								>
									<span class="flex-1 text-text">{cat.name}</span>
									{#if elsewhere}
										<span
											class="shrink-0 border border-border bg-surface px-1.5 py-0.5 text-xs text-text-muted"
											title="Currently assigned here — adding will move it"
										>
											{elsewhere}
										</span>
									{/if}
								</button>
							{/each}
							{#if pickableCategories().length === 0}
								<div class="px-3 py-3 text-sm text-text-muted">
									{assignSearch.trim() ? `No categories match “${assignSearch}”.` : 'All categories are already added.'}
								</div>
							{/if}
						{/if}
					</SelectMenu>
				</div>

				{#if assignSelected.length === 0}
					<div class="mt-3 text-sm text-text-muted">
						No categories assigned — matching pieces fall through to the discard bin.
					</div>
				{/if}
			</div>

			{#if setMeta}
				<div class="border border-border bg-bg p-4">
					<div class="grid gap-4 md:grid-cols-[160px_1fr] md:items-center">
						<div class="flex items-center justify-center bg-surface p-3">
							{#if setMeta.img_url}
								<img src={setMeta.img_url} alt={setMeta.name} class="h-32 w-full object-contain" />
							{/if}
						</div>
						<div>
							<div class="text-lg font-semibold text-text">{setMeta.name}</div>
							{#if setMeta.set_num}
								<div class="mt-1 text-sm text-text-muted">{setMeta.set_num}</div>
							{/if}
							<div class="mt-3 flex flex-wrap gap-2 text-xs text-text-muted">
								<span class="border border-border bg-surface px-2 py-1">{detailsBin.contents?.unique_item_count ?? 0} {(detailsBin.contents?.unique_item_count ?? 0) === 1 ? 'item type' : 'item types'}</span>
								<span class="border border-border bg-surface px-2 py-1">{detailsBin.contents?.piece_count ?? 0} total pieces</span>
							</div>
							<div class="mt-4">
								<button
									type="button"
									onclick={() => openSetChecklist(detailsBin?.bin.category_ids ?? [])}
									class="border border-border bg-surface px-3 py-2 text-sm text-text transition-colors hover:bg-bg"
								>
									Open checklist
								</button>
							</div>
						</div>
					</div>
				</div>
			{/if}

			{#if !detailsBin.contents || detailsBin.contents.items.length === 0}
				<div class="border border-border bg-bg px-4 py-4 text-sm text-text-muted">No detailed piece records for this bin yet.</div>
			{:else}
				<div class="grid gap-3 grid-cols-3 sm:grid-cols-4 lg:grid-cols-6">
					{#each detailsBin.contents.items as item}
						<div class="overflow-hidden border border-border bg-bg">
							<div class="relative bg-surface p-2">
								<div class="h-24 w-full">
									<PieceThumb src={previewUrl(item)} alt={pieceTooltip(item)} fallbackText={item.part_id ?? '?'} />
								</div>
								<QuantityBadge count={item.count} />
							</div>
							<div class="px-2 py-2">
								<div class="flex items-start justify-between gap-2">
									<div class="text-sm font-medium text-text">{itemDisplayName(item)}</div>
									{#if item.classification_status && item.classification_status !== 'classified'}
										<PieceStatusBadge status={item.classification_status} />
									{/if}
								</div>
								<div class="mt-1 text-sm text-text-muted">{itemSecondaryText(item)}</div>
								<div class="mt-2 text-sm text-text-muted">{formatCategoryName(item.category_id) || 'No category'}</div>
							</div>
						</div>
					{/each}
				</div>
			{/if}
		</div>
	{/if}
</Modal>
