<script lang="ts">
	import { onMount } from 'svelte';
	import { getMachineContext } from '$lib/machines/context';
	import { getBackendHttpBase } from '$lib/backend';
	import AppShell from '$lib/components/AppShell.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Select from '$lib/components/ui/Select.svelte';

	type MachineStateStats = {
		current_state?: string;
		state_share_pct?: Record<string, number>;
		state_time_s?: Record<string, number>;
	};

	type TimelineEvent = {
		ts: number;
		machine: string;
		to_state?: string | null;
	};

	type RuntimeStatsRecordItem = {
		record_id: string;
		run_id: string;
		started_at: number;
		ended_at: number;
		total_pieces: number;
	};

	const WINDOW_S = 180;
	// The classification channel reports its phase as "classification".
	const OCCUPANCY_LANE_PREFERRED_ORDER = ['classification', 'distribution.occupancy'];

	const machine_ctx = getMachineContext();

	let loaded_runtime_stats = $state<Record<string, unknown> | null>(null);
	let live_runtime_stats = $state<Record<string, unknown> | null>(null);
	let records = $state<RuntimeStatsRecordItem[]>([]);
	let selected_record_id = $state<string>('live');
	let selected_group = $state<string>('all');
	let records_error = $state<string | null>(null);

	const runtime_stats = $derived(
		(loaded_runtime_stats ?? live_runtime_stats ?? {}) as Record<string, unknown>
	);
	const state_machines = $derived(
		(runtime_stats.state_machines ?? {}) as Record<string, MachineStateStats>
	);
	const timeline_recent = $derived(
		(runtime_stats.timeline_recent ?? []) as TimelineEvent[]
	);
	const now_s = $derived.by(() => {
		void runtime_stats; // the window ends at the latest snapshot
		return Date.now() / 1000.0;
	});
	const window_start = $derived.by(() => now_s - WINDOW_S);

	// A state's color is derived from its name (and its subsystem), so the same
	// state is the same color in both charts. There are too many states for a
	// fixed palette.
	function distinctColorForGroupState(group_name: string, state_name: string): string {
		const group_offsets: Record<string, number> = {
			feeder: 0,
			classification: 120,
			distribution: 240,
			other: 60
		};
		const base_offset = group_offsets[group_name] ?? group_offsets.other;
		let hash = 0;
		for (let i = 0; i < state_name.length; i += 1) {
			hash = (hash * 31 + state_name.charCodeAt(i)) >>> 0;
		}
		const slot = hash % 16;
		const hue = (base_offset + slot * 23) % 360;
		const sat = 58 + (slot % 3) * 4;
		const light = slot % 2 === 0 ? 56 : 62;
		return `hsl(${hue} ${sat}% ${light}%)`;
	}

	function machineGroup(machine_name: string): string {
		const group = machine_name.split('.')[0];
		return ['feeder', 'classification', 'distribution'].includes(group) ? group : 'other';
	}

	function isOccupancyMachine(machine_name: string): boolean {
		return machine_name === 'classification' || machine_name.endsWith('.occupancy');
	}

	function orderedOccupancyMachines(machine_names: string[]): string[] {
		const unique = new Set(machine_names.filter(isOccupancyMachine));
		const ordered: string[] = [];
		for (const preferred of OCCUPANCY_LANE_PREFERRED_ORDER) {
			if (unique.has(preferred)) {
				ordered.push(preferred);
				unique.delete(preferred);
			}
		}
		for (const remaining of Array.from(unique).sort()) {
			ordered.push(remaining);
		}
		return ordered;
	}

	function buildSegments(
		machine_name: string,
		events: TimelineEvent[],
		current_state: string | undefined,
		now_ts: number,
		start_ts: number
	): { state: string; start: number; end: number; machine: string }[] {
		const machine_events = events
			.filter((event) => event.machine === machine_name && event.ts <= now_ts)
			.sort((a, b) => a.ts - b.ts);
		const out: { state: string; start: number; end: number; machine: string }[] = [];

		let state_at_start = current_state ?? 'unknown';
		for (const event of machine_events) {
			if (event.ts <= start_ts) {
				state_at_start = event.to_state ?? state_at_start;
				continue;
			}
			break;
		}

		let active_state = state_at_start;
		let segment_start = start_ts;
		for (const event of machine_events) {
			if (event.ts <= start_ts) {
				continue;
			}
			const segment_end = Math.min(now_ts, event.ts);
			if (segment_end > segment_start) {
				out.push({
					state: active_state,
					start: segment_start,
					end: segment_end,
					machine: machine_name
				});
			}
			active_state = event.to_state ?? active_state;
			segment_start = event.ts;
		}

		if (now_ts > segment_start) {
			out.push({
				state: active_state,
				start: segment_start,
				end: now_ts,
				machine: machine_name
			});
		}

		return out;
	}

	async function loadRecords() {
		records_error = null;
		try {
			const response = await fetch(`${getBackendHttpBase()}/runtime-stats/records`);
			if (!response.ok) {
				throw new Error(`HTTP ${response.status}`);
			}
			const body = (await response.json()) as { records?: RuntimeStatsRecordItem[] };
			records = Array.isArray(body.records) ? body.records : [];
		} catch (error) {
			records = [];
			records_error = error instanceof Error ? error.message : 'failed loading records';
		}
	}

	// The full snapshot (with the state timeline) is not pushed; poll it while
	// this page shows the live run.
	async function loadLive() {
		if (selected_record_id !== 'live' || document.hidden) return;
		try {
			const response = await fetch(`${getBackendHttpBase()}/runtime-stats`);
			if (response.ok) live_runtime_stats = (await response.json()).payload ?? null;
		} catch {
			// The next poll retries.
		}
	}

	async function selectRecord(record_id: string) {
		selected_record_id = record_id;
		if (record_id === 'live') {
			loaded_runtime_stats = null;
			return;
		}
		records_error = null;
		try {
			const response = await fetch(
				`${getBackendHttpBase()}/runtime-stats/record/${encodeURIComponent(record_id)}`
			);
			if (!response.ok) {
				throw new Error(`HTTP ${response.status}`);
			}
			const body = (await response.json()) as { payload?: Record<string, unknown> };
			loaded_runtime_stats = (body.payload ?? {}) as Record<string, unknown>;
		} catch (error) {
			records_error = error instanceof Error ? error.message : 'failed loading record';
			loaded_runtime_stats = null;
			selected_record_id = 'live';
		}
	}

	onMount(() => {
		loadRecords();
		void loadLive();
		const live_timer = setInterval(loadLive, 2000);
		return () => clearInterval(live_timer);
	});

	// The lanes both charts draw: the occupancy machines, narrowed to the chosen subsystem.
	const machines_for_chart = $derived.by(() => {
		const occupancy_machines = orderedOccupancyMachines(Object.keys(state_machines));
		const chart_machines =
			occupancy_machines.length > 0 ? occupancy_machines : Object.keys(state_machines).sort();
		const filtered =
			selected_group === 'all'
				? chart_machines
				: chart_machines.filter((machine_name) => machineGroup(machine_name) === selected_group);
		return filtered.length > 0 ? filtered : chart_machines;
	});

	type Slice = { label: string; share: number; color: string };
	const composition = $derived(
		machines_for_chart.map((machine) => {
			const group = machineGroup(machine);
			const slices: Slice[] = Object.entries(state_machines[machine]?.state_share_pct ?? {})
				.map(([state, share]) => ({
					label: `${group}.${state}`,
					share,
					color: distinctColorForGroupState(group, state)
				}))
				.sort((a, b) => a.label.localeCompare(b.label));
			return { machine, slices };
		})
	);
	const legend = $derived(
		[...new Map(composition.flatMap((row) => row.slices).map((slice) => [slice.label, slice])).values()].sort(
			(a, b) => a.label.localeCompare(b.label)
		)
	);

	const gantt = $derived(
		machines_for_chart.map((machine) => ({
			machine,
			segments: buildSegments(
				machine,
				timeline_recent,
				state_machines[machine]?.current_state,
				now_s,
				window_start
			).map((seg) => ({
				...seg,
				left: ((seg.start - window_start) / WINDOW_S) * 100,
				width: ((seg.end - seg.start) / WINDOW_S) * 100,
				color: distinctColorForGroupState(machineGroup(machine), seg.state)
			}))
		}))
	);

	const top_occupancy_states = $derived.by(() => {
		const rows: [string, number][] = [];
		for (const machine_name of machines_for_chart) {
			const times = state_machines[machine_name]?.state_time_s ?? {};
			for (const [state_name, seconds] of Object.entries(times)) {
				rows.push([`${machine_name} :: ${state_name}`, seconds]);
			}
		}
		return rows.sort((a, b) => b[1] - a[1]).slice(0, 12);
	});

	function fmtRecordLabel(record: RuntimeStatsRecordItem): string {
		const date = new Date(record.started_at * 1000).toLocaleString();
		return `${date} • ${record.total_pieces} pcs • ${record.run_id.slice(0, 8)}`;
	}
