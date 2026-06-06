<script lang="ts">
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import { ChevronDown, Play, Pause, Square } from 'lucide-svelte';
	import { onDestroy, onMount, untrack } from 'svelte';
	import ChuteStressTelemetryChart from './ChuteStressTelemetryChart.svelte';

	type StressMode = 'sweep' | 'random';
	type RunStatus =
		| 'running'
		| 'paused'
		| 'stopping'
		| 'completed'
		| 'stopped'
		| 'failed'
		| 'stalled';

	type RunRecord = {
		id: string;
		started_at: number;
		ended_at: number | null;
		mode: StressMode;
		target_max_deg: number;
		duration_target_s: number;
		speed_microsteps_per_sec: number;
		status: RunStatus;
		total_distance_deg: number;
		total_time_s: number;
		error: string | null;
		last_target_deg?: number | null;
		stalled_at_deg?: number | null;
	};

	const CHUTE_STRESS_MAX_ANGLE = 345;

	let {
		operatingSpeed
	}: {
		operatingSpeed: number;
	} = $props();

	const manager = getMachinesContext();

	let open = $state(false);
	let mode = $state<StressMode>('sweep');
	let targetMaxDeg = $state(340);
	let durationSec = $state(60);
	let useMaxSpeed = $state(true);
	let speedOverride = $state(operatingSpeed);
	let invertDirection = $state(false);

	let errorMsg = $state<string | null>(null);
	let statusMsg = $state('');
	let activeRun = $state<RunRecord | null>(null);
	let active = $state(false);
	let busy = $state(false);

	let runs = $state<RunRecord[]>([]);
	let selectedRunId = $state<string | null>(null);
	let pollHandle: ReturnType<typeof setInterval> | null = null;

	const effectiveSpeed = $derived(
		useMaxSpeed ? Math.max(1, Math.floor(operatingSpeed)) : Math.max(1, Math.floor(speedOverride))
	);

	$effect(() => {
		if (useMaxSpeed) speedOverride = operatingSpeed;
	});

	function backendBase(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? getBackendHttpBase()
		);
	}

	async function readError(res: Response): Promise<string> {
		try {
			const data = await res.json();
			if (typeof data?.detail === 'string') return data.detail;
		} catch {
			/* fall through */
		}
		try {
			return await res.text();
		} catch {
			return `Request failed with status ${res.status}`;
		}
	}

	async function loadStatus() {
		try {
			const res = await fetch(`${backendBase()}/api/chute/stress-test/status`);
			if (!res.ok) return;
			const data = await res.json();
			active = Boolean(data?.active);
			activeRun = data?.run ?? null;
		} catch {
			// silent
		}
	}

	async function loadRuns() {
		try {
			const res = await fetch(`${backendBase()}/api/chute/stress-test/runs?limit=50`);
			if (!res.ok) return;
			const data = await res.json();
			if (Array.isArray(data?.runs)) runs = data.runs;
		} catch {
			// silent
		}
	}

	async function postAction(path: string, body?: unknown): Promise<boolean> {
		busy = true;
		errorMsg = null;
		statusMsg = '';
		try {
			const res = await fetch(`${backendBase()}${path}`, {
				method: 'POST',
				headers: body ? { 'Content-Type': 'application/json' } : undefined,
				body: body ? JSON.stringify(body) : undefined
			});
			if (!res.ok) {
				errorMsg = await readError(res);
				return false;
			}
			const data = await res.json();
			active = Boolean(data?.active);
			activeRun = data?.run ?? null;
			return true;
		} catch (e: any) {
			errorMsg = e?.message ?? 'Request failed';
			return false;
		} finally {
			busy = false;
		}
	}

	async function startRun() {
		if (targetMaxDeg <= 0 || targetMaxDeg > CHUTE_STRESS_MAX_ANGLE) {
			errorMsg = `Target angle must be in (0, ${CHUTE_STRESS_MAX_ANGLE}]`;
			return;
		}
		if (durationSec <= 0) {
			errorMsg = 'Duration must be > 0 seconds';
			return;
		}
		const ok = await postAction('/api/chute/stress-test/start', {
			mode,
			target_max_deg: targetMaxDeg,
			duration_s: durationSec,
			speed_microsteps_per_sec: effectiveSpeed,
			invert_direction: invertDirection
		});
		if (ok) {
			statusMsg = 'Stress test started.';
			await loadRuns();
		}
	}

	async function pauseRun() {
		const ok = await postAction('/api/chute/stress-test/pause');
		if (ok) statusMsg = 'Pause requested (finishing current leg).';
	}

	async function resumeRun() {
		const ok = await postAction('/api/chute/stress-test/resume');
		if (ok) statusMsg = 'Resumed.';
	}

	async function stopRun() {
		const ok = await postAction('/api/chute/stress-test/stop');
		if (ok) {
			statusMsg = 'Stop requested.';
			await loadRuns();
		}
	}

	function formatDuration(seconds: number): string {
		if (!Number.isFinite(seconds) || seconds < 0) return '--';
		const total = Math.floor(seconds);
		const h = Math.floor(total / 3600);
		const m = Math.floor((total % 3600) / 60);
		const s = total % 60;
		if (h > 0) return `${h}h ${m}m ${s}s`;
		if (m > 0) return `${m}m ${s}s`;
		return `${s}s`;
	}

	function formatTimestamp(epoch_s: number | null | undefined): string {
		if (!epoch_s || !Number.isFinite(epoch_s)) return '--';
		try {
			return new Date(epoch_s * 1000).toLocaleString();
		} catch {
			return '--';
		}
	}

	function statusLabel(status: RunStatus): string {
		switch (status) {
			case 'running':
				return 'Running';
			case 'paused':
				return 'Paused';
			case 'stopping':
				return 'Stopping';
			case 'completed':
				return 'Completed';
			case 'stopped':
				return 'Stopped';
			case 'failed':
				return 'Failed';
			case 'stalled':
				return 'Stalled';
			default:
				return status;
		}
	}

	function statusColor(status: RunStatus): string {
		if (status === 'running') return 'text-primary';
		if (status === 'paused' || status === 'stopping') return 'text-warning';
		if (status === 'completed') return 'text-success dark:text-green-400';
		if (status === 'failed' || status === 'stalled') return 'text-danger dark:text-red-400';
		return 'text-text-muted';
	}

	function toggleOpen() {
		open = !open;
		if (open) {
			void loadStatus();
			void loadRuns();
		}
	}

	function startPolling() {
		if (pollHandle !== null) return;
		pollHandle = setInterval(() => {
			void loadStatus();
		}, 500);
	}

	function stopPolling() {
		if (pollHandle !== null) {
			clearInterval(pollHandle);
			pollHandle = null;
		}
	}

	$effect(() => {
		if (open && active) {
			startPolling();
		} else if (!active) {
			stopPolling();
		}
	});

	$effect(() => {
		// When the active run transitions away from running/paused, refresh the runs list.
		// untrack the body so this only depends on the status string — not on the
		// machines context that loadRuns()/backendBase() read, which would otherwise
		// re-fire this effect on every connection heartbeat.
		const status = activeRun?.status;
		const endedId = activeRun?.id;
		const stallMsg = activeRun?.error;
		untrack(() => {
			if (status === 'stalled') {
				errorMsg = stallMsg ?? 'Chute stalled — run halted.';
			}
			if (
				status === 'completed' ||
				status === 'stopped' ||
				status === 'failed' ||
				status === 'stalled'
			) {
				void loadRuns();
				// One final silent refresh so the last flushed samples land after the
				// live poller stops (it stops the moment the run goes inactive).
				if (endedId && selectedRunId === endedId) void loadTelemetry(endedId, true);
			}
		});
	});

	onMount(() => {
		void loadStatus();
	});

	onDestroy(() => {
		stopPolling();
		stopTelemetryPolling();
	});

	const selectedRun = $derived(
		selectedRunId ? runs.find((r) => r.id === selectedRunId) ?? null : null
	);

	type TelemetryPoint = {
		x: number;
		sg: number | null;
		cs: number | null;
		pwm: number | null;
		tstep: number | null;
		warn: boolean;
	};

	type DriverSettings = {
		registers?: Record<string, number | null>;
		decoded?: Record<string, Record<string, unknown>>;
		configured?: Record<string, unknown>;
	};

	let telemetryPoints = $state<TelemetryPoint[]>([]);
	let telemetrySettings = $state<DriverSettings | null>(null);
	let telemetryRunId = $state<string | null>(null);
	let telemetryLoading = $state(false);
	let telemetryError = $state<string | null>(null);
	let showSg = $state(true);
	let showCs = $state(true);
	let showPwm = $state(true);
	let showTstep = $state(false);

	function numOrNull(v: unknown): number | null {
		return typeof v === 'number' && Number.isFinite(v) ? v : null;
	}

	function sampleWarn(drv: number | null): boolean {
		if (drv == null) return false;
		// otpw (bit0) or any over-temperature threshold flag (t120..t157, bits 8..11)
		return (drv & ((1 << 0) | (1 << 8) | (1 << 9) | (1 << 10) | (1 << 11))) !== 0;
	}

	function seriesStat(key: 'sg' | 'cs' | 'pwm' | 'tstep'): {
		min: number;
		max: number;
		last: number;
	} | null {
		const vals = telemetryPoints
			.map((p) => p[key])
			.filter((v): v is number => v != null && v >= 0);
		if (vals.length === 0) return null;
		return { min: Math.min(...vals), max: Math.max(...vals), last: vals[vals.length - 1] };
	}

	const sgStat = $derived(seriesStat('sg'));
	const csStat = $derived(seriesStat('cs'));
	const pwmStat = $derived(seriesStat('pwm'));
	const tstepStat = $derived(seriesStat('tstep'));
	const warnCount = $derived(telemetryPoints.filter((p) => p.warn).length);

	function hex32(v: number | null | undefined): string {
		if (v == null) return '--';
		return `0x${(v >>> 0).toString(16).toUpperCase().padStart(8, '0')}`;
	}

	function decodedField(group: string, field: string): unknown {
		return telemetrySettings?.decoded?.[group]?.[field];
	}

	function configuredCurrent(): Record<string, unknown> | null {
		const c = telemetrySettings?.configured?.['last_set_current'];
		return c && typeof c === 'object' ? (c as Record<string, unknown>) : null;
	}

	function snapshotTempBand(): string {
		const drv = telemetrySettings?.decoded?.['drv_status'];
		if (!drv) return '--';
		if (drv['t157']) return '≥157°C';
		if (drv['t150']) return '≥150°C';
		if (drv['t143']) return '≥143°C';
		if (drv['t120']) return '≥120°C';
		return '<120°C';
	}

	async function loadTelemetry(runId: string, silent = false) {
		// silent=true is used by the live poller during an active run: it updates the
		// data in place and never touches loading/error state or clears the panel, so
		// the UI can't swap blocks (which is what caused the height jitter).
		if (!silent) {
			telemetryLoading = true;
			telemetryError = null;
		}
		try {
			const res = await fetch(`${backendBase()}/api/chute/stress-test/runs/${runId}/telemetry`);
			if (res.status === 404) {
				if (!silent) {
					telemetryPoints = [];
					telemetrySettings = null;
					telemetryRunId = null;
					telemetryError = 'No driver telemetry recorded for this run yet.';
				}
				return;
			}
			if (!res.ok) {
				if (!silent) telemetryError = await readError(res);
				return;
			}
			const data = await res.json();
			const run = data?.run ?? null;
			telemetrySettings = (run?.params ?? null) as DriverSettings | null;
			telemetryRunId = run?.id ?? null;
			const rows: any[] = Array.isArray(data?.samples) ? data.samples : [];
			const t0 = rows.length ? Number(rows[0].recorded_at) : 0;
			telemetryPoints = rows.map((r) => ({
				x: Number(r.recorded_at) - t0,
				sg: numOrNull(r.sg_result),
				cs: numOrNull(r.cs_actual),
				pwm: r.pwm_scale != null ? (Number(r.pwm_scale) & 0xff) : null,
				tstep: numOrNull(r.tstep),
				warn: sampleWarn(r.drv_status_raw != null ? Number(r.drv_status_raw) : null)
			}));
		} catch (e: any) {
			if (!silent) telemetryError = e?.message ?? 'Failed to load telemetry';
		} finally {
			if (!silent) telemetryLoading = false;
		}
	}

	let lastTelemetryId: string | null = null;
	$effect(() => {
		// Depend ONLY on selectedRunId. untrack the body so loadTelemetry()'s call to
		// backendBase() (which reads the machines context) doesn't make this effect
		// re-fire on every context update and re-request telemetry in a loop.
		const id = selectedRunId;
		untrack(() => {
			if (id) {
				if (id !== lastTelemetryId) {
					lastTelemetryId = id;
					void loadTelemetry(id);
				}
			} else {
				lastTelemetryId = null;
				telemetryPoints = [];
				telemetrySettings = null;
				telemetryRunId = null;
				telemetryError = null;
			}
		});
	});

	// True when the run currently being viewed is the one actively running.
	const telemetryLive = $derived(active && activeRun != null && selectedRunId === activeRun.id);

	// While a run is active, point the telemetry view at it (unless the user has
	// explicitly selected a different past run to inspect).
	$effect(() => {
		const activeId = active ? activeRun?.id : null;
		untrack(() => {
			if (activeId && !selectedRunId) selectedRunId = activeId;
		});
	});

	let telemetryPollHandle: ReturnType<typeof setInterval> | null = null;
	function startTelemetryPolling() {
		if (telemetryPollHandle !== null) return;
		// Matches the backend recorder's ~2s DB flush. Silent refresh = update in
		// place, no block swaps, no jitter.
		telemetryPollHandle = setInterval(() => {
			const id = selectedRunId;
			if (id) void loadTelemetry(id, true);
		}, 1500);
	}
	function stopTelemetryPolling() {
		if (telemetryPollHandle !== null) {
			clearInterval(telemetryPollHandle);
			telemetryPollHandle = null;
		}
	}

	$effect(() => {
		if (open && telemetryLive) startTelemetryPolling();
		else stopTelemetryPolling();
	});
