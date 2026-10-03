<script lang="ts">
	import { onMount } from 'svelte';
	import { getMachinesContext, getMachineContext } from '$lib/machines/context';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import Printer from '@lucide/svelte/icons/printer';
	import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
	import { confirmDialog } from '$lib/confirm.svelte';
	import AppShell from '$lib/components/AppShell.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import ProgressBar from '$lib/components/ui/ProgressBar.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';

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

	// A kit's counts carry over from one version of the profile to the next;
	// they start again from zero only from here.
	let resetting = $state<string | null>(null);

	async function resetKit(set_progress: SetProgress) {
		const name = set_progress.name || set_progress.set_num;
		const ok = await confirmDialog({
			title: `Count ${name} from zero`,
			message: `The sorter forgets the ${set_progress.total_found} pieces it counted for this kit and collects all ${set_progress.total_needed} again. Pieces already in its bin stay there.`,
			action: 'Count from zero',
			danger: true
		});
		if (!ok) return;
		resetting = set_progress.id;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/set-progress/reset`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ category_id: set_progress.id })
			});
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			data = await res.json();
			error = null;
		} catch (e) {
			error = e instanceof Error ? e.message : 'The kit could not be reset';
		} finally {
			resetting = null;
		}
	}

	const progress = $derived(data?.progress);
	const is_set_based = $derived(data?.is_set_based ?? false);

	function colorLabel(part: SetPart): string {
		return part.color_name ?? (String(part.color_id) === '-1' ? 'Any color' : String(part.color_id));
	}
</script>

<svelte:head><title>Sorter - Set progress</title></svelte:head>

<AppShell>
	<div class="mx-auto flex w-full max-w-[1500px] flex-col gap-(--gap-panels) px-4 py-6 sm:px-6">
		<PageHeader
			title="Set progress"
			description="How many of each set's parts the sorter has found so far. The counts carry over when the profile changes."
		>
			{#snippet actions()}
				<Button icon={Printer} href="/dashboard/sets/checklist">Checklist</Button>
			{/snippet}
		</PageHeader>

		{#if error}<Alert tone="danger">{error}</Alert>{/if}

		{#if !is_set_based}
			<EmptyState title="The active sorting profile is not set-based">
				Assign a set-based profile to track progress.
			</EmptyState>
		{:else if progress}
			<Panel
				title="Overall progress"
				description="{progress.overall_found} / {progress.overall_needed} parts ({progress.overall_pct}%)"
			>
				<ProgressBar value={progress.overall_pct} label="Overall progress" />
			</Panel>

			<div class="grid grid-cols-1 gap-(--gap-panels) md:grid-cols-2 xl:grid-cols-3">
				{#each progress.sets as set_progress (set_progress.id)}
					{@const is_expanded = expanded_sets.has(set_progress.id)}
					{@const missing_parts = set_progress.parts.filter((p) => p.quantity_found < p.quantity_needed)}
					<Panel flush class="h-full">
						<button
							type="button"
							aria-expanded={is_expanded}
							class="flex w-full items-start gap-3 px-(--pad-panel) py-4 text-left transition-colors hover:bg-hover"
							onclick={() => toggleExpand(set_progress.id)}
						>
							<span class="mt-0.5 shrink-0 text-ink-muted">
								{#if is_expanded}<ChevronDown size={16} />{:else}<ChevronRight size={16} />{/if}
							</span>
							<span class="min-w-0 flex-1">
								<span class="flex items-baseline justify-between gap-2">
									<span class="min-w-0">
										<span class="block truncate text-sm font-medium text-ink">
											{set_progress.name || set_progress.set_num}
										</span>
										{#if set_progress.name && set_progress.name !== set_progress.set_num}
											<span class="num block truncate text-xs text-ink-muted">{set_progress.set_num}</span>
										{/if}
									</span>
									<span class="num shrink-0 text-xs text-ink-muted">
										{set_progress.total_found}/{set_progress.total_needed} ({set_progress.pct}%)
									</span>
								</span>
								<span class="mt-2 block">
									<ProgressBar
										value={Math.min(set_progress.pct, 100)}
										label="Progress of {set_progress.name || set_progress.set_num}"
										tone={set_progress.pct >= 100 ? 'success' : 'primary'}
									/>
								</span>
								<span class="mt-2 block text-sm {missing_parts.length > 0 ? 'text-ink-muted' : 'text-success-ink'}">
									{missing_parts.length > 0 ? `${missing_parts.length} parts still missing` : 'Complete'}
								</span>
							</span>
						</button>

						{#if is_expanded && missing_parts.length > 0}
							<div class="overflow-x-auto">
								<table class="data-table">
									<thead>
										<tr>
											<th>Part</th>
											<th>Color</th>
											<th class="num">Found</th>
											<th class="num">Needed</th>
										</tr>
									</thead>
									<tbody>
										{#each missing_parts as part}
											<tr>
												<td>
													<div class="num">{part.part_num}</div>
													{#if part.part_name}<div class="text-ink-muted">{part.part_name}</div>{/if}
												</td>
												<td>{colorLabel(part)}</td>
												<td class="num">{part.quantity_found}</td>
												<td class="num">{part.quantity_needed}</td>
											</tr>
										{/each}
									</tbody>
								</table>
							</div>
						{/if}
						{#if is_expanded}
							<div class="flex justify-end border-t border-line px-(--pad-panel) py-3">
								<Button
									variant="ghost"
									size="sm"
									icon={RotateCcw}
									loading={resetting === set_progress.id}
									onclick={() => resetKit(set_progress)}>Count from zero</Button
								>
							</div>
						{/if}
					</Panel>
				{/each}
			</div>
		{:else}
			<p class="flex items-center justify-center gap-2 py-12 text-sm text-ink-muted">
				<Spinner size={16} />
				Loading the set progress
			</p>
		{/if}
	</div>
</AppShell>
