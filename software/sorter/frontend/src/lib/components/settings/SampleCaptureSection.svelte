<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import { ToggleSwitch, Button } from '$lib/components/primitives';
	import SettingRow from '$lib/components/settings/SettingRow.svelte';

	const machine = getMachineContext();

	const STATUS_POLL_MS = 3000;

	// Backend defaults (classification_training.py) — drive the changed-from-
	// default highlight + revert on each row.
	const DEFAULT_ENABLED = false;
	const DEFAULT_ANNOTATE = true;
	const DEFAULT_PER_MINUTE = 6;
	const DEFAULT_STORAGE_CAP_GB = 1;
	// Decay defaults mirror sample_collector.py.
	const DEFAULT_DECAY_ENABLED = true;
	const DEFAULT_BURST_PER_MINUTE = 6; // 10s interval
	const DEFAULT_FLOOR_PER_HOUR = 1; // 3600s interval
	const DEFAULT_RAMP_DAYS = 3; // 72h
	const DEFAULT_JITTER_PCT = 30; // 0.3

	let enabled = $state(false);
	let annotate = $state(true);
	let perMinute = $state(6);
	let decayEnabled = $state(true);
	let burstPerMinute = $state(6);
	let floorPerHour = $state(1);
	let rampDays = $state(3);
	let jitterPct = $state(30);
	let decayElapsedS = $state<number | null>(null);
	let currentRatePerMin = $state<number | null>(null);
	let storageCapGb = $state(1);
	let storageUsedMb = $state<number | null>(null);
	let savedCount = $state(0);
	let lastSavedAgeS = $state<number | null>(null);
	let lastError = $state<string | null>(null);
	let outputDir = $state('');
	let initialized = $state(false);

	let loading = $state(true);
	let saving = $state(false);
	let errorMsg = $state<string | null>(null);

	let pollTimer: ReturnType<typeof setInterval> | null = null;

	function currentBackendBaseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? getBackendHttpBase();
	}

	function applyStatus(payload: any) {
		initialized = payload?.reason !== 'collector_not_initialized';
		enabled = Boolean(payload?.enabled);
		annotate = payload?.annotate !== false;
		const ivl = Number(payload?.interval_s);
		if (Number.isFinite(ivl) && ivl > 0) perMinute = Math.round((60 / ivl) * 10) / 10;
		decayEnabled = payload?.decay_enabled !== false;
		const burstS = Number(payload?.burst_interval_s);
		if (Number.isFinite(burstS) && burstS > 0) burstPerMinute = Math.round((60 / burstS) * 10) / 10;
		const floorS = Number(payload?.floor_interval_s);
		if (Number.isFinite(floorS) && floorS > 0) floorPerHour = Math.round((3600 / floorS) * 100) / 100;
		const rampH = Number(payload?.ramp_hours);
		if (Number.isFinite(rampH) && rampH >= 0) rampDays = Math.round((rampH / 24) * 100) / 100;
		const jit = Number(payload?.jitter_frac);
		if (Number.isFinite(jit) && jit >= 0) jitterPct = Math.round(jit * 100);
		const elapsed = Number(payload?.decay_elapsed_s);
		decayElapsedS = Number.isFinite(elapsed) ? elapsed : null;
		const curRate = Number(payload?.current_rate_per_min);
		currentRatePerMin = Number.isFinite(curRate) ? curRate : null;
		const capMb = Number(payload?.storage_cap_mb);
		if (Number.isFinite(capMb) && capMb > 0) storageCapGb = Math.round((capMb / 1024) * 100) / 100;
		const usedMb = Number(payload?.storage_used_mb);
		storageUsedMb = Number.isFinite(usedMb) ? usedMb : null;
		savedCount = Number(payload?.saved_count) || 0;
		const age = Number(payload?.last_saved_age_s);
		lastSavedAgeS = Number.isFinite(age) ? age : null;
		lastError = typeof payload?.last_error === 'string' ? payload.last_error : null;
		if (typeof payload?.output_dir === 'string') outputDir = payload.output_dir;
	}

	async function loadStatus(showLoading = true) {
		if (showLoading) loading = true;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/system/sample-capture`);
			if (!res.ok) throw new Error(await res.text());
			applyStatus(await res.json());
			errorMsg = null;
		} catch (e: any) {
			errorMsg = e?.message ?? 'Failed to load sample-capture status.';
		} finally {
			if (showLoading) loading = false;
		}
	}

	async function post(body: Record<string, unknown>) {
		saving = true;
		errorMsg = null;
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/system/sample-capture`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(body)
			});
			if (!res.ok) throw new Error(await res.text());
			applyStatus(await res.json());
		} catch (e: any) {
			errorMsg = e?.message ?? 'Failed to update sample capture.';
		} finally {
			saving = false;
		}
	}

	function saveEnabled(next: boolean) {
		void post({ enabled: next });
	}

	function saveAnnotate(next: boolean) {
		void post({ annotate: next });
	}

	function saveRate(next: number) {
		if (!Number.isFinite(next) || next <= 0) return;
		void post({ interval_s: 60 / next });
	}

	function saveDecayEnabled(next: boolean) {
		void post({ decay_enabled: next });
	}

	function saveBurst(perMin: number) {
		if (!Number.isFinite(perMin) || perMin <= 0) return;
		void post({ burst_interval_s: 60 / perMin });
	}

	function saveFloor(perHour: number) {
		if (!Number.isFinite(perHour) || perHour <= 0) return;
		void post({ floor_interval_s: 3600 / perHour });
	}

	function saveRamp(days: number) {
		if (!Number.isFinite(days) || days < 0) return;
		void post({ ramp_hours: days * 24 });
	}

	function saveJitter(pct: number) {
		if (!Number.isFinite(pct) || pct < 0) return;
		void post({ jitter_frac: Math.min(1, pct / 100) });
	}

	function resetDecay() {
		void post({ reset_decay: true });
	}

	// Decay curve for the graph: geometric growth of the interval from burst to
	// floor across the ramp — a straight line in log space, plotted as rate.
	const GRAPH_W = 300;
	const GRAPH_H = 96;
	const PAD_X = 8;
	const PAD_Y = 10;
	const curve = $derived.by(() => {
		const burstS = 60 / Math.max(0.001, burstPerMinute);
		const floorS = 3600 / Math.max(0.001, floorPerHour);
		const rampH = Math.max(0.01, rampDays * 24);
		const logB = Math.log(burstS);
		const logF = Math.log(floorS);
		const span = logF - logB || 1;
		const xAt = (frac: number) => PAD_X + frac * (GRAPH_W - 2 * PAD_X);
		const yAt = (logI: number) => PAD_Y + ((logI - logB) / span) * (GRAPH_H - 2 * PAD_Y);
		const steps = 32;
		const points: string[] = [];
		for (let i = 0; i <= steps; i++) {
			const frac = i / steps;
			points.push(`${xAt(frac).toFixed(1)},${yAt(logB + span * frac).toFixed(1)}`);
		}
		const elapsedH = decayElapsedS !== null ? decayElapsedS / 3600 : null;
		const nowFrac = elapsedH !== null ? Math.min(1, Math.max(0, elapsedH / rampH)) : null;
		return {
			polyline: points.join(' '),
			nowX: nowFrac !== null ? xAt(nowFrac) : null,
			nowY: nowFrac !== null ? yAt(logB + span * nowFrac) : null
		};
	});

	function saveStorageCap(nextGb: number) {
		if (!Number.isFinite(nextGb) || nextGb <= 0) return;
		void post({ storage_cap_mb: Math.round(nextGb * 1024) });
	}

	onMount(() => {
		void loadStatus();
		pollTimer = setInterval(() => void loadStatus(false), STATUS_POLL_MS);
	});

	onDestroy(() => {
		if (pollTimer) clearInterval(pollTimer);
	});
