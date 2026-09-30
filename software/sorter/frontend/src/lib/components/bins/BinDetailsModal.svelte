<script lang="ts">
	import PieceStatusBadge from '$lib/components/PieceStatusBadge.svelte';
	import PieceThumb from '$lib/components/PieceThumb.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Modal from '$lib/components/ui/Modal.svelte';
	import Popover from '$lib/components/ui/Popover.svelte';
	import { sortingProfileStore } from '$lib/stores/sortingProfile.svelte';
	import Plus from '@lucide/svelte/icons/plus';
	import Tag from '@lucide/svelte/icons/tag';
	import X from '@lucide/svelte/icons/x';
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

<Modal bind:open title={detailsBin ? `Bin ${detailsBin.bin.global_index + 1}` : 'Bin details'} size="lg">
	{#if detailsBin}
		<div class="flex flex-col gap-4">
			<dl class="grid grid-cols-1 gap-4 sm:grid-cols-3">
				<div>
					<dt class="label">Layer</dt>
					<dd class="num mt-1 text-base font-medium text-ink">{detailsBin.layerIndex + 1}</dd>
				</div>
				<div>
					<dt class="label">Assigned category</dt>
					<dd class="mt-1 text-base font-medium text-ink">
						{categoryLabel(detailsBin.bin.category_ids) || 'None'}
					</dd>
				</div>
				<div>
					<dt class="label">Recorded pieces</dt>
					<dd class="num mt-1 text-base font-medium text-ink">
						{detailsBin.contents?.piece_count ?? 0}
						{(detailsBin.contents?.piece_count ?? 0) === 1 ? 'piece' : 'pieces'}
					</dd>
				</div>
			</dl>

			<!-- Manual category assignment. Pick one or more sorting-profile
			     categories to route into this bin. Assigning a category here
			     removes it from any other bin (a category lives in one bin). -->
			<section class="rounded-control bg-well p-4">
				<div class="flex items-center justify-between gap-3">
					<h3 class="flex items-center gap-2 text-base font-semibold text-ink">
						<Tag size={16} />
						Assign categories
					</h3>
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
				<p class="mt-1 mb-3 text-sm text-ink-muted">
					Choose one or more categories from your sorting profile to route into this bin. Assigning a
					category here moves it out of whatever bin it was in before.
				</p>

				<div class="flex flex-wrap items-center gap-2">
					{#each assignSelected as id (id)}
						{@const elsewhere = assignedElsewhereLabel(id)}
						<Badge tone="primary">
							{formatCategoryName(id) || id}
							{#if elsewhere}<span class="text-ink-muted">(was {elsewhere})</span>{/if}
							<button
								type="button"
								class="-mr-1 ml-0.5 rounded-badge p-0.5 hover:bg-hover"
								onclick={() => removeAssignCategory(id)}
								aria-label={`Remove ${formatCategoryName(id) || id}`}
							>
								<X size={12} />
							</button>
						</Badge>
					{/each}

					<Popover label="Add a category" bind:open={assignDropdownOpen} width="20rem" padded={false}>
						{#snippet trigger(props)}
							<Button {...props} size="sm" icon={Plus}>Add a category</Button>
						{/snippet}
						<div class="p-2">
							<Input aria-label="Search categories" placeholder="Search categories…" bind:value={assignSearch} />
						</div>
						<div class="max-h-64 overflow-y-auto border-t border-line py-1">
							{#if availableCategories().length === 0}
								<p class="px-3 py-2 text-sm text-ink-muted">No categories in the active sorting profile.</p>
							{:else}
								{#each pickableCategories() as cat (cat.id)}
									{@const elsewhere = assignedElsewhereLabel(cat.id)}
									<button
										type="button"
										onclick={() => addAssignCategory(cat.id)}
										class="flex min-h-(--size-menu-item) w-full items-center justify-between gap-2 px-3 text-left text-sm text-ink hover:bg-hover"
									>
										<span class="min-w-0 flex-1 truncate">{cat.name}</span>
										{#if elsewhere}<Badge>{elsewhere}</Badge>{/if}
									</button>
								{/each}
								{#if pickableCategories().length === 0}
									<p class="px-3 py-2 text-sm text-ink-muted">
										{assignSearch.trim()
											? `No categories match “${assignSearch}”.`
											: 'All categories are already added.'}
									</p>
								{/if}
							{/if}
						</div>
					</Popover>
				</div>

				{#if assignSelected.length === 0}
					<p class="mt-3 text-sm text-ink-muted">
						No categories assigned. Matching pieces fall through to the discard bin.
					</p>
				{/if}
			</section>

			{#if setMeta}
				<section class="grid grid-cols-1 gap-4 rounded-control bg-well p-4 md:grid-cols-[10rem_1fr] md:items-center">
					<div class="flex items-center justify-center rounded-item bg-surface p-3">
						{#if setMeta.img_url}
							<img src={setMeta.img_url} alt={setMeta.name} class="h-32 w-full object-contain" />
						{/if}
					</div>
					<div>
						<h3 class="text-base font-semibold text-ink">{setMeta.name}</h3>
						{#if setMeta.set_num}<p class="num mt-1 text-sm text-ink-muted">{setMeta.set_num}</p>{/if}
						<div class="mt-3 flex flex-wrap gap-2">
							<Badge>
								{detailsBin.contents?.unique_item_count ?? 0}
								{(detailsBin.contents?.unique_item_count ?? 0) === 1 ? 'item type' : 'item types'}
							</Badge>
							<Badge>{detailsBin.contents?.piece_count ?? 0} total pieces</Badge>
						</div>
						<div class="mt-4">
							<Button onclick={() => openSetChecklist(detailsBin?.bin.category_ids ?? [])}>
								Open the checklist
							</Button>
						</div>
					</div>
				</section>
			{/if}

			{#if !detailsBin.contents || detailsBin.contents.items.length === 0}
				<EmptyState title="No detailed piece records for this bin yet." />
			{:else}
				<div class="grid grid-cols-3 gap-3 sm:grid-cols-4 lg:grid-cols-5">
					{#each detailsBin.contents.items as item}
						<div class="overflow-hidden rounded-control">
							<div class="relative p-2">
								<div class="h-24 w-full">
									<PieceThumb src={previewUrl(item)} alt={pieceTooltip(item)} fallbackText={item.part_id ?? '?'} />
								</div>
								<QuantityBadge count={item.count} />
							</div>
							<div class="px-2.5 py-2 text-sm">
								<div class="flex items-start justify-between gap-2">
									<div class="font-medium text-ink">{itemDisplayName(item)}</div>
									{#if item.classification_status && item.classification_status !== 'classified'}
										<PieceStatusBadge status={item.classification_status} />
									{/if}
								</div>
								<div class="mt-1 text-ink-muted">{itemSecondaryText(item)}</div>
								<div class="mt-1 text-ink-muted">{formatCategoryName(item.category_id) || 'No category'}</div>
							</div>
						</div>
					{/each}
				</div>
			{/if}
		</div>
	{/if}
</Modal>
