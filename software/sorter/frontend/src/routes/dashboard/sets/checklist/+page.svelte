<script lang="ts">
	import AppShell from '$lib/components/AppShell.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Checkbox from '$lib/components/ui/Checkbox.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import ProgressBar from '$lib/components/ui/ProgressBar.svelte';
	import SegmentedControl from '$lib/components/ui/SegmentedControl.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Stat from '$lib/components/ui/Stat.svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import Printer from '@lucide/svelte/icons/printer';
	import { onMount } from 'svelte';

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
		img_url?: string | null;
		year?: number | null;
		num_parts?: number | null;
		total_needed: number;
		total_found: number;
		pct: number;
		parts: SetPart[];
	};

	const manager = getMachinesContext();
	let activeBaseUrl = $state(currentBackendBaseUrl());

	let sets = $state<SetProgress[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let missingOnly = $state(true);
	// Paper is light whatever the page's mode: while printing, the page takes the light tokens.
	let printing = $state(false);

	function currentBackendBaseUrl(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? getBackendHttpBase()
		);
	}

	async function fetchProgress() {
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/set-progress`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			sets = data.progress?.sets ?? [];
			error = null;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load';
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		fetchProgress();
	});

	$effect(() => {
		const nextBaseUrl = currentBackendBaseUrl();
		if (nextBaseUrl === activeBaseUrl) return;
		activeBaseUrl = nextBaseUrl;
		loading = true;
		sets = [];
		error = null;
		void fetchProgress();
	});

	function colorLabel(part: SetPart): string {
		if (part.color_name) return part.color_name;
		if (String(part.color_id) === '-1') return 'Any color';
		return `Color ${part.color_id}`;
	}

	function visibleParts(set: SetProgress): SetPart[] {
		if (!missingOnly) return set.parts;
		return set.parts.filter((p) => p.quantity_found < p.quantity_needed);
	}

	const visibleSets = $derived.by(() => {
		if (!missingOnly) return sets;
		return sets.filter((s) => s.total_found < s.total_needed);
	});

	const totals = $derived.by(() => {
		let needed = 0;
		let found = 0;
		let missingTypes = 0;
		for (const s of sets) {
			needed += s.total_needed;
			found += s.total_found;
			for (const p of s.parts) {
				if (p.quantity_found < p.quantity_needed) missingTypes += 1;
			}
		}
		return { needed, found, missing: needed - found, missingTypes };
	});

	function totalMissing(set: SetProgress): number {
		return Math.max(0, set.total_needed - set.total_found);
	}

</script>

<svelte:head><title>Parts checklist - Sorter</title></svelte:head>

<svelte:window onbeforeprint={() => (printing = true)} onafterprint={() => (printing = false)} />

<AppShell>
	<div
		class="mx-auto flex w-full max-w-5xl flex-col gap-(--gap-panels) px-4 py-6 text-ink sm:px-6 print:max-w-none print:p-0 {printing
			? 'light'
			: ''}"
	>
		<div class="print:hidden">
			<PageHeader
				title="Parts checklist"
				description="Print this page and walk to your storage to hunt down the parts the sorter hasn't seen yet. Tick off boxes by hand or in the browser."
			>
				{#snippet actions()}
					<Button icon={ArrowLeft} href="/dashboard/sets">Back to set progress</Button>
					<SegmentedControl
						label="Which parts to list"
						value={missingOnly ? 'missing' : 'all'}
						options={[
							{ value: 'missing', label: 'Missing only' },
							{ value: 'all', label: 'All parts' }
						]}
						onchange={(v) => (missingOnly = v === 'missing')}
					/>
					<Button variant="primary" icon={Printer} onclick={() => window.print()}>Print or save as PDF</Button>
				{/snippet}
			</PageHeader>
		</div>

		{#if loading}
			<p class="flex items-center justify-center gap-2 py-12 text-sm text-ink-muted">
				<Spinner size={16} />
				Loading the checklist
			</p>
		{:else if error}
			<Alert tone="danger" title="The checklist did not load">{error}</Alert>
		{:else if sets.length === 0}
			<EmptyState title="No set-based sorting profile is active">
				Assign one to start tracking parts.
			</EmptyState>
		{:else}
			<!-- The summary also prints -->
			<Panel
				title="Hunt summary"
				description="{totals.missing} parts still missing, across {totals.missingTypes} unique part and color combinations in {visibleSets.length} of {sets.length} sets."
				flush
				class="print:break-inside-avoid"
			>
				<div class="grid grid-cols-3 divide-x divide-line border-t border-line">
					<Stat label="Found" value={totals.found} tone="success" />
					<Stat label="Missing" value={totals.missing} tone="danger" />
					<Stat label="Needed" value={totals.needed} />
				</div>
			</Panel>

			{#each visibleSets as set_progress, idx (set_progress.id)}
				{@const parts = visibleParts(set_progress)}
				{@const setMissing = totalMissing(set_progress)}
				{@const isComplete = setMissing === 0}
				{@const setPct = Math.min(100, set_progress.pct)}

				<Panel flush class="print:break-inside-avoid {idx > 0 ? 'print:break-before-page' : ''}">
					<div class="flex items-start gap-4 px-(--pad-panel) py-4">
						{#if set_progress.img_url}
							<img
								src={set_progress.img_url}
								alt={set_progress.name || set_progress.set_num}
								class="size-14 shrink-0 rounded-item object-contain"
								loading="lazy"
							/>
						{/if}
						<div class="min-w-0 flex-1">
							<div class="flex items-baseline justify-between gap-3">
								<div class="min-w-0">
									<div class="num text-sm text-ink-muted">
										Set {set_progress.set_num}{#if set_progress.year} &middot; {set_progress.year}{/if}
									</div>
									<h2 class="truncate text-base font-semibold text-ink">
										{set_progress.name || set_progress.set_num}
									</h2>
								</div>
								{#if isComplete}
									<Badge tone="success" dot>Complete</Badge>
								{:else}
									<Badge tone="danger">
										{setMissing} {setMissing === 1 ? 'part' : 'parts'} missing
									</Badge>
								{/if}
							</div>
							<div class="mt-2 flex items-center gap-3">
								<div class="flex-1">
									<ProgressBar
										value={setPct}
										label="Progress of {set_progress.name || set_progress.set_num}"
										tone={isComplete ? 'success' : 'primary'}
									/>
								</div>
								<span class="num shrink-0 text-xs text-ink-muted">
									{set_progress.total_found}/{set_progress.total_needed} &middot; {setPct}%
								</span>
							</div>
						</div>
					</div>

					{#if parts.length === 0}
						<p class="px-(--pad-panel) pb-5 text-center text-sm text-ink-muted">
							{missingOnly ? 'All parts of this set have been sorted.' : 'This set has no parts.'}
						</p>
					{:else}
						<div class="overflow-x-auto">
						<table class="data-table">
							<thead>
								<tr>
									<th class="w-10"><span class="sr-only">Done</span></th>
									<th>Part</th>
									<th>Color</th>
									<th class="num">Found</th>
									<th class="num">Needed</th>
									<th class="num">Missing</th>
								</tr>
							</thead>
							<tbody>
								{#each parts as part, partIdx (`${part.part_num}-${part.color_id}-${partIdx}`)}
									{@const missing = Math.max(0, part.quantity_needed - part.quantity_found)}
									{@const partComplete = missing === 0}
									<tr class="print:break-inside-avoid {partComplete && !missingOnly ? 'opacity-60' : ''}">
										<td>
											<Checkbox
												checked={partComplete}
												disabled={partComplete}
												aria-label="Mark {part.part_num} as found"
											/>
										</td>
										<td>
											<div class="num font-medium text-ink">{part.part_num}</div>
											{#if part.part_name}<div class="text-ink-muted">{part.part_name}</div>{/if}
										</td>
										<td>{colorLabel(part)}</td>
										<td class="num text-ink-muted">{part.quantity_found}</td>
										<td class="num text-ink-muted">{part.quantity_needed}</td>
										<td class="num">
											{#if partComplete}
												<span class="text-success-ink">OK</span>
											{:else}
												<span class="font-semibold text-danger-ink">{missing}</span>
											{/if}
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
						</div>
					{/if}
				</Panel>
			{/each}

			{#if visibleSets.length === 0 && missingOnly}
				<Alert tone="success" title="All clear">
					Every tracked set is fully sorted. Choose "All parts" to review the completed inventory.
				</Alert>
			{/if}
		{/if}
	</div>
</AppShell>
