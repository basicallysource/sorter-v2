<script lang="ts">
	import { onMount } from 'svelte';
	import { getMachinesContext, getMachineContext } from '$lib/machines/context';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import MachineDropdown from '$lib/components/MachineDropdown.svelte';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import Printer from '@lucide/svelte/icons/printer';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';

	type SetPart = {
		part_num: string;
		color_id: string | number;
		part_name?: string | null;
		color_name?: string | null;
		quantity_needed: number;
		quantity_found: number;
	};

	type SetProgress = {
		id: string;
		set_num: string;
		name: string;
		img_url: string | null;
		total_needed: number;
		total_found: number;
		pct: number;
		parts: SetPart[];
	};

	type ProgressData = {
		is_set_based: boolean;
		progress: {
			overall_needed: number;
			overall_found: number;
			overall_pct: number;
			sets: SetProgress[];
		} | null;
	};

	const manager = getMachinesContext();
	let activeBaseUrl = $state(currentBackendBaseUrl());

	let data = $state<ProgressData | null>(null);
	let error = $state<string | null>(null);
	let expanded_sets = $state<Set<string>>(new Set());

	function currentBackendBaseUrl(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? getBackendHttpBase()
		);
	}

	function toggleExpand(setId: string) {
		const next = new Set(expanded_sets);
		if (next.has(setId)) next.delete(setId);
		else next.add(setId);
		expanded_sets = next;
	}

	async function fetchProgress() {
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/set-progress`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			data = await res.json();
			error = null;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load';
		}
	}

	onMount(() => {
		fetchProgress();
		const interval = setInterval(fetchProgress, 3000);
		return () => clearInterval(interval);
	});

	$effect(() => {
		const nextBaseUrl = currentBackendBaseUrl();
		if (nextBaseUrl === activeBaseUrl) return;
		activeBaseUrl = nextBaseUrl;
		data = null;
		error = null;
		void fetchProgress();
	});

	const progress = $derived(data?.progress);
	const is_set_based = $derived(data?.is_set_based ?? false);

	function colorLabel(part: SetPart): string {
		return part.color_name ?? (String(part.color_id) === '-1' ? 'Any color' : String(part.color_id));
	}
</script>

<svelte:head><title>Sorter - Sets</title></svelte:head>

<div class="min-h-screen bg-well p-6">
	<div class="mb-4 flex items-center justify-between">
		<div class="flex items-center gap-3">
			<a href="/" class="p-2 text-ink transition-colors hover:bg-surface" title="Back">
				<ArrowLeft size={20} />
			</a>
			<h1 class="text-xl font-bold text-ink">Set Progress</h1>
		</div>
		<div class="flex items-center gap-2">
			<a
				href="/dashboard/sets/checklist"
				class="flex items-center gap-1 border border-line px-3 py-1 text-xs text-ink hover:bg-surface"
			>
				<Printer size={14} />
				Checklist
			</a>
			<MachineDropdown />
		</div>
	</div>

	{#if error}
		<div class="mb-3 text-xs text-danger-ink">{error}</div>
	{/if}

	{#if !is_set_based}
		<div class="py-12 text-center text-ink-muted">
			The active sorting profile is not set-based. Assign a set-based profile to track progress.
		</div>
	{:else if progress}
		<!-- Overall progress -->
		<div class="mb-6 border border-line bg-surface p-4">
			<div class="mb-2 flex items-baseline justify-between">
				<span class="text-sm font-medium text-ink">Overall Progress</span>
				<span class="text-xs num text-ink-muted">
					{progress.overall_found} / {progress.overall_needed} parts ({progress.overall_pct}%)
				</span>
			</div>
			<div class="h-3 w-full bg-well">
				<div
					class="h-full bg-primary transition-all"
					style="width: {progress.overall_pct}%"
				></div>
			</div>
		</div>

		<!-- Per-set cards -->
		<div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
			{#each progress.sets as set_progress (set_progress.id)}
				{@const is_expanded = expanded_sets.has(set_progress.id)}
				{@const missing_parts = set_progress.parts.filter(p => p.quantity_found < p.quantity_needed)}
				<div class="border border-line bg-surface">
					<button
						class="flex w-full items-center gap-3 p-4 text-left hover:bg-hover"
						onclick={() => toggleExpand(set_progress.id)}
					>
						<div class="flex-shrink-0 text-ink-muted">
							{#if is_expanded}
								<ChevronDown size={16} />
							{:else}
								<ChevronRight size={16} />
							{/if}
						</div>
						<div class="min-w-0 flex-1">
							<div class="flex items-baseline justify-between gap-2">
								<div class="min-w-0">
									<div class="truncate text-sm font-medium text-ink">
										{set_progress.name || set_progress.set_num}
									</div>
									{#if set_progress.name && set_progress.name !== set_progress.set_num}
										<div class="truncate text-xs text-ink-muted">{set_progress.set_num}</div>
									{/if}
								</div>
								<span class="flex-shrink-0 text-xs num text-ink-muted">
									{set_progress.total_found}/{set_progress.total_needed} ({set_progress.pct}%)
								</span>
							</div>
							<div class="mt-1.5 h-2 w-full bg-well">
								<div
									class="h-full transition-all {set_progress.pct >= 100 ? 'bg-success' : 'bg-primary'}"
									style="width: {Math.min(set_progress.pct, 100)}%"
								></div>
							</div>
							{#if missing_parts.length > 0}
								<div class="mt-1 text-sm text-ink-muted">{missing_parts.length} parts still missing</div>
							{:else}
								<div class="mt-1 text-xs text-success-ink">Complete!</div>
							{/if}
						</div>
					</button>

					{#if is_expanded && missing_parts.length > 0}
						<div class="border-t border-line px-4 pb-3 pt-2">
							<table class="w-full text-xs">
								<thead>
									<tr class="text-ink-muted">
										<th class="pb-1 text-left font-medium">Part</th>
										<th class="pb-1 text-left font-medium">Color</th>
										<th class="pb-1 text-right font-medium">Found</th>
										<th class="pb-1 text-right font-medium">Needed</th>
									</tr>
								</thead>
								<tbody>
									{#each missing_parts as part}
										<tr class="border-t border-line text-ink">
											<td class="py-0.5">
												<div>{part.part_num}</div>
												{#if part.part_name}
													<div class="text-xs text-ink-muted">{part.part_name}</div>
												{/if}
											</td>
											<td class="py-0.5">{colorLabel(part)}</td>
											<td class="py-0.5 text-right num">{part.quantity_found}</td>
											<td class="py-0.5 text-right num">{part.quantity_needed}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					{/if}
				</div>
			{/each}
		</div>
	{:else}
		<div class="py-12 text-center text-ink-muted">Loading...</div>
	{/if}
</div>