</script>

<div class="border-t border-border pt-4"></div>

<div class="flex flex-col gap-2">
	<button
		onclick={toggleOpen}
		class="flex w-full items-center justify-between text-left"
	>
		<div class="flex flex-col gap-0.5">
			<div class="text-sm font-medium text-text">Stress Test</div>
			<div class="text-xs text-text-muted">
				Bounce the chute back and forth at speed to exercise mechanics and stepper.
			</div>
		</div>
		<ChevronDown
			size={16}
			class="text-text-muted transition-transform {open ? 'rotate-180' : ''}"
		/>
	</button>

	{#if active && activeRun}
		<div class="border border-border bg-surface px-3 py-2 text-sm">
			<div class="flex items-center justify-between">
				<span class="font-medium {statusColor(activeRun.status)}">
					{statusLabel(activeRun.status)}
				</span>
				<span class="text-text-muted">{activeRun.mode}</span>
			</div>
			<div class="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs text-text-muted">
				<span>Elapsed</span>
				<span class="text-right text-text">
					{formatDuration(activeRun.total_time_s)} / {formatDuration(
						activeRun.duration_target_s
					)}
				</span>
				<span>Distance</span>
				<span class="text-right text-text">
					{activeRun.total_distance_deg.toFixed(1)}°
				</span>
				<span>Last target</span>
				<span class="text-right text-text">
					{activeRun.last_target_deg !== null && activeRun.last_target_deg !== undefined
						? `${activeRun.last_target_deg.toFixed(1)}°`
						: '--'}
				</span>
				<span>Speed</span>
				<span class="text-right text-text">
					{activeRun.speed_microsteps_per_sec} µsteps/s
				</span>
			</div>
		</div>
	{/if}
</div>

{#if open}
	<div class="flex flex-col gap-3">
		<label class="text-xs text-text">
			Mode
			<select
				bind:value={mode}
				disabled={active || busy}
				class="mt-1 block w-full border border-border bg-bg px-2 py-1.5 text-sm text-text disabled:cursor-not-allowed disabled:opacity-50"
			>
				<option value="sweep">Sweep (home ↔ target)</option>
				<option value="random">Random within [0°, target]</option>
			</select>
		</label>

		<label class="text-xs text-text">
			Target Max Angle (°) — max {CHUTE_STRESS_MAX_ANGLE}
			<input
				type="number"
				min="1"
				max={CHUTE_STRESS_MAX_ANGLE}
				step="1"
				bind:value={targetMaxDeg}
				disabled={active || busy}
				class="mt-1 block w-full border border-border bg-bg px-2 py-1.5 text-sm text-text disabled:cursor-not-allowed disabled:opacity-50"
			/>
		</label>

		<label class="text-xs text-text">
			Duration (seconds)
			<input
				type="number"
				min="1"
				step="1"
				bind:value={durationSec}
				disabled={active || busy}
				class="mt-1 block w-full border border-border bg-bg px-2 py-1.5 text-sm text-text disabled:cursor-not-allowed disabled:opacity-50"
			/>
		</label>

		<label class="flex items-center gap-2 text-xs text-text">
			<input
				type="checkbox"
				bind:checked={useMaxSpeed}
				disabled={active || busy}
				class="h-3.5 w-3.5"
			/>
			Use operating speed ({operatingSpeed} µsteps/s)
		</label>

		<label class="flex items-center gap-2 text-xs text-text">
			<input
				type="checkbox"
				bind:checked={invertDirection}
				disabled={active || busy}
				class="h-3.5 w-3.5"
			/>
			Invert direction
		</label>

		{#if !useMaxSpeed}
			<label class="text-xs text-text">
				Speed Override (µsteps/s)
				<input
					type="number"
					min="1"
					step="100"
					bind:value={speedOverride}
					disabled={active || busy}
					class="mt-1 block w-full border border-border bg-bg px-2 py-1.5 text-sm text-text disabled:cursor-not-allowed disabled:opacity-50"
				/>
			</label>
		{/if}

		<div class="flex flex-col gap-2">
			{#if !active}
				<button
					onclick={startRun}
					disabled={busy}
					class="inline-flex cursor-pointer items-center justify-center gap-1.5 border border-border bg-bg px-3 py-2 text-sm text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
				>
					<Play size={14} />
					{busy ? 'Starting...' : 'Start Stress Test'}
				</button>
			{:else}
				{#if activeRun?.status === 'paused'}
					<button
						onclick={resumeRun}
						disabled={busy}
						class="inline-flex cursor-pointer items-center justify-center gap-1.5 border border-border bg-bg px-3 py-2 text-sm text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
					>
						<Play size={14} />
						{busy ? 'Resuming...' : 'Resume'}
					</button>
				{:else}
					<button
						onclick={pauseRun}
						disabled={busy || activeRun?.status === 'stopping'}
						class="inline-flex cursor-pointer items-center justify-center gap-1.5 border border-border bg-bg px-3 py-2 text-sm text-text transition-colors hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
					>
						<Pause size={14} />
						{busy ? 'Pausing...' : 'Pause'}
					</button>
				{/if}
				<button
					onclick={stopRun}
					disabled={busy}
					class="inline-flex cursor-pointer items-center justify-center gap-1.5 border border-danger bg-danger/20 px-3 py-2 text-sm text-danger transition-colors hover:bg-danger/30 disabled:cursor-not-allowed disabled:opacity-50"
				>
					<Square size={14} />
					{busy ? 'Stopping...' : 'Stop'}
				</button>
			{/if}
		</div>

		{#if errorMsg}
			<div class="text-sm text-danger dark:text-red-400">{errorMsg}</div>
		{:else if statusMsg}
			<div class="text-sm text-text-muted">{statusMsg}</div>
		{/if}

		<div class="flex flex-col gap-2 border-t border-border pt-3">
			<div class="flex items-center justify-between">
				<div class="text-xs font-semibold tracking-wider text-text-muted uppercase">
					Past Runs
				</div>
				<button
					onclick={() => void loadRuns()}
					class="cursor-pointer text-xs text-text-muted underline hover:text-text"
				>
					Refresh
				</button>
			</div>

			{#if runs.length === 0}
				<div class="text-sm text-text-muted">No stress runs recorded yet.</div>
			{:else}
				<div class="flex max-h-48 flex-col overflow-y-auto border border-border">
					{#each runs as run (run.id)}
						<button
							onclick={() => (selectedRunId = selectedRunId === run.id ? null : run.id)}
							class="flex items-center justify-between gap-2 border-b border-border px-2 py-1.5 text-left text-sm last:border-b-0 hover:bg-surface
							{selectedRunId === run.id ? 'bg-surface' : ''}"
						>
							<span class="min-w-0 truncate text-text">
								{formatTimestamp(run.started_at)}
							</span>
							<span class="shrink-0 text-xs {statusColor(run.status)}">
								{statusLabel(run.status)}
							</span>
						</button>
					{/each}
				</div>
			{/if}

			{#if selectedRun}
				<div class="border border-border bg-surface px-3 py-2 text-sm">
					<div class="grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs text-text-muted">
						<span>Started</span>
						<span class="text-right text-text">{formatTimestamp(selectedRun.started_at)}</span>
						<span>Ended</span>
						<span class="text-right text-text">{formatTimestamp(selectedRun.ended_at)}</span>
						<span>Mode</span>
						<span class="text-right text-text">{selectedRun.mode}</span>
						<span>Target max</span>
						<span class="text-right text-text">{selectedRun.target_max_deg.toFixed(1)}°</span>
						<span>Duration target</span>
						<span class="text-right text-text">
							{formatDuration(selectedRun.duration_target_s)}
						</span>
						<span>Time elapsed</span>
						<span class="text-right text-text">{formatDuration(selectedRun.total_time_s)}</span>
						<span>Distance</span>
						<span class="text-right text-text">
							{selectedRun.total_distance_deg.toFixed(1)}°
						</span>
						<span>Speed</span>
						<span class="text-right text-text">
							{selectedRun.speed_microsteps_per_sec} µsteps/s
						</span>
						<span>Status</span>
						<span class="text-right {statusColor(selectedRun.status)}">
							{statusLabel(selectedRun.status)}
						</span>
					</div>
					{#if selectedRun.error}
						<div class="mt-2 text-xs text-danger dark:text-red-400">
							{selectedRun.error}
						</div>
					{/if}
				</div>
			{/if}

			{#if selectedRunId}
				<div class="flex flex-col gap-2 border-t border-border pt-3">
					<div class="flex items-center justify-between">
						<div class="flex items-center gap-2">
							<div class="text-xs font-semibold tracking-wider text-text-muted uppercase">
								Driver Telemetry
							</div>
							{#if telemetryLive}
								<span class="text-xs text-success dark:text-green-400">● live</span>
							{/if}
						</div>
						<button
							onclick={() => selectedRunId && void loadTelemetry(selectedRunId)}
							class="cursor-pointer text-xs text-text-muted underline hover:text-text"
						>
							Refresh
						</button>
					</div>

					{#if telemetryLoading}
						<div class="text-sm text-text-muted">Loading telemetry…</div>
					{:else if telemetryError}
						<div class="text-sm text-text-muted">{telemetryError}</div>
					{:else if telemetryPoints.length === 0}
						<div class="text-sm text-text-muted">No telemetry samples for this run.</div>
					{:else}
						{#if telemetrySettings}
							<div class="border border-border bg-bg px-3 py-2">
								<div class="mb-1 text-xs font-semibold tracking-wider text-text-muted uppercase">
									Driver settings (read from hardware at run start)
								</div>
								<div class="grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs text-text-muted">
									<span>Chopper mode</span>
									<span
										class="text-right {decodedField('gconf', 'stealthchop')
											? 'text-warning'
											: 'text-text'}"
									>
										{decodedField('gconf', 'stealthchop') === undefined
											? '--'
											: decodedField('gconf', 'stealthchop')
												? 'StealthChop'
												: 'SpreadCycle'}
									</span>
									<span>Microsteps</span>
									<span class="text-right text-text">
										{decodedField('chopconf', 'microsteps') ?? '--'}
									</span>
									<span>Interpolate (256)</span>
									<span class="text-right text-text">
										{decodedField('chopconf', 'intpol') === undefined
											? '--'
											: decodedField('chopconf', 'intpol')
												? 'on'
												: 'off'}
									</span>
									<span>Run current (IRUN)</span>
									<span class="text-right text-text">
										{configuredCurrent()?.['irun'] ?? '--'} / 31
									</span>
									<span>Hold current (IHOLD)</span>
									<span class="text-right text-text">
										{configuredCurrent()?.['ihold'] ?? '--'} / 31
									</span>
									<span>CS_ACTUAL @ start</span>
									<span class="text-right text-text">
										{decodedField('drv_status', 'cs_actual') ?? '--'} / 31
									</span>
									<span>OT prewarn @ start</span>
									<span
										class="text-right {decodedField('drv_status', 'otpw')
											? 'text-danger'
											: 'text-text'}"
									>
										{decodedField('drv_status', 'otpw') === undefined
											? '--'
											: decodedField('drv_status', 'otpw')
												? 'YES'
												: 'no'}
									</span>
									<span>Driver temp @ start</span>
									<span class="text-right text-text">{snapshotTempBand()}</span>
								</div>
								<div
									class="mt-2 grid grid-cols-2 gap-x-3 gap-y-0.5 border-t border-border pt-1 text-xs text-text-muted"
								>
									<span>GCONF</span>
									<span class="text-right font-mono text-text">
										{hex32(telemetrySettings.registers?.['gconf'])}
									</span>
									<span>CHOPCONF</span>
									<span class="text-right font-mono text-text">
										{hex32(telemetrySettings.registers?.['chopconf'])}
									</span>
									<span>DRV_STATUS</span>
									<span class="text-right font-mono text-text">
										{hex32(telemetrySettings.registers?.['drv_status'])}
									</span>
									<span>PWM_SCALE</span>
									<span class="text-right font-mono text-text">
										{hex32(telemetrySettings.registers?.['pwm_scale'])}
									</span>
								</div>
							</div>
						{/if}

						<div class="flex flex-wrap gap-x-3 gap-y-1 text-xs text-text">
							<label class="flex items-center gap-1.5">
								<input type="checkbox" bind:checked={showSg} class="h-3.5 w-3.5" />
								<span class="inline-block h-2 w-2 bg-primary"></span> SG_RESULT
							</label>
							<label class="flex items-center gap-1.5">
								<input type="checkbox" bind:checked={showPwm} class="h-3.5 w-3.5" />
								<span class="inline-block h-2 w-2 bg-danger"></span> PWM_SCALE
							</label>
							<label class="flex items-center gap-1.5">
								<input type="checkbox" bind:checked={showCs} class="h-3.5 w-3.5" />
								<span class="inline-block h-2 w-2 bg-warning"></span> CS_ACTUAL
							</label>
							<label class="flex items-center gap-1.5">
								<input type="checkbox" bind:checked={showTstep} class="h-3.5 w-3.5" />
								<span class="inline-block h-2 w-2 bg-success"></span> TSTEP
							</label>
						</div>

						<ChuteStressTelemetryChart
							points={telemetryPoints}
							{showSg}
							{showCs}
							{showPwm}
							{showTstep}
							height={260}
						/>

						<div class="text-xs text-text-muted">
							Series are min–max normalized; ranges below are absolute. {telemetryPoints.length}
							samples.
						</div>
						<div class="grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs text-text-muted">
							{#if sgStat}
								<span><span class="mr-1 inline-block h-2 w-2 bg-primary"></span>SG_RESULT</span>
								<span class="text-right text-text">
									{sgStat.min}–{sgStat.max} (now {sgStat.last})
								</span>
							{/if}
							{#if pwmStat}
								<span><span class="mr-1 inline-block h-2 w-2 bg-danger"></span>PWM_SCALE</span>
								<span class="text-right text-text">
									{pwmStat.min}–{pwmStat.max} (now {pwmStat.last})
								</span>
							{/if}
							{#if csStat}
								<span><span class="mr-1 inline-block h-2 w-2 bg-warning"></span>CS_ACTUAL</span>
								<span class="text-right text-text">
									{csStat.min}–{csStat.max} (now {csStat.last})
								</span>
							{/if}
							{#if tstepStat}
								<span><span class="mr-1 inline-block h-2 w-2 bg-success"></span>TSTEP</span>
								<span class="text-right text-text">
									{tstepStat.min}–{tstepStat.max}
								</span>
							{/if}
							<span>Over-temp / OT-prewarn samples</span>
							<span class="text-right {warnCount > 0 ? 'text-danger' : 'text-text'}">
								{warnCount}
							</span>
						</div>
					{/if}
				</div>
			{/if}
		</div>
	</div>
{/if}
