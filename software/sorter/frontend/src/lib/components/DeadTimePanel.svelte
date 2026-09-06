<script lang="ts">
	import { onMount } from 'svelte';
	import { getBackendHttpBase } from '$lib/backend';

	type Opportunity = {
		key: string;
		title: string;
		hint: string;
		seconds: number;
		share_pct: number;
		episodes: number;
		longest_s: number;
		breakdown: Record<string, number>;
		top_episodes: { start: number; end: number; seconds: number }[];
	};
	type StationTime = { time_s: Record<string, number>; coverage_s: number };
	type DeadTime = {
		window_s: number;
		now: number;
		stations: Record<string, StationTime>;
		opportunities: Opportunity[];
	};

	const STATION_ORDER = ['belt', 'c3', 'c4', 'distribution'];
	const REFRESH_MS = 15000;

	let minutes = $state(15);
	let data = $state<DeadTime | null>(null);
	let error = $state<string | null>(null);
	let expanded = $state<string | null>(null);

	async function load() {
		try {
			const response = await fetch(`${getBackendHttpBase()}/runtime-stats/dead-time?minutes=${minutes}`);
			if (!response.ok) throw new Error(`HTTP ${response.status}`);
			data = (await response.json()) as DeadTime;
			error = null;
		} catch (e) {
			error = e instanceof Error ? e.message : 'failed loading dead time';
		}
	}

	onMount(() => {
		void load();
		const timer = setInterval(() => void load(), REFRESH_MS);
		return () => clearInterval(timer);
	});

	$effect(() => {
		minutes;
		void load();
	});

	const stations = $derived.by(() => {
		const all = data?.stations ?? {};
		const names = [...STATION_ORDER.filter((n) => n in all), ...Object.keys(all).filter((n) => !STATION_ORDER.includes(n))];
		return names.map((name) => ({ name, ...all[name] }));
	});

	function pct(seconds: number): string {
		const window = data?.window_s ?? 0;
		return window > 0 ? `${((seconds / window) * 100).toFixed(0)}%` : '';
	}

	function fmtTime(ts: number): string {
		return new Date(ts * 1000).toLocaleTimeString();
	}
</script>

<div class="border border-border bg-surface p-3">
	<div class="mb-2 flex items-center justify-between">
		<div class="text-sm font-medium text-text">Dead time & overlap opportunities</div>
		<select
			class="border border-border bg-surface px-2 py-1 text-xs text-text"
			value={String(minutes)}
			onchange={(event) => (minutes = Number((event.currentTarget as HTMLSelectElement).value))}
		>
			<option value="5">Last 5 min</option>
			<option value="15">Last 15 min</option>
			<option value="60">Last 60 min</option>
			<option value="180">Last 3 h</option>
		</select>
	</div>
	<p class="mb-3 text-xs text-text-muted">
		Moments where one station waited while another could have kept working. Share is of the whole window; the breakdown says what the other station was doing meanwhile.
	</p>

	{#if error}
		<div class="text-xs text-danger">Dead time load error: {error}</div>
	{:else if !data}
		<div class="text-xs text-text-muted">Loading…</div>
	{:else if data.opportunities.length === 0}
		<div class="text-xs text-text-muted">No station data in this window yet.</div>
	{:else}
		<table class="w-full text-xs">
			<thead class="text-left text-text-muted">
				<tr>
					<th class="py-1 pr-2 font-medium">Gap</th>
					<th class="py-1 pr-2 text-right font-medium">Time</th>
					<th class="py-1 pr-2 text-right font-medium">Share</th>
					<th class="py-1 pr-2 text-right font-medium">Episodes</th>
					<th class="py-1 pr-2 text-right font-medium">Longest</th>
					<th class="py-1 font-medium">Meanwhile</th>
				</tr>
			</thead>
			<tbody>
				{#each data.opportunities as opp (opp.key)}
					<tr
						class="cursor-pointer border-t border-border align-top text-text hover:bg-bg"
						onclick={() => (expanded = expanded === opp.key ? null : opp.key)}
					>
						<td class="py-1 pr-2">{opp.title}</td>
						<td class="py-1 pr-2 text-right tabular-nums">{opp.seconds.toFixed(0)} s</td>
						<td class="py-1 pr-2 text-right tabular-nums">{opp.share_pct.toFixed(0)}%</td>
						<td class="py-1 pr-2 text-right tabular-nums">{opp.episodes}</td>
						<td class="py-1 pr-2 text-right tabular-nums">{opp.longest_s.toFixed(0)} s</td>
						<td class="py-1 text-text-muted">
							{Object.entries(opp.breakdown)
								.slice(0, 3)
								.map(([k, v]) => `${k} ${v.toFixed(0)} s`)
								.join(' · ')}
						</td>
					</tr>
					{#if expanded === opp.key}
						<tr class="bg-bg text-xs text-text-muted">
							<td colspan="6" class="px-2 py-2">
								<div>{opp.hint}</div>
								{#if opp.top_episodes.length > 0}
									<div class="mt-1">
										Longest episodes:
										{opp.top_episodes.map((e) => `${fmtTime(e.start)} (${e.seconds.toFixed(0)} s)`).join(', ')}
									</div>
								{/if}
							</td>
						</tr>
					{/if}
				{/each}
			</tbody>
		</table>
	{/if}

	{#if stations.length > 0}
		<div class="mt-3 grid grid-cols-1 gap-2 text-xs md:grid-cols-2 xl:grid-cols-4">
			{#each stations as station (station.name)}
				<div class="border border-border p-2">
					<div class="mb-1 flex items-center justify-between text-text">
						<span class="font-medium uppercase">{station.name}</span>
						<span class="text-text-muted">{pct(station.coverage_s)} covered</span>
					</div>
					{#each Object.entries(station.time_s).slice(0, 5) as [activity, seconds] (activity)}
						<div class="flex items-center justify-between text-text-muted">
							<span class="truncate pr-2">{activity}</span>
							<span class="tabular-nums">{seconds.toFixed(0)} s · {pct(seconds)}</span>
						</div>
					{/each}
				</div>
			{/each}
		</div>
	{/if}
</div>
