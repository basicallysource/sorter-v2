<script lang="ts">
	import { onMount } from 'svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import SegmentedControl from '$lib/components/ui/SegmentedControl.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Stat from '$lib/components/ui/Stat.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';

	const ctx = getMachineContext();

	function backendBase(): string {
		return machineHttpBaseUrlFromWsUrl(ctx.machine?.url) ?? getBackendHttpBase();
	}

	// ── Types ───────────────────────────────────────────────────────────────
	type Snapshot = Record<string, any>;
	type CameraProfile = {
		source_id: string;
		infer_hz: number | null;
		infer_ms: number | null;
		cycle_ms: number | null;
		frame_age_ms: number | null;
	};
	type Profile = {
		running_time_s: number | null;
		lifecycle: string | null;
		is_running: boolean;
		decision_hz: number | null;
		loop_hz: number | null;
		distribution_hz: number | null;
		feeder_hz: number | null;
		decision_frame_age_ms: number | null;
		loop_interval_ms: number | null;
		controller_step_ms: number | null;
		gil_stall_ms: number | null;
		distribution_ms: number | null;
		classification_ms: number | null;
		feeder_ms: number | null;
		cameras: CameraProfile[];
		rolling_5min_ppm: number | null;
		overall_ppm: number | null;
		pieces_seen: number | null;
		distributed: number | null;
	};

	// ── Snapshot → plain-language profile ───────────────────────────────────
	// One snapshot carries cumulative counters (perf_total_counts) and latency
	// histograms (perf_ms). Whole-run rates come from counter / running_time_s,
	// which is the fairest apples-to-apples number for comparing two machines.
	function num(v: unknown): number | null {
		return typeof v === 'number' && Number.isFinite(v) ? v : null;
	}
	function deriveProfile(snap: Snapshot | null | undefined): Profile {
		const perf_ms: Record<string, any> = (snap?.perf_ms ?? {}) as Record<string, any>;
		const counts: Record<string, number> = (snap?.perf_total_counts ?? {}) as Record<string, number>;
		const throughput: Record<string, any> = (snap?.throughput ?? {}) as Record<string, any>;
		const snapCounts: Record<string, any> = (snap?.counts ?? {}) as Record<string, any>;
		const running = num(throughput.running_time_s);

		const med = (key: string): number | null => {
			const e = perf_ms[key];
			if (!e || typeof e !== 'object') return null;
			return num(e.med_ms) ?? num(e.avg_ms);
		};
		const hz = (countKey: string): number | null => {
			const c = num(counts[countKey]);
			if (c == null || running == null || running <= 0) return null;
			return c / running;
		};

		const cameras: CameraProfile[] = [];
		for (const key of Object.keys(perf_ms)) {
			const m = key.match(/^perception\.(.+)\.infer_ms$/);
			if (!m) continue;
			const id = m[1];
			cameras.push({
				source_id: id,
				infer_hz: hz(`perception.${id}.infer_ms`),
				infer_ms: med(`perception.${id}.infer_ms`),
				cycle_ms: med(`perception.${id}.cycle_ms`),
				frame_age_ms: med(`perception.${id}.frame_age_ms`)
			});
		}
		cameras.sort((a, b) => a.source_id.localeCompare(b.source_id));

		return {
			running_time_s: running,
			lifecycle: (snap?.lifecycle_state ?? null) as string | null,
			is_running: Boolean(snap?.is_running),
			decision_hz: hz('coordinator.step.classification_ms'),
			loop_hz: hz('main.loop.interval_ms'),
			distribution_hz: hz('coordinator.step.distribution_ms'),
			feeder_hz: hz('coordinator.step.feeder_ms'),
			decision_frame_age_ms: med('classification.decision_frame_age_ms'),
			loop_interval_ms: med('main.loop.interval_ms'),
			controller_step_ms: med('main.loop.controller_step_ms'),
			gil_stall_ms: med('coordinator.step.gil_stall_ms'),
			distribution_ms: med('coordinator.step.distribution_ms'),
			classification_ms: med('coordinator.step.classification_ms'),
			feeder_ms: med('coordinator.step.feeder_ms'),
			cameras,
			rolling_5min_ppm: num(throughput.rolling_5min_ppm),
			overall_ppm: num(throughput.overall_ppm),
			pieces_seen: num(snapCounts.pieces_seen),
			distributed: num(snapCounts.distributed)
		};
	}

	// The full snapshot is not pushed; loadHistory fetches it with the history.
	let liveSnapshot = $state<Snapshot | null>(null);
	const liveProfile = $derived(deriveProfile(liveSnapshot));
	const machineName = $derived(
		ctx.machine?.identity?.nickname || ctx.machine?.identity?.machine_id || 'this machine'
	);

	// ── Time-range history (sparklines + recent-window rates) ───────────────
	const RANGES: { label: string; window_s: number }[] = [
		{ label: 'Live', window_s: 15 },
		{ label: '1 min', window_s: 60 },
		{ label: '5 min', window_s: 300 },
		{ label: '15 min', window_s: 900 },
		{ label: '60 min', window_s: 3600 }
	];
	let rangeIdx = $state(2);
	const windowS = $derived(RANGES[rangeIdx].window_s);

	let rows = $state<any[]>([]);
	let windowRates = $state<any>({ hz: {}, cameras_hz: {}, current: {} });
	let historyError = $state<string | null>(null);

	async function loadHistory() {
		try {
			const [res, live] = await Promise.all([
				fetch(`${backendBase()}/runtime-stats/perf-history?window_s=${windowS}`),
				fetch(`${backendBase()}/runtime-stats`)
			]);
			if (!res.ok) throw new Error(await res.text());
			if (live.ok) liveSnapshot = (await live.json()).payload ?? null;
			const body = await res.json();
			rows = Array.isArray(body.rows) ? body.rows : [];
			windowRates = body.rates ?? { hz: {}, cameras_hz: {}, current: {} };
			historyError = null;
		} catch (e: any) {
			historyError = e?.message ?? 'Failed to load history';
		}
	}

	$effect(() => {
		void windowS; // re-run on range change
		void loadHistory();
		const id = setInterval(() => void loadHistory(), 2500);
		return () => clearInterval(id);
	});

	// Per-row Hz series for a cumulative counter — difference adjacent rows.
	function rateSeries(key: string): number[] {
		const out: number[] = [];
		for (let i = 1; i < rows.length; i += 1) {
			const a = rows[i - 1];
			const b = rows[i];
			const ca = a?.counts?.[key];
			const cb = b?.counts?.[key];
			const dt = (b?.t ?? 0) - (a?.t ?? 0);
			if (typeof ca === 'number' && typeof cb === 'number' && dt > 0 && cb >= ca) {
				out.push((cb - ca) / dt);
			} else {
				out.push(0);
			}
		}
		return out;
	}
	function valueSeries(field: string): number[] {
		return rows.map((r) => (typeof r?.[field] === 'number' ? r[field] : 0));
	}

	const decisionAgeSeries = $derived(valueSeries('decision_frame_age_ms'));
	const loopIntervalSeries = $derived(valueSeries('loop_interval_ms'));
	const decisionHzSeries = $derived(rateSeries('decision'));
	const cameraIds = $derived(liveProfile.cameras.map((c) => c.source_id));

	// ── Past-run comparison ─────────────────────────────────────────────────
	type RecordItem = { record_id: string; run_id: string; started_at: number; ended_at: number; total_pieces: number };
	let records = $state<RecordItem[]>([]);
	let selectedRecordId = $state<string>('');
	let compareProfile = $state<Profile | null>(null);
	let compareLabel = $state<string>('');

	async function loadRecords() {
		try {
			const res = await fetch(`${backendBase()}/runtime-stats/records`);
			if (!res.ok) return;
			const body = await res.json();
			records = Array.isArray(body.records) ? body.records : [];
		} catch {
			// non-fatal
		}
	}
	async function loadCompare(recordId: string) {
		if (!recordId) {
			compareProfile = null;
			compareLabel = '';
			return;
		}
		try {
			const res = await fetch(`${backendBase()}/runtime-stats/record/${recordId}`);
			if (!res.ok) throw new Error(await res.text());
			const body = await res.json();
			compareProfile = deriveProfile(body.payload as Snapshot);
			const rec = records.find((r) => r.record_id === recordId);
			compareLabel = rec ? new Date(rec.started_at * 1000).toLocaleString() : recordId;
		} catch {
			compareProfile = null;
		}
	}

	onMount(() => {
		void loadRecords();
	});

	function unionCameras(a: Profile, b: Profile): string[] {
		const ids = new Set<string>();
		for (const c of a.cameras) ids.add(c.source_id);
		for (const c of b.cameras) ids.add(c.source_id);
		return [...ids].sort();
	}

	// ── Formatting + health ─────────────────────────────────────────────────
	function fmtHz(v: number | null): string {
		return v == null ? '–' : v.toFixed(1);
	}
	function fmtMs(v: number | null): string {
		return v == null ? '–' : v < 10 ? v.toFixed(1) : Math.round(v).toString();
	}
	function fmtPpm(v: number | null): string {
		return v == null ? '–' : v.toFixed(1);
	}
	function fmtDuration(s: number | null): string {
		if (s == null) return '–';
		if (s < 60) return `${Math.round(s)}s`;
		if (s < 3600) return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
		return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
	}
	type Tone = 'success' | 'warning' | 'danger' | undefined;
	const TONE_INK = { success: 'text-success-ink', warning: 'text-warning-ink', danger: 'text-danger-ink' };
	// Lower is better (latency, age): good < warn < bad.
	function msTone(v: number | null, good: number, warn: number): Tone {
		if (v == null) return undefined;
		return v <= good ? 'success' : v <= warn ? 'warning' : 'danger';
	}
	// Higher is better (rates): good > warn.
	function hzTone(v: number | null, good: number, warn: number): Tone {
		if (v == null) return undefined;
		return v >= good ? 'success' : v >= warn ? 'warning' : 'danger';
	}
	const rangeOptions = RANGES.map((r, i) => ({ value: String(i), label: r.label }));
	const recordOptions = $derived([
		{ value: '', label: 'None' },
		...records.map((rec) => ({
			value: rec.record_id,
			label: new Date(rec.started_at * 1000).toLocaleString(),
			hint: `${rec.total_pieces} pcs`
		}))
	]);
