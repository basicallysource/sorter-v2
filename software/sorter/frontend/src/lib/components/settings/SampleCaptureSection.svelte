<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import Switch from '$lib/components/ui/Switch.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import SettingRow from '$lib/components/ui/SettingRow.svelte';

	const machine = getMachineContext();

	const STATUS_POLL_MS = 3000;

	const GB = 1024 ** 3;

	// Backend defaults (sample_collector.py) — drive the changed-from-default
	// highlight + revert on each row. The burst, floor, ramp and store size have
	// no default of their own: they follow the limits Hive sets.
	const DEFAULT_ENABLED = false;
	const DEFAULT_ANNOTATE = true;
	const DEFAULT_PER_MINUTE = 6;
	const DEFAULT_DECAY_ENABLED = true;
	const DEFAULT_JITTER_PCT = 30; // 0.3

	// The limits Hive sets, as the machine sees them (the strictest across its Hives).
	type HiveLimits = {
		sample_burst_interval_s: number;
		sample_floor_interval_s: number;
		sample_ramp_hours: number;
		sample_store_max_bytes: number;
		upload_bytes_per_minute: number;
		upload_files_per_minute: number;
	};

	// What is set on this machine; null = following Hive.
	type LocalSettings = {
		burst_interval_s: number | null;
		floor_interval_s: number | null;
		ramp_hours: number | null;
		store_max_mb: number | null;
	};

	type StoreInfo = {
		stored: number;
		stored_bytes: number;
		not_on_every_hive: number;
		cap_bytes: number;
		disk_free_bytes: number | null;
		min_free_bytes: number;
		dropped_queue_full: number;
		skipped_low_disk: number;
	};

	type FollowableKey = 'burst_interval_s' | 'floor_interval_s' | 'ramp_hours' | 'storage_cap_mb';

	let enabled = $state(false);
	let annotate = $state(true);
	let perMinute = $state(6);
	let decayEnabled = $state(true);
	// The schedule in force: what is set here where set, else Hive's limit.
	let burstS = $state(10);
	let floorS = $state(3600);
	let rampH = $state(72);
	let local = $state<LocalSettings>({
		burst_interval_s: null,
		floor_interval_s: null,
		ramp_hours: null,
		store_max_mb: null
	});
	let hive = $state<HiveLimits | null>(null);
	let store = $state<StoreInfo | null>(null);
	let jitterPct = $state(30);
	let decayElapsedS = $state<number | null>(null);
	let currentIntervalS = $state<number | null>(null);
	let savedCount = $state(0);
	let lastSavedAgeS = $state<number | null>(null);
	let lastError = $state<string | null>(null);
	let initialized = $state(false);

	let loading = $state(true);
	let saving = $state(false);
	let errorMsg = $state<string | null>(null);

	let pollTimer: ReturnType<typeof setInterval> | null = null;

	function currentBackendBaseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? getBackendHttpBase();
	}

	function numberOrNull(value: unknown): number | null {
		return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : null;
	}

	function round(n: number, digits = 1): number {
		const f = 10 ** digits;
		return Math.round(n * f) / f;
	}

	function formatInterval(s: number): string {
		if (s < 120) return `${round(s)} s`;
		if (s < 7200) return `${round(s / 60)} min`;
		return `${round(s / 3600)} h`;
	}

	function formatBytes(bytes: number): string {
		if (bytes === 0) return '0 B';
		const units = ['B', 'KB', 'MB', 'GB'];
		const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
		const val = bytes / Math.pow(1024, i);
		return `${val.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
	}

	function applyStatus(payload: any) {
		initialized = payload?.reason !== 'collector_not_initialized';
		enabled = Boolean(payload?.enabled);
		annotate = payload?.annotate !== false;
		const ivl = Number(payload?.interval_s);
		if (Number.isFinite(ivl) && ivl > 0) perMinute = Math.round((60 / ivl) * 10) / 10;
		decayEnabled = payload?.decay_enabled !== false;
		const burst = Number(payload?.burst_interval_s);
		if (Number.isFinite(burst) && burst > 0) burstS = burst;
		const floor = Number(payload?.floor_interval_s);
		if (Number.isFinite(floor) && floor > 0) floorS = floor;
		const ramp = Number(payload?.ramp_hours);
		if (Number.isFinite(ramp) && ramp >= 0) rampH = ramp;
		const localRaw = payload?.local_settings ?? {};
		local = {
			burst_interval_s: numberOrNull(localRaw.burst_interval_s),
			floor_interval_s: numberOrNull(localRaw.floor_interval_s),
			ramp_hours: numberOrNull(localRaw.ramp_hours),
			store_max_mb: numberOrNull(localRaw.store_max_mb)
		};
		hive = payload?.hive_limits ?? null;
		store = payload?.store ?? null;
		const jit = Number(payload?.jitter_frac);
		if (Number.isFinite(jit) && jit >= 0) jitterPct = Math.round(jit * 100);
		const elapsed = Number(payload?.decay_elapsed_s);
		decayElapsedS = Number.isFinite(elapsed) ? elapsed : null;
		const curInterval = Number(payload?.current_interval_s);
		currentIntervalS = Number.isFinite(curInterval) && curInterval > 0 ? curInterval : null;
		savedCount = Number(payload?.saved_count) || 0;
		const age = Number(payload?.last_saved_age_s);
		lastSavedAgeS = Number.isFinite(age) ? age : null;
		lastError = typeof payload?.last_error === 'string' ? payload.last_error : null;
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

	// A number sets the value on this machine; an empty field (or the reset
	// button) clears it, so the machine follows Hive's limit again.
	function saveLocal(key: FollowableKey, raw: string, toApi: (n: number) => number = (n) => n) {
		if (raw.trim() === '') {
			void post({ [key]: null });
			return;
		}
		const n = Number(raw);
		if (!Number.isFinite(n) || n <= 0) return;
		void post({ [key]: toApi(n) });
	}

	function followHive(key: FollowableKey) {
		void post({ [key]: null });
	}

	function valueOf(event: Event): string {
		return (event.currentTarget as HTMLInputElement).value;
	}

	function saveJitter(pct: number) {
		if (!Number.isFinite(pct) || pct < 0) return;
		void post({ jitter_frac: Math.min(1, pct / 100) });
	}

	function resetDecay() {
		void post({ reset_decay: true });
	}

	// Hive's limits in the units the inputs use.
	const hiveBurst = $derived(hive ? round(hive.sample_burst_interval_s, 2) : null);
	const hiveFloorMin = $derived(hive ? round(hive.sample_floor_interval_s / 60, 2) : null);
	const hiveRampH = $derived(hive ? round(hive.sample_ramp_hours, 2) : null);
	const hiveCapGb = $derived(hive ? round(hive.sample_store_max_bytes / GB, 2) : null);

	const hint = (n: number | null) => (n === null ? undefined : `Hive: ${n}`);
	const followText = (n: number | null, unit: string) =>
		n === null ? undefined : `Hive (${n} ${unit})`;

	// Decay curve for the graph: geometric growth of the interval from burst to
	// floor across the ramp — a straight line in log space, plotted as rate.
	const GRAPH_W = 300;
	const GRAPH_H = 96;
	const PAD_X = 8;
	const PAD_Y = 10;
	const curve = $derived.by(() => {
		const rampLenH = Math.max(0.01, rampH);
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
		const nowFrac = elapsedH !== null ? Math.min(1, Math.max(0, elapsedH / rampLenH)) : null;
		return {
			polyline: points.join(' '),
			nowX: nowFrac !== null ? xAt(nowFrac) : null,
			nowY: nowFrac !== null ? yAt(logB + span * nowFrac) : null
		};
	});

	onMount(() => {
		void loadStatus();
		pollTimer = setInterval(() => void loadStatus(false), STATUS_POLL_MS);
	});

	onDestroy(() => {
		if (pollTimer) clearInterval(pollTimer);
	});
</script>

<div class="divide-y divide-line">
	<SettingRow
		label="Capture training frames"
		help="Takes the latest frame from every live camera at the rate below, only while the machine is sorting. Frames are saved to a capped store on this machine and uploaded to Hive in the background. It only reads camera frames and does not change how the machine sorts. The setting persists across restarts."
		changed={enabled !== DEFAULT_ENABLED}
		defaultText={DEFAULT_ENABLED ? 'on' : 'off'}
		onreset={() => saveEnabled(DEFAULT_ENABLED)}
	>
		<Switch
			checked={enabled}
			label="Capture training frames"
			disabled={loading || saving || !initialized}
			onchange={(on) => saveEnabled(on)}
		/>
	</SettingRow>

	<SettingRow
		label="Annotate with OpenRouter"
		help="Run the Gemini (gemini_sam) detector on each frame before it is saved so samples arrive in Hive as teacher captures. Adds an OpenRouter call per frame per camera. If off (or no API key), frames are saved and uploaded as raw samples."
		changed={annotate !== DEFAULT_ANNOTATE}
		defaultText={DEFAULT_ANNOTATE ? 'on' : 'off'}
		onreset={() => saveAnnotate(DEFAULT_ANNOTATE)}
	>
		<Switch
			checked={annotate}
			label="Annotate with OpenRouter"
			disabled={loading || saving || !initialized}
			onchange={(on) => saveAnnotate(on)}
		/>
	</SettingRow>

	<SettingRow
		label="Decay capture rate"
		help="Capture a burst of frames when a run starts, then slow down geometrically to a floor over the ramp, with random jitter, so the same rig stops saving near-identical frames forever. Reset re-arms the burst."
		changed={decayEnabled !== DEFAULT_DECAY_ENABLED}
		defaultText={DEFAULT_DECAY_ENABLED ? 'on' : 'off'}
		onreset={() => saveDecayEnabled(DEFAULT_DECAY_ENABLED)}
		below={decayEnabled ? decayDetails : undefined}
	>
		<Switch
			checked={decayEnabled}
			label="Decay capture rate"
			disabled={loading || saving || !initialized}
			onchange={(on) => saveDecayEnabled(on)}
		/>
	</SettingRow>

	{#if !decayEnabled}
		<SettingRow
			label="Capture rate"
			help="Frames per minute per camera. Default 6 (one every 10s)."
			for="sample-capture-rate"
			changed={perMinute !== DEFAULT_PER_MINUTE}
			defaultText={String(DEFAULT_PER_MINUTE)}
			onreset={() => saveRate(DEFAULT_PER_MINUTE)}
		>
			<Input
				id="sample-capture-rate"
				type="number"
				min={0.1}
				max={600}
				step={1}
				value={perMinute}
				disabled={loading || saving || !initialized}
				onchange={(event) => saveRate(Number((event.currentTarget as HTMLInputElement).value))}
				unit="/min"
				class="w-32"
			/>
		</SettingRow>
	{/if}

	<SettingRow
		label="Sample store size"
		help="Keep at most this much on this machine, never more than Hive allows. When it is full, samples every Hive already has are deleted first, then the oldest."
		for="sample-capture-storage-cap"
		changed={local.store_max_mb !== null}
		defaultText={followText(hiveCapGb, 'GB')}
		defaultHelp="Follow the size Hive sets again."
		onreset={() => followHive('storage_cap_mb')}
	>
		<Input
			id="sample-capture-storage-cap"
			type="number"
			min={0.1}
			max={hiveCapGb ?? 500}
			step={0.5}
			value={local.store_max_mb === null ? null : round(local.store_max_mb / 1024, 2)}
			placeholder={hint(hiveCapGb)}
			disabled={loading || saving || !initialized}
			onchange={(event) =>
				saveLocal('storage_cap_mb', valueOf(event), (gb) =>
					Math.round(Math.min(gb, hiveCapGb ?? Infinity) * 1024)
				)}
			unit="GB"
			class="w-36"
		/>
	</SettingRow>

	<div class="flex flex-col gap-1 px-(--pad-panel) py-(--pad-row) text-sm text-ink-muted">
		{#if !initialized && !loading}
			<p>The sample collector hasn't started on this machine (no camera service yet).</p>
		{/if}
		{#if store}
			{@const lowDisk = store.disk_free_bytes !== null && store.disk_free_bytes < store.min_free_bytes}
			<p>
				Stored on this machine: <span class="num font-medium text-ink">{store.stored.toLocaleString()}</span>
				samples, <span class="num font-medium text-ink">{formatBytes(store.stored_bytes)}</span> of
				<span class="num font-medium text-ink">{formatBytes(store.cap_bytes)}</span>.
				<span class="num font-medium text-ink">{store.not_on_every_hive.toLocaleString()}</span>
				not on every Hive yet.
			</p>
			{#if store.disk_free_bytes !== null}
				<p class={lowDisk ? 'text-warning-ink' : ''}>
					<span class="num font-medium {lowDisk ? '' : 'text-ink'}">{formatBytes(store.disk_free_bytes)}</span>
					free on the disk{#if lowDisk}, so no samples are saved until there is
						{formatBytes(store.min_free_bytes)} free{/if}.
				</p>
			{/if}
			{#if store.dropped_queue_full > 0}
				<p class="text-warning-ink">
					<span class="num font-medium">{store.dropped_queue_full.toLocaleString()}</span> frames dropped since
					startup because saving could not keep up.
				</p>
			{/if}
			{#if store.skipped_low_disk > 0}
				<p class="text-warning-ink">
					<span class="num font-medium">{store.skipped_low_disk.toLocaleString()}</span> frames skipped since
					startup because the disk was low on space.
				</p>
			{/if}
		{/if}
		<p>
			Saved since startup: <span class="num font-medium text-ink">{savedCount}</span>{#if enabled && lastSavedAgeS !== null},
				the last one {lastSavedAgeS.toFixed(1)} s ago{/if}.
		</p>
		{#if errorMsg}
			<p class="text-danger-ink">{errorMsg}</p>
		{:else if lastError}
			<p class="text-danger-ink">The last capture failed: {lastError}</p>
		{/if}
	</div>
</div>

{#snippet decayDetails()}
		<div class="flex items-center justify-between gap-3 px-(--pad-panel) pt-3">
			<p class="num text-sm text-ink-muted">
				Every <span class="font-medium text-ink">{formatInterval(burstS)}</span>, slowing to every
				<span class="font-medium text-ink">{formatInterval(floorS)}</span> over
				<span class="font-medium text-ink">{formatInterval(rampH * 3600)}</span>{#if currentIntervalS !== null}.
					Now every <span class="font-medium text-ink">{formatInterval(currentIntervalS)}</span>{/if}.
			</p>
			<Button
				variant="ghost"
				size="sm"
				disabled={loading || saving || !initialized}
				onclick={resetDecay}
			>
				Reset decay
			</Button>
		</div>

		<svg
			viewBox="0 0 {GRAPH_W} {GRAPH_H}"
			class="block h-24 w-full px-(--pad-panel) py-2"
			role="img"
			aria-label="The capture rate falling from the burst rate to the floor over the ramp"
		>
			<line
				x1={PAD_X}
				y1={GRAPH_H - PAD_Y}
				x2={GRAPH_W - PAD_X}
				y2={GRAPH_H - PAD_Y}
				class="text-line-strong"
				stroke="currentColor"
				stroke-width="1"
				vector-effect="non-scaling-stroke"
			/>
			<polyline
				points={curve.polyline}
				class="text-primary-ink"
				fill="none"
				stroke="currentColor"
				stroke-width="1.5"
				vector-effect="non-scaling-stroke"
			/>
			{#if curve.nowX !== null}
				<line
					x1={curve.nowX}
					y1={PAD_Y}
					x2={curve.nowX}
					y2={GRAPH_H - PAD_Y}
					class="text-primary-ink"
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
					class="text-primary-ink"
					fill="currentColor"
				/>
			{/if}
		</svg>
		<div class="divide-y divide-line">
		<SettingRow
			label="Burst interval"
			help="Seconds between frames per camera right after a reset. Never faster than Hive allows."
			for="decay-burst"
			changed={local.burst_interval_s !== null}
			defaultText={followText(hiveBurst, 's')}
			defaultHelp="Follow the interval Hive sets again."
			onreset={() => followHive('burst_interval_s')}
		>
			<Input
				id="decay-burst"
				type="number"
				min={hiveBurst ?? 0.1}
				step={1}
				value={local.burst_interval_s}
				placeholder={hint(hiveBurst)}
				disabled={loading || saving || !initialized}
				onchange={(event) =>
					saveLocal('burst_interval_s', valueOf(event), (sec) => Math.max(sec, hiveBurst ?? 0))}
				unit="s"
				class="w-36"
			/>
		</SettingRow>

		<SettingRow
			label="Floor interval"
			help="Minutes between frames per camera once the decay has settled."
			for="decay-floor"
			changed={local.floor_interval_s !== null}
			defaultText={followText(hiveFloorMin, 'min')}
			defaultHelp="Follow the interval Hive sets again."
			onreset={() => followHive('floor_interval_s')}
		>
			<Input
				id="decay-floor"
				type="number"
				min={0.1}
				step="any"
				value={local.floor_interval_s === null ? null : round(local.floor_interval_s / 60, 2)}
				placeholder={hint(hiveFloorMin)}
				disabled={loading || saving || !initialized}
				onchange={(event) => saveLocal('floor_interval_s', valueOf(event), (min) => min * 60)}
				unit="min"
				class="w-36"
			/>
		</SettingRow>

		<SettingRow
			label="Ramp"
			help="Hours to go from the burst interval to the floor interval."
			for="decay-ramp"
			changed={local.ramp_hours !== null}
			defaultText={followText(hiveRampH, 'h')}
			defaultHelp="Follow the ramp Hive sets again."
			onreset={() => followHive('ramp_hours')}
		>
			<Input
				id="decay-ramp"
				type="number"
				min={0.1}
				step="any"
				value={local.ramp_hours}
				placeholder={hint(hiveRampH)}
				disabled={loading || saving || !initialized}
				onchange={(event) => saveLocal('ramp_hours', valueOf(event))}
				unit="h"
				class="w-36"
			/>
		</SettingRow>

		<SettingRow
			label="Jitter"
			help="Random wobble on each interval so captures aren't perfectly periodic."
			for="decay-jitter"
			changed={jitterPct !== DEFAULT_JITTER_PCT}
			defaultText="{DEFAULT_JITTER_PCT}%"
			onreset={() => saveJitter(DEFAULT_JITTER_PCT)}
		>
			<Input
				id="decay-jitter"
				type="number"
				min={0}
				max={100}
				step={5}
				value={jitterPct}
				disabled={loading || saving || !initialized}
				onchange={(event) => saveJitter(Number((event.currentTarget as HTMLInputElement).value))}
				unit="%"
				class="w-32"
			/>
		</SettingRow>
		</div>
{/snippet}
