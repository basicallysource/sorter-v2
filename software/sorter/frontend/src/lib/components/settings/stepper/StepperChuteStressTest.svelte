<script lang="ts">
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import { ChevronDown, Play, Pause, Square } from 'lucide-svelte';
	import { onDestroy, onMount } from 'svelte';

	type StressMode = 'sweep' | 'random';
	type RunStatus =
		| 'running'
		| 'paused'
		| 'stopping'
		| 'completed'
		| 'stopped'
		| 'failed';

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
	let targetMaxDeg = $state(300);
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
			default:
				return status;
		}
	}

	function statusColor(status: RunStatus): string {
		if (status === 'running') return 'text-primary';
		if (status === 'paused' || status === 'stopping') return 'text-warning';
		if (status === 'completed') return 'text-success dark:text-green-400';
		if (status === 'failed') return 'text-danger dark:text-red-400';
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
		// When the active run transitions away from running/paused, refresh the runs list
		const status = activeRun?.status;
		if (status === 'completed' || status === 'stopped' || status === 'failed') {
			void loadRuns();
		}
	});

	onMount(() => {
		void loadStatus();
	});

	onDestroy(stopPolling);

	const selectedRun = $derived(
		selectedRunId ? runs.find((r) => r.id === selectedRunId) ?? null : null
	);
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
		</div>
	</div>
{/if}