</script>

<svelte:head><title>Sorter - Performance</title></svelte:head>

<div class="flex flex-col gap-(--gap-panels)">
	<PageHeader
		title="Performance"
		description="How fast this machine is thinking and how fresh the data behind each decision is."
	/>
	<div class="flex flex-wrap items-center justify-between gap-3">
		<p class="text-sm text-ink-muted">
			Showing <span class="font-medium text-ink">{machineName}</span>
			{#if liveProfile.lifecycle}· <span class="text-ink">{liveProfile.lifecycle}</span>{/if}
			· running {fmtDuration(liveProfile.running_time_s)}
		</p>
		<SegmentedControl
			label="Time range"
			size="sm"
			value={String(rangeIdx)}
			options={rangeOptions}
			onchange={(v) => (rangeIdx = Number(v))}
		/>
	</div>
	{#if historyError}<Alert tone="danger">{historyError}</Alert>{/if}

	<Panel title="Decision loop" flush>
		{@render stats([
			{ label: 'Decisions a second', value: fmtHz(liveProfile.decision_hz), unit: 'Hz', hint: 'Classification ticks', tone: hzTone(liveProfile.decision_hz, 60, 30) },
			{ label: 'Decision data age', value: fmtMs(liveProfile.decision_frame_age_ms), unit: 'ms', hint: 'Age of the camera data', tone: msTone(liveProfile.decision_frame_age_ms, 150, 300) },
			{ label: 'Control loop rate', value: fmtHz(liveProfile.loop_hz), unit: 'Hz', hint: 'Target 100', tone: hzTone(liveProfile.loop_hz, 80, 50) },
			{ label: 'GIL stall', value: fmtMs(liveProfile.gil_stall_ms), unit: 'ms', hint: 'Loop contention', tone: msTone(liveProfile.gil_stall_ms, 5, 15) }
		])}
		<div class="grid grid-cols-1 gap-3 border-t border-line p-(--pad-panel) md:grid-cols-3">
			{@render spark('Decision data age (ms)', decisionAgeSeries, 'Over ' + RANGES[rangeIdx].label)}
			{@render spark('Control loop interval (ms)', loopIntervalSeries, 'Lower is faster')}
			{@render spark('Decisions a second', decisionHzSeries, 'Over ' + RANGES[rangeIdx].label)}
		</div>
	</Panel>

	<Panel title="Perception" description="Inference on each camera." flush>
		{#if liveProfile.cameras.length === 0}
			<p class="px-(--pad-panel) pb-4 text-sm text-ink-muted">No inference cameras are reporting yet.</p>
		{:else}
			<div class="divide-y divide-line">
				{#each liveProfile.cameras as cam (cam.source_id)}
					<div class="px-(--pad-panel) py-(--pad-row)">
						<div class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 text-sm">
							<span class="font-medium text-ink">{cam.source_id}</span>
							<span class="flex flex-wrap gap-x-4">
								{@render reading('Rate', fmtHz(cam.infer_hz), 'Hz', hzTone(cam.infer_hz, 15, 8))}
								{@render reading('Infer', fmtMs(cam.infer_ms), 'ms', msTone(cam.infer_ms, 40, 80))}
								{@render reading('Cycle', fmtMs(cam.cycle_ms), 'ms')}
								{@render reading('Frame age', fmtMs(cam.frame_age_ms), 'ms', msTone(cam.frame_age_ms, 80, 160))}
							</span>
						</div>
						{@render line(rateSeries(`infer.${cam.source_id}`), 'mt-2 h-8')}
					</div>
				{/each}
			</div>
		{/if}
	</Panel>

	<Panel title="Subsystem step cost" description="Each control tick." flush>
		{@render stats([
			{ label: 'Distribution', value: fmtMs(liveProfile.distribution_ms), unit: 'ms', tone: msTone(liveProfile.distribution_ms, 2, 6) },
			{ label: 'Classification', value: fmtMs(liveProfile.classification_ms), unit: 'ms', tone: msTone(liveProfile.classification_ms, 2, 6) },
			{ label: 'Feeder', value: fmtMs(liveProfile.feeder_ms), unit: 'ms', tone: msTone(liveProfile.feeder_ms, 2, 6) },
			{ label: 'Controller step', value: fmtMs(liveProfile.controller_step_ms), unit: 'ms', tone: msTone(liveProfile.controller_step_ms, 4, 10) }
		])}
	</Panel>

	<Panel title="Throughput" flush>
		{@render stats([
			{ label: 'Pieces a minute (5 min)', value: fmtPpm(liveProfile.rolling_5min_ppm), unit: 'ppm' },
			{ label: 'Pieces a minute (average)', value: fmtPpm(liveProfile.overall_ppm), unit: 'ppm' },
			{ label: 'Pieces seen', value: liveProfile.pieces_seen?.toString() ?? '–' },
			{ label: 'Distributed', value: liveProfile.distributed?.toString() ?? '–' }
		])}
	</Panel>

	<Panel
		title="Compare to a past run"
		description="This machine's current session beside a finished run, the same numbers side by side. Useful for comparing machines or spotting a regression."
		flush
	>
		<div class="flex flex-wrap items-center gap-3 px-(--pad-panel) pb-4">
			<Select
				label="Past run"
				class="w-72 max-w-full"
				bind:value={selectedRecordId}
				options={recordOptions}
				onchange={(id) => void loadCompare(id)}
			/>
			{#if records.length === 0}<span class="text-sm text-ink-muted">No saved runs yet.</span>{/if}
		</div>
		{#if compareProfile}
			<div class="overflow-x-auto">
				<table class="data-table">
					<thead>
						<tr><th>Metric</th><th class="num">{machineName} (now)</th><th class="num">{compareLabel}</th></tr>
					</thead>
					<tbody>
						{@render cmp('Decisions a second', fmtHz(liveProfile.decision_hz), fmtHz(compareProfile.decision_hz))}
						{@render cmp('Decision data age (ms)', fmtMs(liveProfile.decision_frame_age_ms), fmtMs(compareProfile.decision_frame_age_ms))}
						{@render cmp('Control loop rate (Hz)', fmtHz(liveProfile.loop_hz), fmtHz(compareProfile.loop_hz))}
						{@render cmp('GIL stall (ms)', fmtMs(liveProfile.gil_stall_ms), fmtMs(compareProfile.gil_stall_ms))}
						{@render cmp('Controller step (ms)', fmtMs(liveProfile.controller_step_ms), fmtMs(compareProfile.controller_step_ms))}
						{@render cmp('Distribution step (ms)', fmtMs(liveProfile.distribution_ms), fmtMs(compareProfile.distribution_ms))}
						{@render cmp('Classification step (ms)', fmtMs(liveProfile.classification_ms), fmtMs(compareProfile.classification_ms))}
						{@render cmp('Feeder step (ms)', fmtMs(liveProfile.feeder_ms), fmtMs(compareProfile.feeder_ms))}
						{@render cmp('Pieces a minute (average)', fmtPpm(liveProfile.overall_ppm), fmtPpm(compareProfile.overall_ppm))}
						{#each unionCameras(liveProfile, compareProfile) as id (id)}
							{@render cmp(
								`Inference ${id} (Hz)`,
								fmtHz(liveProfile.cameras.find((c) => c.source_id === id)?.infer_hz ?? null),
								fmtHz(compareProfile.cameras.find((c) => c.source_id === id)?.infer_hz ?? null)
							)}
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</Panel>
</div>

{#snippet stats(items: { label: string; value: string; unit?: string; hint?: string; tone?: Tone }[])}
	<div class="grid grid-cols-2 gap-px bg-line md:grid-cols-4">
		{#each items as item (item.label)}
			<div class="bg-surface"><Stat {...item} /></div>
		{/each}
	</div>
{/snippet}

{#snippet reading(label: string, value: string, unit: string, tone?: Tone)}
	<span class="text-ink-muted">
		{label} <span class="num font-medium {tone ? TONE_INK[tone] : 'text-ink'}">{value}</span>
		{unit}
	</span>
{/snippet}

{#snippet cmp(label: string, a: string, b: string)}
	<tr><td class="text-ink-muted">{label}</td><td class="num">{a}</td><td class="num">{b}</td></tr>
{/snippet}

<!-- A series as a 1.5px line in the primary, scaled to its own peak. -->
{#snippet line(series: number[], cls: string)}
	{@const peak = Math.max(1e-6, ...series)}
	<svg
		viewBox="0 -0.1 {Math.max(1, series.length - 1)} 1.2"
		preserveAspectRatio="none"
		class="block w-full {cls}"
		aria-hidden="true"
	>
		<polyline
			points={series.map((v, i) => `${i},${1 - v / peak}`).join(' ')}
			fill="none"
			stroke="var(--primary)"
			stroke-width="1.5"
			vector-effect="non-scaling-stroke"
		/>
	</svg>
{/snippet}

{#snippet spark(title: string, series: number[], sub: string)}
	{@const last = series.at(-1) ?? 0}
	<div class="rounded-control bg-well p-3">
		<div class="flex items-baseline justify-between gap-2 text-sm">
			<span class="text-ink-muted">{title}</span>
			<span class="num text-ink">{last < 10 ? last.toFixed(1) : Math.round(last)}</span>
		</div>
		{@render line(series, 'mt-2 h-10')}
		<div class="mt-1 text-xs text-ink-muted">{sub}</div>
	</div>
{/snippet}