</script>

<div class="flex flex-col gap-2">
	<SettingRow
		label="Capture training frames"
		description="Snapshots the latest frame from every live camera at the rate below and feeds each into the classification pipeline — saved to a session, queued, and uploaded to Hive. Runs in any machine mode without changing sorting behavior; it only reads camera frames. The setting persists across restarts."
		changed={enabled !== DEFAULT_ENABLED}
		defaultLabel={DEFAULT_ENABLED ? 'on' : 'off'}
		onRevert={() => saveEnabled(DEFAULT_ENABLED)}
	>
		<ToggleSwitch
			checked={enabled}
			label="Capture training frames"
			disabled={loading || saving || !initialized}
			onToggle={() => saveEnabled(!enabled)}
		/>
	</SettingRow>

	<SettingRow
		label="Annotate with OpenRouter"
		description="Run the Gemini (gemini_sam) detector on each frame before upload so samples arrive in Hive as teacher captures. Adds an OpenRouter call per frame per camera. If off (or no API key), frames upload as raw samples."
		changed={annotate !== DEFAULT_ANNOTATE}
		defaultLabel={DEFAULT_ANNOTATE ? 'on' : 'off'}
		onRevert={() => saveAnnotate(DEFAULT_ANNOTATE)}
	>
		<ToggleSwitch
			checked={annotate}
			label="Annotate with OpenRouter"
			disabled={loading || saving || !initialized}
			onToggle={() => saveAnnotate(!annotate)}
		/>
	</SettingRow>

	<SettingRow
		label="Decay capture rate"
		description="Capture a burst of frames when a run starts, then slow down geometrically to a floor over the ramp, with random jitter — so the same rig stops re-uploading near-identical frames forever. Reset re-arms the burst."
		changed={decayEnabled !== DEFAULT_DECAY_ENABLED}
		defaultLabel={DEFAULT_DECAY_ENABLED ? 'on' : 'off'}
		onRevert={() => saveDecayEnabled(DEFAULT_DECAY_ENABLED)}
	>
		<ToggleSwitch
			checked={decayEnabled}
			label="Decay capture rate"
			disabled={loading || saving || !initialized}
			onToggle={() => saveDecayEnabled(!decayEnabled)}
		/>
	</SettingRow>

	{#if decayEnabled}
		<div class="flex flex-col gap-2 border border-border bg-bg px-3 py-3">
			<div class="flex items-center justify-between gap-3">
				<span class="text-sm text-text-muted">
					burst <span class="text-text">{burstPerMinute}/min</span> → floor
					<span class="text-text">{floorPerHour}/hr</span> over
					<span class="text-text">{rampDays}d</span>
					{#if currentRatePerMin !== null}
						· now ≈ <span class="text-text">{currentRatePerMin.toFixed(2)}/min</span>
					{/if}
				</span>
				<Button
					variant="secondary"
					size="sm"
					disabled={loading || saving || !initialized}
					onclick={resetDecay}
				>
					Reset decay
				</Button>
			</div>

			<svg viewBox="0 0 {GRAPH_W} {GRAPH_H}" class="h-24 w-full" role="img" aria-label="Capture-rate decay curve">
				<line
					x1={PAD_X}
					y1={GRAPH_H - PAD_Y}
					x2={GRAPH_W - PAD_X}
					y2={GRAPH_H - PAD_Y}
					class="text-text-muted"
					stroke="currentColor"
					stroke-width="0.5"
					opacity="0.4"
				/>
				<polyline
					points={curve.polyline}
					class="text-primary"
					fill="none"
					stroke="currentColor"
					stroke-width="1.5"
				/>
				{#if curve.nowX !== null}
					<line
						x1={curve.nowX}
						y1={PAD_Y}
						x2={curve.nowX}
						y2={GRAPH_H - PAD_Y}
						class="text-primary"
						stroke="currentColor"
						stroke-width="0.75"
						stroke-dasharray="2 2"
						opacity="0.7"
					/>
					<rect
						x={curve.nowX - 2.5}
						y={(curve.nowY ?? 0) - 2.5}
						width="5"
						height="5"
						class="text-primary"
						fill="currentColor"
					/>
				{/if}
			</svg>

			<SettingRow
				label="Burst rate"
				description="Frames per minute per camera right after a reset."
				forId="decay-burst"
				changed={burstPerMinute !== DEFAULT_BURST_PER_MINUTE}
				defaultLabel="{DEFAULT_BURST_PER_MINUTE}/min"
				onRevert={() => saveBurst(DEFAULT_BURST_PER_MINUTE)}
			>
				<input
					id="decay-burst"
					type="number"
					min="0.1"
					max="600"
					step="1"
					value={burstPerMinute}
					disabled={loading || saving || !initialized}
					onchange={(event) => saveBurst(Number(event.currentTarget.value))}
					class="w-20 border border-border bg-bg px-2 py-1 text-right text-sm text-text outline-none focus:border-primary"
				/>
				<span class="text-sm text-text-muted">/min</span>
			</SettingRow>

			<SettingRow
				label="Floor rate"
				description="The slow steady-state rate the decay settles to."
				forId="decay-floor"
				changed={floorPerHour !== DEFAULT_FLOOR_PER_HOUR}
				defaultLabel="{DEFAULT_FLOOR_PER_HOUR}/hr"
				onRevert={() => saveFloor(DEFAULT_FLOOR_PER_HOUR)}
			>
				<input
					id="decay-floor"
					type="number"
					min="0.01"
					max="60"
					step="0.5"
					value={floorPerHour}
					disabled={loading || saving || !initialized}
					onchange={(event) => saveFloor(Number(event.currentTarget.value))}
					class="w-20 border border-border bg-bg px-2 py-1 text-right text-sm text-text outline-none focus:border-primary"
				/>
				<span class="text-sm text-text-muted">/hr</span>
			</SettingRow>

			<SettingRow
				label="Ramp"
				description="Days to go from the burst rate down to the floor."
				forId="decay-ramp"
				changed={rampDays !== DEFAULT_RAMP_DAYS}
				defaultLabel="{DEFAULT_RAMP_DAYS}d"
				onRevert={() => saveRamp(DEFAULT_RAMP_DAYS)}
			>
				<input
					id="decay-ramp"
					type="number"
					min="0.1"
					max="30"
					step="0.5"
					value={rampDays}
					disabled={loading || saving || !initialized}
					onchange={(event) => saveRamp(Number(event.currentTarget.value))}
					class="w-20 border border-border bg-bg px-2 py-1 text-right text-sm text-text outline-none focus:border-primary"
				/>
				<span class="text-sm text-text-muted">days</span>
			</SettingRow>

			<SettingRow
				label="Jitter"
				description="Random wobble on each interval so captures aren't perfectly periodic."
				forId="decay-jitter"
				changed={jitterPct !== DEFAULT_JITTER_PCT}
				defaultLabel="{DEFAULT_JITTER_PCT}%"
				onRevert={() => saveJitter(DEFAULT_JITTER_PCT)}
			>
				<input
					id="decay-jitter"
					type="number"
					min="0"
					max="100"
					step="5"
					value={jitterPct}
					disabled={loading || saving || !initialized}
					onchange={(event) => saveJitter(Number(event.currentTarget.value))}
					class="w-20 border border-border bg-bg px-2 py-1 text-right text-sm text-text outline-none focus:border-primary"
				/>
				<span class="text-sm text-text-muted">%</span>
			</SettingRow>
		</div>
	{:else}
		<SettingRow
			label="Capture rate"
			description="Frames per minute per camera. Default 6 (one every 10s)."
			forId="sample-capture-rate"
			changed={perMinute !== DEFAULT_PER_MINUTE}
			defaultLabel={String(DEFAULT_PER_MINUTE)}
			onRevert={() => saveRate(DEFAULT_PER_MINUTE)}
		>
			<input
				id="sample-capture-rate"
				type="number"
				min="0.1"
				max="600"
				step="1"
				value={perMinute}
				disabled={loading || saving || !initialized}
				onchange={(event) => saveRate(Number(event.currentTarget.value))}
				class="w-20 border border-border bg-bg px-2 py-1 text-right text-sm text-text outline-none focus:border-primary"
			/>
			<span class="text-sm text-text-muted">/min</span>
		</SettingRow>
	{/if}

	<SettingRow
		label="Local storage cap"
		description="Keep at most this much captured imagery on disk. Once exceeded, the oldest samples are deleted first."
		forId="sample-capture-storage-cap"
		changed={storageCapGb !== DEFAULT_STORAGE_CAP_GB}
		defaultLabel="{DEFAULT_STORAGE_CAP_GB} GB"
		onRevert={() => saveStorageCap(DEFAULT_STORAGE_CAP_GB)}
	>
		{#if storageUsedMb !== null}
			<span class="text-sm text-text-muted">
				using {(storageUsedMb / 1024).toFixed(2)} GB ·
			</span>
		{/if}
		<input
			id="sample-capture-storage-cap"
			type="number"
			min="0.1"
			max="500"
			step="0.5"
			value={storageCapGb}
			disabled={loading || saving}
			onchange={(event) => saveStorageCap(Number(event.currentTarget.value))}
			class="w-20 border border-border bg-bg px-2 py-1 text-right text-sm text-text outline-none focus:border-primary"
		/>
		<span class="text-sm text-text-muted">GB</span>
	</SettingRow>

	{#if !initialized && !loading}
		<div class="text-sm text-text-muted">
			Sample collector is not initialized on this machine (no camera service yet).
		</div>
	{/if}

	<div class="flex flex-col gap-1 text-sm text-text-muted">
		<span>
			Saved this session: <span class="font-medium text-text">{savedCount}</span>
			{#if enabled && lastSavedAgeS !== null}
				· last frame {lastSavedAgeS.toFixed(1)}s ago
			{/if}
		</span>
		{#if outputDir}
			<span class="break-all">Writing to <span class="text-text">{outputDir}</span></span>
		{/if}
	</div>

	{#if errorMsg}
		<div class="text-sm text-danger dark:text-red-400">{errorMsg}</div>
	{:else if lastError}
		<div class="text-sm text-danger dark:text-red-400">Last capture error: {lastError}</div>
	{/if}
</div>
