<script lang="ts">
	import { onMount } from 'svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import SectionCard from '$lib/components/settings/SectionCard.svelte';
	import { Button, Alert } from '$lib/components/primitives';

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

	// Live snapshot from the websocket (updates every ~1s).
	const liveProfile = $derived(deriveProfile(ctx.machine?.runtimeStats as Snapshot));
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
			const res = await fetch(`${backendBase()}/runtime-stats/perf-history?window_s=${windowS}`);
			if (!res.ok) throw new Error(await res.text());
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

	// ── Profiler toggle (toml-backed, default on) ───────────────────────────
	let profilerEnabled = $state<boolean | null>(null);
	let profilerSaving = $state(false);
	let profilerError = $state<string | null>(null);

	async function loadProfiler() {
		try {
			const res = await fetch(`${backendBase()}/api/system/profiler-config`);
			if (!res.ok) throw new Error(await res.text());
			const body = await res.json();
			profilerEnabled = Boolean(body.enabled);
		} catch (e: any) {
			profilerError = e?.message ?? 'Failed to load profiler setting';
		}
	}
	async function saveProfiler(next: boolean) {
		profilerSaving = true;
		profilerError = null;
		try {
			const res = await fetch(`${backendBase()}/api/system/profiler-config`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ enabled: next })
			});
			if (!res.ok) throw new Error(await res.text());
			const body = await res.json();
			profilerEnabled = Boolean(body.enabled);
		} catch (e: any) {
			profilerError = e?.message ?? 'Failed to save profiler setting';
		} finally {
			profilerSaving = false;
		}
	}

	onMount(() => {
		void loadRecords();
		void loadProfiler();
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
	// Lower-is-better (latency/age). good < warn < bad.
	function msHealth(v: number | null, good: number, warn: number): string {
		if (v == null) return 'text-text';
		if (v <= good) return 'text-success';
		if (v <= warn) return 'text-warning';
		return 'text-danger';
	}
	// Higher-is-better (rates). good > warn.
	function hzHealth(v: number | null, good: number, warn: number): string {
		if (v == null) return 'text-text';
		if (v >= good) return 'text-success';
		if (v >= warn) return 'text-warning';
		return 'text-danger';
	}
</script>

<div class="flex flex-col gap-6">
	<SectionCard
		title="Performance"
		description="How fast this machine is thinking and how fresh the data behind each decision is. Core rates are always collected; the detailed profiler can be toggled below."
	>
		<!-- Range + machine -->
		<div class="flex flex-wrap items-center justify-between gap-3">
			<div class="text-sm text-text-muted">
				Showing <span class="font-medium text-text">{machineName}</span>
				{#if liveProfile.lifecycle}
					· <span class="text-text">{liveProfile.lifecycle}</span>
				{/if}
				· running {fmtDuration(liveProfile.running_time_s)}
			</div>
			<div class="flex items-center gap-1">
				{#each RANGES as r, i (r.label)}
					<Button
						variant={i === rangeIdx ? 'primary' : 'ghost'}
						size="sm"
						onclick={() => (rangeIdx = i)}
					>
						{r.label}
					</Button>
				{/each}
			</div>
		</div>
		{#if historyError}
			<div class="mt-2 text-sm text-danger">{historyError}</div>
		{/if}

		<!-- ── Decision loop ──────────────────────────────────────────────── -->
		<div class="mt-5 text-xs font-semibold uppercase tracking-wider text-text-muted">
			Decision loop
		</div>
		<div class="mt-2 grid grid-cols-2 gap-2 md:grid-cols-4">
			<div class="border border-border bg-bg p-3">
				<div class="text-sm text-text-muted">Decisions / sec</div>
				<div class="mt-1 text-3xl font-semibold tabular-nums {hzHealth(liveProfile.decision_hz, 60, 30)}">
					{fmtHz(liveProfile.decision_hz)}
				</div>
				<div class="mt-0.5 text-sm text-text-muted">Hz · classification ticks</div>
			</div>
			<div class="border border-border bg-bg p-3">
				<div class="text-sm text-text-muted">Decision data age</div>
				<div class="mt-1 text-3xl font-semibold tabular-nums {msHealth(liveProfile.decision_frame_age_ms, 150, 300)}">
					{fmtMs(liveProfile.decision_frame_age_ms)}
				</div>
				<div class="mt-0.5 text-sm text-text-muted">ms old camera data</div>
			</div>
			<div class="border border-border bg-bg p-3">
				<div class="text-sm text-text-muted">Control loop rate</div>
				<div class="mt-1 text-3xl font-semibold tabular-nums {hzHealth(liveProfile.loop_hz, 80, 50)}">
					{fmtHz(liveProfile.loop_hz)}
				</div>
				<div class="mt-0.5 text-sm text-text-muted">Hz · target 100</div>
			</div>
			<div class="border border-border bg-bg p-3">
				<div class="text-sm text-text-muted">GIL stall</div>
				<div class="mt-1 text-3xl font-semibold tabular-nums {msHealth(liveProfile.gil_stall_ms, 5, 15)}">
					{fmtMs(liveProfile.gil_stall_ms)}
				</div>
				<div class="mt-0.5 text-sm text-text-muted">ms · loop contention</div>
			</div>
		</div>

		<!-- sparklines over the selected window -->
		<div class="mt-2 grid grid-cols-1 gap-2 md:grid-cols-3">
			{@render spark('Decision data age (ms)', decisionAgeSeries, 'over ' + RANGES[rangeIdx].label)}
			{@render spark('Control loop interval (ms)', loopIntervalSeries, 'lower = faster')}
			{@render spark('Decisions / sec', decisionHzSeries, 'over ' + RANGES[rangeIdx].label)}
		</div>

		<!-- ── Perception (per camera) ────────────────────────────────────── -->
		<div class="mt-6 text-xs font-semibold uppercase tracking-wider text-text-muted">
			Perception — inference per camera
		</div>
		{#if liveProfile.cameras.length === 0}
			<div class="mt-2 text-sm text-text-muted">No active inference cameras reporting yet.</div>
		{:else}
			<div class="mt-2 flex flex-col gap-2">
				{#each liveProfile.cameras as cam (cam.source_id)}
					<div class="border border-border bg-bg p-3">
						<div class="flex flex-wrap items-baseline justify-between gap-2">
							<div class="text-base font-medium text-text">{cam.source_id}</div>
							<div class="flex items-baseline gap-4 text-sm tabular-nums">
								<span class="text-text-muted">
									rate
									<span class="text-lg font-semibold {hzHealth(cam.infer_hz, 15, 8)}">
										{fmtHz(cam.infer_hz)}
									</span> Hz
								</span>
								<span class="text-text-muted">
									infer
									<span class="font-semibold {msHealth(cam.infer_ms, 40, 80)}">{fmtMs(cam.infer_ms)}</span> ms
								</span>
								<span class="text-text-muted">
									cycle <span class="font-semibold text-text">{fmtMs(cam.cycle_ms)}</span> ms
								</span>
								<span class="text-text-muted">
									frame age
									<span class="font-semibold {msHealth(cam.frame_age_ms, 80, 160)}">{fmtMs(cam.frame_age_ms)}</span> ms
								</span>
							</div>
						</div>
						{@render bars(rateSeries(`infer.${cam.source_id}`))}
					</div>
				{/each}
			</div>
		{/if}

		<!-- ── Subsystem step cost ────────────────────────────────────────── -->
		<div class="mt-6 text-xs font-semibold uppercase tracking-wider text-text-muted">
			Subsystem step cost (per control tick)
		</div>
		<div class="mt-2 grid grid-cols-2 gap-2 md:grid-cols-4">
			{@render stat('Distribution', fmtMs(liveProfile.distribution_ms), 'ms', msHealth(liveProfile.distribution_ms, 2, 6))}
			{@render stat('Classification', fmtMs(liveProfile.classification_ms), 'ms', msHealth(liveProfile.classification_ms, 2, 6))}
			{@render stat('Feeder', fmtMs(liveProfile.feeder_ms), 'ms', msHealth(liveProfile.feeder_ms, 2, 6))}
			{@render stat('Controller step', fmtMs(liveProfile.controller_step_ms), 'ms', msHealth(liveProfile.controller_step_ms, 4, 10))}
		</div>

		<!-- ── Throughput ─────────────────────────────────────────────────── -->
		<div class="mt-6 text-xs font-semibold uppercase tracking-wider text-text-muted">Throughput</div>
		<div class="mt-2 grid grid-cols-2 gap-2 md:grid-cols-4">
			{@render stat('Pieces / min (5m)', fmtPpm(liveProfile.rolling_5min_ppm), 'ppm', 'text-text')}
			{@render stat('Pieces / min (avg)', fmtPpm(liveProfile.overall_ppm), 'ppm', 'text-text')}
			{@render stat('Pieces seen', liveProfile.pieces_seen?.toString() ?? '–', '', 'text-text')}
			{@render stat('Distributed', liveProfile.distributed?.toString() ?? '–', '', 'text-text')}
		</div>
	</SectionCard>

	<!-- ── Compare to a past run ──────────────────────────────────────────── -->
	<SectionCard
		title="Compare to a past run"
		description="Put this machine's current session next to a finished run — same numbers, side by side. Useful for comparing machines or spotting a regression."
	>
		<div class="flex flex-wrap items-center gap-2">
			<select
				bind:value={selectedRecordId}
				onchange={() => void loadCompare(selectedRecordId)}
				class="border border-border bg-bg px-3 py-2 text-sm text-text"
			>
				<option value="">Select a finished run…</option>
				{#each records as rec (rec.record_id)}
					<option value={rec.record_id}>
						{new Date(rec.started_at * 1000).toLocaleString()} · {rec.total_pieces} pcs
					</option>
				{/each}
			</select>
			{#if records.length === 0}
				<span class="text-sm text-text-muted">No saved runs yet.</span>
			{/if}
		</div>

		{#if compareProfile}
			<div class="mt-3 overflow-x-auto">
				<table class="w-full border-collapse text-sm">
					<thead>
						<tr class="text-left text-text-muted">
							<th class="border border-border px-3 py-2 font-semibold">Metric</th>
							<th class="border border-border px-3 py-2 font-semibold">{machineName} (now)</th>
							<th class="border border-border px-3 py-2 font-semibold">{compareLabel}</th>
						</tr>
					</thead>
					<tbody class="tabular-nums text-text">
						{@render cmp('Decisions / sec', fmtHz(liveProfile.decision_hz), fmtHz(compareProfile.decision_hz))}
						{@render cmp('Decision data age (ms)', fmtMs(liveProfile.decision_frame_age_ms), fmtMs(compareProfile.decision_frame_age_ms))}
						{@render cmp('Control loop rate (Hz)', fmtHz(liveProfile.loop_hz), fmtHz(compareProfile.loop_hz))}
						{@render cmp('GIL stall (ms)', fmtMs(liveProfile.gil_stall_ms), fmtMs(compareProfile.gil_stall_ms))}
						{@render cmp('Controller step (ms)', fmtMs(liveProfile.controller_step_ms), fmtMs(compareProfile.controller_step_ms))}
						{@render cmp('Distribution step (ms)', fmtMs(liveProfile.distribution_ms), fmtMs(compareProfile.distribution_ms))}
						{@render cmp('Classification step (ms)', fmtMs(liveProfile.classification_ms), fmtMs(compareProfile.classification_ms))}
						{@render cmp('Feeder step (ms)', fmtMs(liveProfile.feeder_ms), fmtMs(compareProfile.feeder_ms))}
						{@render cmp('Pieces / min (avg)', fmtPpm(liveProfile.overall_ppm), fmtPpm(compareProfile.overall_ppm))}
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
	</SectionCard>

	<!-- ── Profiler toggle ────────────────────────────────────────────────── -->
	<SectionCard
		title="Detailed profiler"
		description="The detailed code profiler adds per-block timers and a periodic report. Headline rates above are always collected regardless of this setting; this only controls the extra fine-grained instrumentation. Persisted to this machine's config and applied live."
	>
		<Alert variant="warning">
			Leave this <strong>off</strong> for normal sorting. The profiler adds per-call timing
			overhead across hot loops — it can noticeably slow things like the live camera feed — and
			writes telemetry to disk. It's a diagnostic for comparing one machine against another, not
			something to run continuously.
		</Alert>
		<label class="mt-3 flex items-start gap-3 border border-border bg-bg px-3 py-2.5 text-sm text-text">
			<input
				type="checkbox"
				checked={profilerEnabled ?? false}
				disabled={profilerEnabled == null || profilerSaving}
				onchange={(e) => void saveProfiler(e.currentTarget.checked)}
				class="mt-0.5 h-4 w-4 accent-sky-500"
			/>
			<span class="min-w-0">
				<span class="block text-sm font-medium text-text">Enable detailed profiler</span>
				<span class="mt-0.5 block text-sm text-text-muted">
					Off by default. The Performance numbers above keep working either way — only turn this
					on temporarily when you need fine-grained per-block timings.
				</span>
			</span>
		</label>
		{#if profilerError}
			<div class="mt-2 text-sm text-danger">{profilerError}</div>
		{/if}
	</SectionCard>
</div>

<!-- ── Snippets ───────────────────────────────────────────────────────────── -->
{#snippet stat(label: string, value: string, unit: string, color: string)}
	<div class="border border-border bg-bg p-3">
		<div class="text-sm text-text-muted">{label}</div>
		<div class="mt-1 flex items-baseline gap-1">
			<span class="text-2xl font-semibold tabular-nums {color}">{value}</span>
			{#if unit}<span class="text-sm text-text-muted">{unit}</span>{/if}
		</div>
	</div>
{/snippet}

{#snippet cmp(label: string, a: string, b: string)}
	<tr>
		<td class="border border-border px-3 py-1.5 text-text-muted">{label}</td>
		<td class="border border-border px-3 py-1.5">{a}</td>
		<td class="border border-border px-3 py-1.5">{b}</td>
	</tr>
{/snippet}

{#snippet bars(series: number[])}
	{@const peak = Math.max(1e-6, ...series)}
	<div class="mt-2 flex h-8 items-end gap-px">
		{#each series as v, i (i)}
			<div
				class="flex-1 bg-primary/70"
				style="height: {Math.max(2, (v / peak) * 100)}%;"
			></div>
		{/each}
	</div>
{/snippet}

{#snippet spark(title: string, series: number[], sub: string)}
	{@const peak = Math.max(1e-6, ...series)}
	{@const last = series.length ? series[series.length - 1] : 0}
	<div class="border border-border bg-bg p-3">
		<div class="flex items-baseline justify-between">
			<div class="text-sm text-text-muted">{title}</div>
			<div class="text-sm tabular-nums text-text">{last < 10 ? last.toFixed(1) : Math.round(last)}</div>
		</div>
		<div class="mt-2 flex h-10 items-end gap-px">
			{#each series as v, i (i)}
				<div class="flex-1 bg-primary/60" style="height: {Math.max(2, (v / peak) * 100)}%;"></div>
			{/each}
		</div>
		<div class="mt-1 text-sm text-text-muted">{sub}</div>
	</div>
{/snippet}