</script>

<svelte:head><title>Sorter - Runtime</title></svelte:head>

<AppShell>
	<div class="mx-auto flex w-full max-w-[1500px] flex-col gap-(--gap-panels) px-4 py-6 sm:px-6">
		<PageHeader title="Runtime" description="How long each part of the machine spent in each state.">
			{#snippet actions()}
				<Select
					label="Subsystem"
					class="w-full sm:w-44"
					bind:value={selected_group}
					options={[
						{ value: 'all', label: 'All subsystems' },
						{ value: 'feeder', label: 'Feeder' },
						{ value: 'classification', label: 'Classification' },
						{ value: 'distribution', label: 'Distribution' }
					]}
				/>
				<Select
					label="Run"
					class="w-full sm:w-72"
					value={selected_record_id}
					onchange={selectRecord}
					options={[
						{ value: 'live', label: 'Live runtime' },
						...records.map((record) => ({ value: record.record_id, label: fmtRecordLabel(record) }))
					]}
				/>
				<Button onclick={loadRecords}>Refresh</Button>
			{/snippet}
		</PageHeader>

		{#if records_error}<Alert tone="danger">Could not load the records: {records_error}</Alert>{/if}

		{#if !machine_ctx.machine && !loaded_runtime_stats}
			<EmptyState title="No machine is selected" />
		{:else}
			<div class="grid grid-cols-1 gap-(--gap-panels) lg:grid-cols-2">
				<Panel title="Occupancy share by subsystem" description="Percent of the run spent in each state.">
					{#if composition.length === 0}
						<p class="text-sm text-ink-muted">No occupancy data yet.</p>
					{:else}
						<div class="flex flex-col gap-4 rounded-control bg-well p-4">
							<div class="flex flex-col gap-2">
								{#each composition as row (row.machine)}
									<div class="flex items-center gap-3 text-sm">
										<span class="w-40 shrink-0 truncate text-ink" title={row.machine}>{row.machine}</span>
										<div class="flex h-5 flex-1 overflow-hidden rounded-badge bg-track">
											{#each row.slices as slice (slice.label)}
												<div
													style:width="{slice.share}%"
													style:background-color={slice.color}
													title="{slice.label}: {slice.share.toFixed(1)}%"
												></div>
											{/each}
										</div>
									</div>
								{/each}
							</div>
							<ul class="flex flex-wrap gap-x-4 gap-y-1 text-sm text-ink-muted">
								{#each legend as slice (slice.label)}
									<li class="flex items-center gap-1.5">
										<span class="size-2.5 shrink-0" style:background-color={slice.color}></span>
										{slice.label}
									</li>
								{/each}
							</ul>
						</div>
					{/if}
				</Panel>

				<Panel title="Occupancy over the last {WINDOW_S} seconds" description="Each bar is a state; hover it for its length.">
					{#if gantt.length === 0}
						<p class="text-sm text-ink-muted">No occupancy data yet.</p>
					{:else}
						<div class="flex flex-col gap-2 rounded-control bg-well p-4">
							{#each gantt as row (row.machine)}
								<div class="flex items-center gap-3 text-sm">
									<span class="w-40 shrink-0 truncate text-ink" title={row.machine}>{row.machine}</span>
									<div class="relative h-5 flex-1 overflow-hidden bg-track">
										{#each row.segments as seg, i (i)}
											<div
												class="absolute inset-y-0"
												style:left="{seg.left}%"
												style:width="{seg.width}%"
												style:background-color={seg.color}
												title="{seg.state} {(seg.end - seg.start).toFixed(2)}s"
											></div>
										{/each}
									</div>
								</div>
							{/each}
							<div class="num ml-[10.75rem] flex justify-between text-xs text-ink-muted">
								<span>{WINDOW_S} s ago</span><span>{WINDOW_S / 2} s</span><span>now</span>
							</div>
						</div>
					{/if}
				</Panel>
			</div>

			<Panel title="Top occupancy blocks" description="Run total.">
				{#if top_occupancy_states.length === 0}
					<p class="text-sm text-ink-muted">No occupancy data yet.</p>
				{:else}
					<ul class="grid grid-cols-1 gap-x-8 gap-y-1 text-sm md:grid-cols-2">
						{#each top_occupancy_states as [name, seconds]}
							<li class="flex items-center justify-between gap-3 text-ink-muted">
								<span class="truncate">{name}</span>
								<span class="num shrink-0 text-ink">{seconds.toFixed(2)} s</span>
							</li>
						{/each}
					</ul>
				{/if}
			</Panel>
		{/if}
	</div>
</AppShell>
