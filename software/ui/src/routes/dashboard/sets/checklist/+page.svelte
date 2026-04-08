<script lang="ts">
	import AppHeader from '$lib/components/AppHeader.svelte';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import { ArrowLeft, CheckCircle2, Filter, Printer } from 'lucide-svelte';
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

	let sets = $state<SetProgress[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let missingOnly = $state(true);

	function currentBackendBaseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(manager.selectedMachine?.url) ?? backendHttpBaseUrl;
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

	function missingTypesForSet(set: SetProgress): number {
		return set.parts.filter((p) => p.quantity_found < p.quantity_needed).length;
	}
</script>

<svelte:head>
	<title>Parts Checklist · Sorter</title>
	<style>
		@media print {
			html,
			body {
				background: #ffffff !important;
				color: #000000 !important;
				font-size: 10pt;
			}
			.no-print {
				display: none !important;
			}
			.print-block {
				break-inside: avoid;
				page-break-inside: avoid;
			}
			.print-break {
				break-before: page;
				page-break-before: always;
			}
			.print-card {
				border: 1px solid #000 !important;
				background: #ffffff !important;
				box-shadow: none !important;
			}
			.print-card-header {
				background: #f0f0f0 !important;
				border-bottom: 1px solid #000 !important;
			}
			.print-row {
				border-bottom: 1px solid #c0c0c0 !important;
			}
			.print-checkbox {
				border: 1.5px solid #000 !important;
				background: #ffffff !important;
				width: 14pt !important;
				height: 14pt !important;
			}
			.print-muted {
				color: #444 !important;
			}
			.print-strong {
				color: #000 !important;
			}
		}
	</style>
</svelte:head>

<div class="min-h-screen bg-bg text-text">
	<div class="no-print">
		<AppHeader />
	</div>

	<main class="mx-auto flex max-w-5xl flex-col gap-5 px-4 py-6 sm:px-6">
		<header class="no-print flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
			<div class="flex items-start gap-3">
				<a
					href="/dashboard/sets"
					class="setup-button-secondary inline-flex h-9 w-9 items-center justify-center text-text transition-colors"
					title="Back to set progress"
				>
					<ArrowLeft size={16} />
				</a>
				<div>
					<div
						class="text-[11px] font-semibold uppercase tracking-wider text-text-muted"
					>
						Set tracking
					</div>
					<h1 class="text-2xl font-bold text-text">Parts checklist</h1>
					<p class="mt-1 max-w-xl text-sm text-text-muted">
						Print this page and walk to your storage to hunt down the parts the sorter
						hasn&rsquo;t seen yet. Tick off boxes by hand or in the browser.
					</p>
				</div>
			</div>

			<div class="flex flex-shrink-0 items-center gap-2">
				<button
					type="button"
					onclick={() => (missingOnly = !missingOnly)}
					class="setup-button-secondary inline-flex items-center gap-2 px-3 py-2 text-sm text-text transition-colors"
					title="Toggle between missing parts only and all parts"
				>
					<Filter size={14} />
					{missingOnly ? 'Missing only' : 'All parts'}
				</button>
				<button
					type="button"
					onclick={() => window.print()}
					class="setup-button-primary inline-flex items-center gap-2 px-3 py-2 text-sm font-medium transition-colors"
					title="Print or export as PDF"
				>
					<Printer size={14} />
					Print / PDF
				</button>
			</div>
		</header>

		{#if loading}
			<div class="border border-border bg-surface px-4 py-12 text-center text-sm text-text-muted">
				Loading checklist&hellip;
			</div>
		{:else if error}
			<div
				class="border border-[#D01012]/40 bg-[#D01012]/[0.06] px-3 py-2"
			>
				<div
					class="text-[11px] font-semibold uppercase tracking-wider text-[#5C0708]"
				>
					Could not load checklist
				</div>
				<div class="mt-1 text-xs leading-relaxed text-text">{error}</div>
			</div>
		{:else if sets.length === 0}
			<div class="border border-border bg-surface px-4 py-12 text-center text-sm text-text-muted">
				No set-based sorting profile is active. Assign one to start tracking parts.
			</div>
		{:else}
			<!-- Summary card (also visible in print) -->
			<section class="print-block print-card border border-border bg-surface">
				<div class="print-card-header border-b border-border bg-surface px-4 py-3">
					<div
						class="text-[11px] font-semibold uppercase tracking-wider text-text-muted"
					>
						Hunt summary
					</div>
					<div class="mt-1 flex flex-wrap items-baseline gap-x-6 gap-y-1">
						<div class="text-base font-semibold text-text">
							{totals.missing} <span class="text-text-muted">parts still missing</span>
						</div>
						<div class="text-xs text-text-muted">
							across {totals.missingTypes} unique part / color combos in {visibleSets.length} of {sets.length} sets
						</div>
					</div>
				</div>
				<div class="grid grid-cols-3 divide-x divide-border">
					<div class="px-4 py-3">
						<div
							class="text-[11px] font-semibold uppercase tracking-wider text-text-muted"
						>
							Found
						</div>
						<div class="mt-1 text-lg font-semibold tabular-nums text-[#00852B]">
							{totals.found}
						</div>
					</div>
					<div class="px-4 py-3">
						<div
							class="text-[11px] font-semibold uppercase tracking-wider text-text-muted"
						>
							Missing
						</div>
						<div class="mt-1 text-lg font-semibold tabular-nums text-[#D01012]">
							{totals.missing}
						</div>
					</div>
					<div class="px-4 py-3">
						<div
							class="text-[11px] font-semibold uppercase tracking-wider text-text-muted"
						>
							Needed
						</div>
						<div class="mt-1 text-lg font-semibold tabular-nums text-text">
							{totals.needed}
						</div>
					</div>
				</div>
			</section>

			{#each visibleSets as set_progress, idx (set_progress.id)}
				{@const parts = visibleParts(set_progress)}
				{@const setMissing = totalMissing(set_progress)}
				{@const setMissingTypes = missingTypesForSet(set_progress)}
				{@const isComplete = setMissing === 0}
				{@const setPct = Math.min(100, set_progress.pct)}

				<section
					class="print-block print-card border border-border bg-surface"
					class:print-break={idx > 0}
				>
					<header
						class="print-card-header flex items-start gap-4 border-b border-border bg-surface px-4 py-3"
					>
						{#if set_progress.img_url}
							<img
								src={set_progress.img_url}
								alt={set_progress.name || set_progress.set_num}
								class="h-14 w-14 flex-shrink-0 border border-border bg-white object-contain"
								loading="lazy"
							/>
						{/if}
						<div class="min-w-0 flex-1">
							<div class="flex items-baseline justify-between gap-3">
								<div class="min-w-0">
									<div
										class="text-[11px] font-semibold uppercase tracking-wider text-text-muted print-muted"
									>
										Set {set_progress.set_num}{#if set_progress.year} &middot; {set_progress.year}{/if}
									</div>
									<h2 class="truncate text-base font-bold text-text print-strong">
										{set_progress.name || set_progress.set_num}
									</h2>
								</div>
								{#if isComplete}
									<span
										class="inline-flex flex-shrink-0 items-center gap-1 border border-[#00852B]/40 bg-[#00852B]/[0.08] px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-[#003D14]"
									>
										<CheckCircle2 size={12} />
										Complete
									</span>
								{:else}
									<span
										class="inline-flex flex-shrink-0 items-center gap-1 border border-[#D01012]/40 bg-[#D01012]/[0.06] px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-[#5C0708]"
									>
										{setMissing}
										{setMissing === 1 ? 'part' : 'parts'} missing
									</span>
								{/if}
							</div>
							<div class="mt-2 flex items-center gap-3">
								<div class="h-1.5 flex-1 bg-bg">
									<div
										class="h-full transition-all {isComplete ? 'bg-[#00852B]' : 'bg-primary'}"
										style="width: {setPct}%"
									></div>
								</div>
								<div
									class="flex-shrink-0 text-[11px] font-semibold tabular-nums text-text-muted print-muted"
								>
									{set_progress.total_found}/{set_progress.total_needed} &middot; {setPct}%
								</div>
							</div>
						</div>
					</header>

					{#if parts.length === 0}
						<div class="px-4 py-6 text-center text-xs text-text-muted">
							{#if missingOnly}
								All parts of this set have been sorted.
							{:else}
								This set has no parts.
							{/if}
						</div>
					{:else}
						<div class="px-1 py-1">
							<table class="w-full text-sm">
								<thead>
									<tr
										class="text-[11px] font-semibold uppercase tracking-wider text-text-muted print-muted"
									>
										<th class="px-3 pb-2 pt-2 text-left" style="width: 30px;">
											<span class="sr-only">Done</span>
										</th>
										<th class="px-2 pb-2 pt-2 text-left">Part</th>
										<th class="px-2 pb-2 pt-2 text-left">Color</th>
										<th class="px-2 pb-2 pt-2 text-right">Found</th>
										<th class="px-2 pb-2 pt-2 text-right">Needed</th>
										<th class="px-3 pb-2 pt-2 text-right">Missing</th>
									</tr>
								</thead>
								<tbody>
									{#each parts as part, partIdx (`${part.part_num}-${part.color_id}-${partIdx}`)}
										{@const missing = Math.max(0, part.quantity_needed - part.quantity_found)}
										{@const partComplete = missing === 0}
										<tr
											class="print-row border-t border-border/60 align-top text-text"
											class:opacity-60={partComplete && !missingOnly}
										>
											<td class="px-3 py-2">
												<input
													type="checkbox"
													checked={partComplete}
													disabled={partComplete}
													class="setup-toggle print-checkbox h-4 w-4 cursor-pointer border border-border bg-white"
													aria-label="Mark {part.part_num} as found"
												/>
											</td>
											<td class="px-2 py-2">
												<div class="font-mono text-xs font-semibold text-text print-strong">
													{part.part_num}
												</div>
												{#if part.part_name}
													<div class="mt-0.5 text-[11px] text-text-muted print-muted">
														{part.part_name}
													</div>
												{/if}
											</td>
											<td class="px-2 py-2 text-xs text-text print-strong">
												{colorLabel(part)}
											</td>
											<td
												class="px-2 py-2 text-right text-xs tabular-nums text-text-muted print-muted"
											>
												{part.quantity_found}
											</td>
											<td
												class="px-2 py-2 text-right text-xs tabular-nums text-text-muted print-muted"
											>
												{part.quantity_needed}
											</td>
											<td class="px-3 py-2 text-right">
												{#if partComplete}
													<span
														class="inline-flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wider text-[#003D14]"
													>
														<CheckCircle2 size={12} />
														OK
													</span>
												{:else}
													<span
														class="font-mono text-sm font-bold tabular-nums text-[#D01012] print-strong"
													>
														{missing}
													</span>
												{/if}
											</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					{/if}
				</section>
			{/each}

			{#if visibleSets.length === 0 && missingOnly}
				<div
					class="border border-[#00852B]/40 bg-[#00852B]/[0.06] px-4 py-8 text-center"
				>
					<div
						class="text-[11px] font-semibold uppercase tracking-wider text-[#003D14]"
					>
						All clear
					</div>
					<div class="mt-1 text-sm text-text">
						Every tracked set is fully sorted. Toggle &ldquo;All parts&rdquo; to review the
						completed inventory.
					</div>
				</div>
			{/if}
		{/if}
	</main>
</div>
