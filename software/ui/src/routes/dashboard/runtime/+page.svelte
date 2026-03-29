<script lang="ts">
	import { onMount } from 'svelte';
	import { getMachinesContext, getMachineContext } from '$lib/machines/context';
	import MachineDropdown from '$lib/components/MachineDropdown.svelte';
	import { backendWsBaseUrl } from '$lib/backend';
	import { ArrowLeft } from 'lucide-svelte';

	type MachineStateStats = {
		current_state?: string;
		state_share_pct?: Record<string, number>;
	};

	type TimelineEvent = {
		ts: number;
		machine: string;
		to_state?: string | null;
	};

	type FeederSignalEvent = {
		ts: number;
		signal: string;
		active: boolean;
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
	const manager = getMachinesContext();
	const machine_ctx = getMachineContext();

	let composition_canvas = $state<HTMLCanvasElement | null>(null);
	let gantt_canvas = $state<HTMLCanvasElement | null>(null);
	let composition_chart: InstanceType<ChartCtor> | null = null;
	let gantt_chart: InstanceType<ChartCtor> | null = null;
	let chart_constructor: ChartCtor | null = null;

	const runtime_stats = $derived(
		(machine_ctx.machine?.runtimeStats ?? {}) as Record<string, unknown>
	);
	const state_machines = $derived(
		(runtime_stats.state_machines ?? {}) as Record<string, MachineStateStats>
	);
	const timeline_recent = $derived(
		(runtime_stats.timeline_recent ?? []) as TimelineEvent[]
	);
	const feeder_data = $derived((runtime_stats.feeder ?? {}) as Record<string, unknown>);
	const feeder_signal_timeline = $derived(
		(feeder_data.signal_timeline_recent ?? []) as FeederSignalEvent[]
	);
	const feeder_signals_current = $derived(
		(feeder_data.signals_current ?? {}) as Record<string, boolean>
	);
	const feeder_signal_time = $derived(
		(feeder_data.signal_time_s ?? {}) as Record<string, number>
	);
	const feeder_blocker_combo_time = $derived(
		(feeder_data.blocker_combo_time_s ?? {}) as Record<string, number>
	);
	const now_s = $derived.by(() => Date.now() / 1000.0);
	const window_start = $derived.by(() => now_s - WINDOW_S);

	function stateColor(state_name: string): string {
		const s = state_name.toLowerCase();
		if (s.includes('idle')) return '#6b7280';
		if (s.includes('feeding')) return '#0ea5e9';
		if (s.includes('detect')) return '#a855f7';
		if (s.includes('rotat')) return '#3b82f6';
		if (s.includes('snapp')) return '#f59e0b';
		if (s.includes('position')) return '#f97316';
		if (s.includes('ready')) return '#22c55e';
		if (s.includes('send')) return '#ef4444';
		if (s.includes('pulsing')) return '#22c55e';
		if (s.includes('waiting_chute')) return '#ef4444';
		if (s.includes('waiting_classification')) return '#a855f7';
		if (s.includes('waiting_ch2')) return '#0ea5e9';
		if (s.includes('waiting_ch3')) return '#3b82f6';
		if (s.includes('waiting_stepper')) return '#ec4899';
		if (s.includes('stable')) return '#f59e0b';
		return '#14b8a6';
	}

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

	function buildSegments(
		machine_name: string,
		events: TimelineEvent[],
		current_state: string | undefined,
		now_ts: number,
		start_ts: number
	): { state: string; start: number; end: number; machine: string }[] {
		const machine_events = events
			.filter((e) => e.machine === machine_name && e.ts >= start_ts && e.ts <= now_ts)
			.sort((a, b) => a.ts - b.ts);
		const out: { state: string; start: number; end: number; machine: string }[] = [];

		if (machine_events.length > 0) {
			for (let i = 0; i < machine_events.length; i += 1) {
				const current = machine_events[i];
				const next = machine_events[i + 1];
				const seg_start = Math.max(start_ts, current.ts);
				const seg_end = next ? Math.min(now_ts, next.ts) : now_ts;
				if (seg_end <= seg_start) continue;
				out.push({
					state: current.to_state ?? current_state ?? 'unknown',
					start: seg_start,
					end: seg_end,
					machine: machine_name
				});
			}
		} else if (current_state) {
			out.push({
				state: current_state,
				start: start_ts,
				end: now_ts,
				machine: machine_name
			});
		}

		return out;
	}

	function feederSignalColor(signal_name: string): string {
		const signal = signal_name.toLowerCase();
		if (signal.includes('wait_chute')) return '#ef4444';
		if (signal.includes('wait_classification')) return '#f59e0b';
		if (signal.includes('wait_ch2_dropzone')) return '#06b6d4';
		if (signal.includes('wait_ch3_dropzone')) return '#8b5cf6';
		if (signal.includes('wait_stepper')) return '#ec4899';
		if (signal.includes('pulse_sent')) return '#22c55e';
		if (signal.includes('pulse_intent')) return '#3b82f6';
		if (signal.includes('stepper_busy')) return '#f97316';
		if (signal.includes('stable')) return '#6b7280';
		return '#14b8a6';
	}

	function buildSignalSegments(
		signal_name: string,
		events: FeederSignalEvent[],
		current_active: boolean,
		now_ts: number,
		start_ts: number
	): { signal: string; start: number; end: number }[] {
		const signal_events = events
			.filter((event) => event.signal === signal_name && event.ts <= now_ts)
			.sort((a, b) => a.ts - b.ts);
		const out: { signal: string; start: number; end: number }[] = [];

		let active = false;
		for (const event of signal_events) {
			if (event.ts <= start_ts) {
				active = event.active;
				continue;
			}
			break;
		}

		if (signal_events.length === 0) {
			active = current_active;
		}

		let active_start = start_ts;
		for (const event of signal_events) {
			if (event.ts <= start_ts) {
				continue;
			}
			if (event.active && !active) {
				active = true;
				active_start = event.ts;
			} else if (!event.active && active) {
				const end_ts = Math.min(now_ts, event.ts);
				const start_clamped = Math.max(start_ts, active_start);
				if (end_ts > start_clamped) {
					out.push({
						signal: signal_name,
						start: start_clamped,
						end: end_ts
					});
				}
				active = false;
			}
		}

		if (active) {
			const start_clamped = Math.max(start_ts, active_start);
			if (now_ts > start_clamped) {
				out.push({
					signal: signal_name,
					start: start_clamped,
					end: now_ts
				});
			}
		}

		return out;
	}

	function updateCharts() {
		if (!composition_chart || !gantt_chart) return;
		const machine_names = Object.keys(state_machines);
		const labels =
			machine_names.length > 0 ? machine_names : ['feeder', 'classification', 'distribution'];

		const all_states = new Set<string>();
		for (const machine_name of labels) {
			const shares = state_machines[machine_name]?.state_share_pct ?? {};
			for (const state_name of Object.keys(shares)) {
				all_states.add(state_name);
			}
		}

		const composition_datasets = Array.from(all_states).map((state_name) => ({
			label: state_name,
			backgroundColor: stateColor(state_name),
			data: labels.map((machine_name) => state_machines[machine_name]?.state_share_pct?.[state_name] ?? 0)
		}));

		composition_chart.data = {
			labels,
			datasets: composition_datasets
		};
		composition_chart.update('none');

		const feeder_labels = new Set<string>();
		for (const signal_name of Object.keys(feeder_signals_current)) {
			feeder_labels.add(signal_name);
		}
		for (const signal_name of Object.keys(feeder_signal_time)) {
			feeder_labels.add(signal_name);
		}
		for (const event of feeder_signal_timeline) {
			feeder_labels.add(event.signal);
		}
		const signal_labels = Array.from(feeder_labels).sort();

		const segments: {
			x: [number, number];
			y: string;
			signal: string;
			duration_s: number;
		}[] = [];
		for (const signal_name of signal_labels) {
			const signal_segments = buildSignalSegments(
				signal_name,
				feeder_signal_timeline,
				Boolean(feeder_signals_current[signal_name]),
				now_s,
				window_start
			);
			for (const seg of signal_segments) {
				segments.push({
					x: [seg.start - window_start, seg.end - window_start],
					y: seg.signal,
					signal: seg.signal,
					duration_s: seg.end - seg.start
				});
			}
		}

		const segment_colors = segments.map((seg) => feederSignalColor(seg.signal));

		gantt_chart.data = {
			datasets: [
				{
					label: 'feeder signals',
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
			options.scales.y.labels = signal_labels;
		}
		gantt_chart.update('none');
	}

	onMount(() => {
		let disposed = false;
		let initialized = false;
		if (manager.connectedMachines.length === 0) {
			manager.connect(`${backendWsBaseUrl}/ws`);
		}

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
					plugins: {
						legend: { position: 'bottom' }
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
								label: (ctx: { raw?: { duration_s?: number; signal?: string } }) => {
									const state_name = (ctx.raw as { signal?: string } | undefined)?.signal ?? 'unknown';
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

	const top_blocker_combos = $derived.by(() =>
		Object.entries(feeder_blocker_combo_time)
			.filter(([combo_name, duration_s]) => combo_name !== 'none' && duration_s > 0)
			.sort((a, b) => b[1] - a[1])
			.slice(0, 8)
	);
</script>

<div class="dark:bg-bg-dark min-h-screen bg-bg p-6">
	<div class="mb-4 flex items-center justify-between">
		<div class="flex items-center gap-3">
			<a
				href="/"
				class="dark:text-text-dark dark:hover:bg-surface-dark p-2 text-text transition-colors hover:bg-surface"
				title="Back"
			>
				<ArrowLeft size={20} />
			</a>
			<h1 class="dark:text-text-dark text-xl font-bold text-text">Runtime Dashboard</h1>
		</div>
		<MachineDropdown />
	</div>

	{#if !machine_ctx.machine}
		<div class="dark:text-text-muted-dark py-12 text-center text-text-muted">
			No machine selected.
		</div>
	{:else}
		<div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
			<div class="dark:border-border-dark dark:bg-surface-dark border border-border bg-surface p-3">
				<div class="dark:text-text-dark mb-2 text-sm font-medium text-text">
					State Composition (Last {WINDOW_S}s)
				</div>
				<div class="h-[340px]">
					<canvas bind:this={composition_canvas}></canvas>
				</div>
			</div>

			<div class="dark:border-border-dark dark:bg-surface-dark border border-border bg-surface p-3">
				<div class="dark:text-text-dark mb-2 text-sm font-medium text-text">
					Feeder Signal Timeline (Last {WINDOW_S}s)
				</div>
				<div class="h-[340px]">
					<canvas bind:this={gantt_canvas}></canvas>
				</div>
			</div>
		</div>

		<div class="dark:border-border-dark dark:bg-surface-dark mt-4 border border-border bg-surface p-3">
			<div class="dark:text-text-dark mb-2 text-sm font-medium text-text">
				Feeder Blocker Combos (Total Time)
			</div>
			{#if top_blocker_combos.length === 0}
				<div class="dark:text-text-muted-dark text-xs text-text-muted">No blocker combo time yet.</div>
			{:else}
				<div class="grid grid-cols-1 gap-1 text-xs md:grid-cols-2">
					{#each top_blocker_combos as [combo_name, duration_s]}
						<div class="dark:text-text-muted-dark flex items-center justify-between text-text-muted">
							<span class="truncate pr-2">{combo_name}</span>
							<span class="tabular-nums">{duration_s.toFixed(2)}s</span>
						</div>
					{/each}
				</div>
			{/if}
		</div>
	{/if}
</div>
