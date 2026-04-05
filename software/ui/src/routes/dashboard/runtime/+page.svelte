<script lang="ts">
	import { onMount } from 'svelte';
	import { getMachinesContext, getMachineContext } from '$lib/machines/context';
	import MachineDropdown from '$lib/components/MachineDropdown.svelte';
	import ThemeToggle from '$lib/components/ThemeToggle.svelte';
	import { backendHttpBaseUrl, backendWsBaseUrl } from '$lib/backend';
	import { settings } from '$lib/stores/settings';
	import { ArrowLeft } from 'lucide-svelte';

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

	type ChartCtor = new (
		ctx: CanvasRenderingContext2D,
		config: Record<string, unknown>
	) => {
		data: Record<string, unknown>;
		options: Record<string, unknown>;
		update: (mode?: string) => void;
		destroy: () => void;
	};

	const WINDOW_S = 180;
	const OCCUPANCY_LANE_PREFERRED_ORDER = [
		'feeder.ch1',
		'feeder.ch2',
		'feeder.ch3',
		'classification.occupancy',
		'distribution.occupancy'
	];

	const manager = getMachinesContext();
	const machine_ctx = getMachineContext();

	let loaded_runtime_stats = $state<Record<string, unknown> | null>(null);
	let records = $state<RuntimeStatsRecordItem[]>([]);
	let selected_record_id = $state<string>('live');
	let selected_group = $state<string>('all');
	let records_error = $state<string | null>(null);

	let composition_canvas = $state<HTMLCanvasElement | null>(null);
	let gantt_canvas = $state<HTMLCanvasElement | null>(null);
	let composition_chart: InstanceType<ChartCtor> | null = null;
	let gantt_chart: InstanceType<ChartCtor> | null = null;
	let chart_constructor: ChartCtor | null = null;

	function cssVar(name: string, fallback: string): string {
		if (typeof document === 'undefined') return fallback;
		const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
		return value || fallback;
	}

	function chartPalette() {
		return {
			text: cssVar('--color-text', '#1A1A1A'),
			textMuted: cssVar('--color-text-muted', '#7A7770'),
			border: cssVar('--color-border', '#E2E0DB'),
			surface: cssVar('--color-surface', '#FFFFFF'),
			background: cssVar('--color-bg', '#F7F6F3')
		};
	}

	function applyChartTheme() {
		if (!composition_chart || !gantt_chart) return;
		const palette = chartPalette();
		const grid_color = `${palette.border}CC`;

		const composition_options = composition_chart.options as {
			plugins?: { legend?: { labels?: Record<string, unknown> } };
			scales?: {
				x?: { ticks?: Record<string, unknown>; title?: Record<string, unknown>; grid?: Record<string, unknown> };
				y?: { ticks?: Record<string, unknown>; title?: Record<string, unknown>; grid?: Record<string, unknown> };
			};
		};
		composition_options.plugins ??= {};
		composition_options.plugins.legend ??= {};
		composition_options.plugins.legend.labels ??= {};
		composition_options.plugins.legend.labels.color = palette.text;
		composition_options.scales ??= {};
		composition_options.scales.x ??= {};
		composition_options.scales.y ??= {};
		composition_options.scales.x.ticks ??= {};
		composition_options.scales.x.title ??= {};
		composition_options.scales.x.grid ??= {};
		composition_options.scales.y.ticks ??= {};
		composition_options.scales.y.title ??= {};
		composition_options.scales.y.grid ??= {};
		composition_options.scales.x.ticks.color = palette.textMuted;
		composition_options.scales.x.title.color = palette.text;
		composition_options.scales.x.grid.color = grid_color;
		composition_options.scales.y.ticks.color = palette.textMuted;
		composition_options.scales.y.title.color = palette.text;
		composition_options.scales.y.grid.color = grid_color;

		const gantt_options = gantt_chart.options as {
			plugins?: { tooltip?: Record<string, unknown> };
			scales?: {
				x?: { ticks?: Record<string, unknown>; title?: Record<string, unknown>; grid?: Record<string, unknown> };
				y?: { ticks?: Record<string, unknown>; title?: Record<string, unknown>; grid?: Record<string, unknown> };
			};
		};
		gantt_options.plugins ??= {};
		gantt_options.plugins.tooltip ??= {};
		gantt_options.plugins.tooltip.backgroundColor = palette.surface;
		gantt_options.plugins.tooltip.titleColor = palette.text;
		gantt_options.plugins.tooltip.bodyColor = palette.text;
		gantt_options.plugins.tooltip.borderColor = palette.border;
		gantt_options.plugins.tooltip.borderWidth = 1;
		gantt_options.scales ??= {};
		gantt_options.scales.x ??= {};
		gantt_options.scales.y ??= {};
		gantt_options.scales.x.ticks ??= {};
		gantt_options.scales.x.title ??= {};
		gantt_options.scales.x.grid ??= {};
		gantt_options.scales.y.ticks ??= {};
		gantt_options.scales.y.title ??= {};
		gantt_options.scales.y.grid ??= {};
		gantt_options.scales.x.ticks.color = palette.textMuted;
		gantt_options.scales.x.title.color = palette.text;
		gantt_options.scales.x.grid.color = grid_color;
		gantt_options.scales.y.ticks.color = palette.textMuted;
		gantt_options.scales.y.title.color = palette.text;
		gantt_options.scales.y.grid.color = grid_color;
	}

	const runtime_stats = $derived(
		(loaded_runtime_stats ?? machine_ctx.machine?.runtimeStats ?? {}) as Record<string, unknown>
	);
	const state_machines = $derived(
		(runtime_stats.state_machines ?? {}) as Record<string, MachineStateStats>
	);
	const timeline_recent = $derived(
		(runtime_stats.timeline_recent ?? []) as TimelineEvent[]
	);
	const now_s = $derived.by(() => Date.now() / 1000.0);
	const window_start = $derived.by(() => now_s - WINDOW_S);

	function loadScript(src: string): Promise<void> {
		return new Promise((resolve, reject) => {
			const existing = document.querySelector(`script[src="${src}"]`);
			if (existing) {
				resolve();
				return;
			}
			const script = document.createElement('script');
			script.src = src;
			script.async = true;
			script.onload = () => resolve();
			script.onerror = () => reject(new Error(`Failed to load ${src}`));
			document.head.appendChild(script);
		});
	}

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
		if (machine_name.startsWith('feeder.')) return 'feeder';
		if (machine_name.startsWith('classification.')) return 'classification';
		if (machine_name.startsWith('distribution.')) return 'distribution';
		return 'other';
	}

	function isOccupancyMachine(machine_name: string): boolean {
		if (machine_name.startsWith('feeder.ch')) return true;
		if (machine_name.endsWith('.occupancy')) return true;
		return false;
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
			const response = await fetch(`${backendHttpBaseUrl}/runtime-stats/records`);
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

	async function selectRecord(record_id: string) {
		selected_record_id = record_id;
		if (record_id === 'live') {
			loaded_runtime_stats = null;
			return;
		}
		records_error = null;
		try {
			const response = await fetch(
				`${backendHttpBaseUrl}/runtime-stats/record/${encodeURIComponent(record_id)}`
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

	function updateCharts() {
		if (!composition_chart || !gantt_chart) return;

		const occupancy_machines = orderedOccupancyMachines(Object.keys(state_machines));
		const chart_machines =
			occupancy_machines.length > 0 ? occupancy_machines : Object.keys(state_machines).sort();
		const filtered_chart_machines =
			selected_group === 'all'
				? chart_machines
				: chart_machines.filter((machine_name) => machineGroup(machine_name) === selected_group);
		const machines_for_chart =
			filtered_chart_machines.length > 0 ? filtered_chart_machines : chart_machines;

		const dataset_map = new Map<
			string,
			{
				label: string;
				backgroundColor: string;
				data: number[];
			}
		>();
		for (let machine_idx = 0; machine_idx < machines_for_chart.length; machine_idx += 1) {
			const machine_name = machines_for_chart[machine_idx];
			const group_name = machineGroup(machine_name);
			const shares = state_machines[machine_name]?.state_share_pct ?? {};
			for (const [state_name, share] of Object.entries(shares)) {
				const key = `${group_name}::${state_name}`;
				let dataset = dataset_map.get(key);
				if (!dataset) {
					dataset = {
						label: `${group_name}.${state_name}`,
						backgroundColor: distinctColorForGroupState(group_name, state_name),
						data: Array.from({ length: machines_for_chart.length }, () => 0)
					};
					dataset_map.set(key, dataset);
				}
				dataset.data[machine_idx] = share;
			}
		}

		const composition_datasets = Array.from(dataset_map.values()).sort((a, b) =>
			a.label.localeCompare(b.label)
		);

		composition_chart.data = {
			labels: machines_for_chart,
			datasets: composition_datasets
		};
		composition_chart.update('none');

		const segments: {
			x: [number, number];
			y: string;
			state: string;
			duration_s: number;
		}[] = [];
		for (const machine_name of machines_for_chart) {
			const current_state = state_machines[machine_name]?.current_state;
			const machine_segments = buildSegments(
				machine_name,
				timeline_recent,
				current_state,
				now_s,
				window_start
			);
			for (const seg of machine_segments) {
				segments.push({
					x: [seg.start - window_start, seg.end - window_start],
					y: seg.machine,
					state: seg.state,
					duration_s: seg.end - seg.start
				});
			}
		}

		const segment_colors = segments.map((seg) =>
			distinctColorForGroupState(machineGroup(seg.y), seg.state)
		);
		gantt_chart.data = {
			datasets: [
				{
					label: 'occupancy',
					data: segments,
					backgroundColor: segment_colors,
					borderWidth: 0
				}
			]
		};
		const options = gantt_chart.options as {
			scales?: {
				x?: { min?: number; max?: number };
				y?: { labels?: string[] };
			};
		};
		if (options.scales?.x) {
			options.scales.x.min = 0;
			options.scales.x.max = WINDOW_S;
		}
		if (options.scales?.y) {
			options.scales.y.labels = machines_for_chart;
		}
		gantt_chart.update('none');
	}

	onMount(() => {
		let disposed = false;
		let initialized = false;
		if (manager.connectedMachines.length === 0) {
			manager.connect(`${backendWsBaseUrl}/ws`);
		}
		loadRecords();

		loadScript('https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js').then(() => {
			if (disposed) {
				return;
			}
			const chart_global = (window as Window & { Chart?: ChartCtor }).Chart;
			if (!chart_global || !composition_canvas || !gantt_canvas) {
				return;
			}
			chart_constructor = chart_global;

			const comp_ctx = composition_canvas.getContext('2d');
			const gantt_ctx = gantt_canvas.getContext('2d');
			if (!comp_ctx || !gantt_ctx) return;

			composition_chart = new chart_constructor(comp_ctx, {
				type: 'bar',
				data: { labels: [], datasets: [] },
				options: {
					indexAxis: 'y',
					responsive: true,
					maintainAspectRatio: false,
					animation: false,
					layout: {
						padding: {
							right: 24
						}
					},
					plugins: {
						legend: {
							position: 'right',
							align: 'start',
							fullSize: true,
							labels: {
								usePointStyle: true,
								pointStyle: 'rect',
								boxWidth: 10,
								boxHeight: 10,
								padding: 10,
								font: {
									size: 10
								}
							}
						}
					},
					scales: {
						x: { stacked: true, min: 0, max: 100, title: { display: true, text: '%' } },
						y: { stacked: true }
					}
				}
			});

			gantt_chart = new chart_constructor(gantt_ctx, {
				type: 'bar',
				data: { datasets: [] },
				options: {
					indexAxis: 'y',
					responsive: true,
					maintainAspectRatio: false,
					animation: false,
					parsing: {
						xAxisKey: 'x',
						yAxisKey: 'y'
					},
					plugins: {
						legend: { display: false },
						tooltip: {
							callbacks: {
								label: (ctx: { raw?: { duration_s?: number; state?: string } }) => {
									const state_name = (ctx.raw as { state?: string } | undefined)?.state ?? 'unknown';
									const duration_s = ctx.raw?.duration_s ?? 0;
									return `${state_name} ${duration_s.toFixed(2)}s`;
								}
							}
						}
					},
					scales: {
						x: { type: 'linear', min: 0, max: WINDOW_S, title: { display: true, text: 'seconds' } },
						y: { type: 'category', labels: [] }
					}
				}
			});
			initialized = true;
			applyChartTheme();
			updateCharts();
		});

		return () => {
			disposed = true;
			if (initialized) {
				composition_chart?.destroy();
				gantt_chart?.destroy();
				composition_chart = null;
				gantt_chart = null;
			}
		};
	});

	$effect(() => {
		runtime_stats;
		if (!chart_constructor) return;
		updateCharts();
	});

	$effect(() => {
		$settings.theme;
		if (!chart_constructor || !composition_chart || !gantt_chart) return;
		applyChartTheme();
		composition_chart.update('none');
		gantt_chart.update('none');
	});

	const top_occupancy_states = $derived.by(() => {
		const rows: [string, number][] = [];
		const occupancy_machines = orderedOccupancyMachines(Object.keys(state_machines));
		const chart_machines =
			occupancy_machines.length > 0 ? occupancy_machines : Object.keys(state_machines).sort();
		const filtered_chart_machines =
			selected_group === 'all'
				? chart_machines
				: chart_machines.filter((machine_name) => machineGroup(machine_name) === selected_group);
		const machines_for_chart =
			filtered_chart_machines.length > 0 ? filtered_chart_machines : chart_machines;
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

<div class="min-h-screen bg-bg p-6">
	<div class="mb-4 flex items-center justify-between">
		<div class="flex items-center gap-3">
			<a
				href="/"
				class="p-2 text-text transition-colors hover:bg-surface"
				title="Back"
			>
				<ArrowLeft size={20} />
			</a>
			<h1 class="text-xl font-bold text-text">Runtime Dashboard</h1>
		</div>
		<div class="flex items-center gap-2">
			<ThemeToggle />
			<select
				class="border border-border bg-surface px-2 py-1 text-xs text-text"
				value={selected_group}
				onchange={(event) => (selected_group = (event.currentTarget as HTMLSelectElement).value)}
			>
				<option value="all">All Subsystems</option>
				<option value="feeder">Feeder</option>
				<option value="classification">Classification</option>
				<option value="distribution">Distribution</option>
			</select>
			<select
				class="border border-border bg-surface px-2 py-1 text-xs text-text"
				value={selected_record_id}
				onchange={(event) => selectRecord((event.currentTarget as HTMLSelectElement).value)}
			>
				<option value="live">Live Runtime</option>
				{#each records as record}
					<option value={record.record_id}>{fmtRecordLabel(record)}</option>
				{/each}
			</select>
			<button
				class="border border-border px-2 py-1 text-xs text-text"
				onclick={loadRecords}
			>
				Refresh
			</button>
			<MachineDropdown />
		</div>
	</div>

	{#if records_error}
		<div class="dark:text-red-400 mb-3 text-xs text-[#D01012]">Record load error: {records_error}</div>
	{/if}

	{#if !machine_ctx.machine && !loaded_runtime_stats}
		<div class="py-12 text-center text-text-muted">
			No machine selected.
		</div>
	{:else}
		<div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
			<div class="border border-border bg-surface p-3">
				<div class="mb-2 text-sm font-medium text-text">
					Occupancy Share By Subsystem
				</div>
				<div class="h-[460px]">
					<canvas bind:this={composition_canvas}></canvas>
				</div>
			</div>

			<div class="border border-border bg-surface p-3">
				<div class="mb-2 text-sm font-medium text-text">
					Occupancy Gantt (Last {WINDOW_S}s)
				</div>
				<div class="h-[380px]">
					<canvas bind:this={gantt_canvas}></canvas>
				</div>
			</div>
		</div>

		<div class="mt-4 border border-border bg-surface p-3">
			<div class="mb-2 text-sm font-medium text-text">
				Top Occupancy Blocks (Run Total)
			</div>
			{#if top_occupancy_states.length === 0}
				<div class="text-xs text-text-muted">No occupancy data yet.</div>
			{:else}
				<div class="grid grid-cols-1 gap-1 text-xs md:grid-cols-2">
					{#each top_occupancy_states as [name, seconds]}
						<div class="flex items-center justify-between text-text-muted">
							<span class="truncate pr-2">{name}</span>
							<span class="tabular-nums">{seconds.toFixed(2)}s</span>
						</div>
					{/each}
				</div>
			{/if}
		</div>
	{/if}
</div>
