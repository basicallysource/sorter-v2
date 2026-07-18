<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import { ToggleSwitch } from '$lib/components/primitives';
	import SettingRow from '$lib/components/settings/SettingRow.svelte';

	const machine = getMachineContext();

	const STATUS_POLL_MS = 3000;

	// Backend defaults (classification_training.py) — drive the changed-from-
	// default highlight + revert on each row.
	const DEFAULT_ENABLED = false;
	const DEFAULT_ANNOTATE = true;
	const DEFAULT_PER_MINUTE = 6;
	const DEFAULT_STORAGE_CAP_GB = 1;

	let enabled = $state(false);
	let annotate = $state(true);
	let perMinute = $state(6);
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
