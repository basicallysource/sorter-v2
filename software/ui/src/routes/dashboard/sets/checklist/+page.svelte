<script lang="ts">
	import { onMount } from 'svelte';
	import { getMachinesContext } from '$lib/machines/context';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { ArrowLeft, Printer } from 'lucide-svelte';

	type SetPart = {
		part_num: string;
		color_id: number;
		quantity_needed: number;
		quantity_found: number;
	};

	type SetProgress = {
		set_num: string;
		total_needed: number;
		total_found: number;
		pct: number;
		parts: SetPart[];
	};

	const manager = getMachinesContext();

	let sets = $state<SetProgress[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);

	function currentBackendBaseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(manager.selectedMachine?.url) ?? backendHttpBaseUrl;
	}

	async function fetchProgress() {
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/set-progress`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			sets = data.progress?.sets ?? [];
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load';
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		fetchProgress();
	});
</script>

<svelte:head>
	<style>
		@media print {
			nav, .no-print { display: none !important; }
			body { font-size: 10pt; }
			.print-break { page-break-before: always; }
		}
	</style>
</svelte:head>

<div class="min-h-screen bg-bg p-6">
	<div class="no-print mb-4 flex items-center justify-between">
		<div class="flex items-center gap-3">
			<a href="/dashboard/sets" class="p-2 text-text transition-colors hover:bg-surface" title="Back">
				<ArrowLeft size={20} />
			</a>
			<h1 class="text-xl font-bold text-text">Parts Checklist</h1>
		</div>
		<button
			onclick={() => window.print()}
			class="flex items-center gap-1 border border-border px-3 py-2 text-sm text-text hover:bg-surface"
		>
			<Printer size={16} />
			Print
		</button>
	</div>

	{#if loading}
		<div class="py-12 text-center text-text-muted">Loading...</div>
	{:else if error}
		<div class="text-sm text-red-600">{error}</div>
	{:else}
		{#each sets as set_progress, idx}
			<div class={idx > 0 ? 'print-break' : ''}>
				<div class="mb-3 mt-6 flex items-baseline justify-between border-b border-border pb-2">
					<h2 class="text-lg font-bold text-text">{set_progress.set_num}</h2>
					<span class="text-sm text-text-muted">
						{set_progress.total_found}/{set_progress.total_needed} ({set_progress.pct}%)
					</span>
				</div>
				<table class="w-full text-sm">
					<thead>
						<tr class="border-b border-border text-text-muted">
							<th class="pb-1 text-left font-medium">Part Number</th>
							<th class="pb-1 text-left font-medium">Color ID</th>
							<th class="pb-1 text-right font-medium">Needed</th>
							<th class="pb-1 text-right font-medium">Found</th>
							<th class="pb-1 text-right font-medium">Missing</th>
							<th class="pb-1 text-center font-medium">Status</th>
						</tr>
					</thead>
					<tbody>
						{#each set_progress.parts as part}
							{@const missing = part.quantity_needed - part.quantity_found}
							<tr class="border-b border-border/50 text-text">
								<td class="py-1">{part.part_num}</td>
								<td class="py-1">{part.color_id}</td>
								<td class="py-1 text-right tabular-nums">{part.quantity_needed}</td>
								<td class="py-1 text-right tabular-nums">{part.quantity_found}</td>
								<td class="py-1 text-right tabular-nums {missing > 0 ? 'text-red-500' : ''}">{missing}</td>
								<td class="py-1 text-center">
									{#if missing <= 0}
										<span class="text-green-600">OK</span>
									{:else}
										<span class="text-text-muted">---</span>
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/each}
	{/if}
</div>
