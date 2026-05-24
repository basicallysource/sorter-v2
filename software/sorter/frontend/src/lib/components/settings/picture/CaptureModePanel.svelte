<script lang="ts">
	import { getBackendHttpBase } from '$lib/backend';
	import { Alert } from '$lib/components/primitives';
	import type { CameraRole } from '$lib/settings/stations';

	type CaptureMode = {
		width: number;
		height: number;
		fps: number;
		fourcc: string;
		native_fourcc?: string;
	};

	type CaptureModeResponse = {
		ok: boolean;
		role: string;
		source?: number | string | null;
		supported: boolean;
		backend?: string;
		modes: CaptureMode[];
		current?: { width?: number | null; height?: number | null; fps?: number | null; fourcc?: string | null } | null;
		live?: { width?: number | null; height?: number | null; fps?: number | null } | null;
		message?: string;
	};

	let { role }: { role: CameraRole } = $props();

	let loading = $state(true);
	let saving = $state(false);
	let error = $state<string | null>(null);
	let status = $state('');
	let data = $state<CaptureModeResponse | null>(null);
	let selectedKey = $state<string>('');
	let selectedFourcc = $state<string>('');
	let fourccOptions = $derived(fourccsForKey(selectedKey));

	function modeKey(m: { width?: number | null; height?: number | null } | null | undefined): string {
		if (!m || !m.width || !m.height) return '';
		return `${m.width}x${m.height}`;
	}

	function fourccsForKey(key: string): string[] {
		if (!data) return [];
		const seen = new Set<string>();
		const out: string[] = [];
		for (const m of data.modes) {
			if (modeKey(m) !== key) continue;
			const fc = (m.fourcc || '').toUpperCase();
			if (!fc || seen.has(fc)) continue;
			seen.add(fc);
			out.push(fc);
		}
		// Always make MJPG the first option when available — it's the default.
		out.sort((a, b) => (a === 'MJPG' ? -1 : b === 'MJPG' ? 1 : a.localeCompare(b)));
		return out;
	}

	function pickInitialFourcc(key: string, current: string | null | undefined): string {
		const options = fourccsForKey(key);
		if (options.length === 0) return '';
		const want = (current || '').toUpperCase();
		if (want && options.includes(want)) return want;
		return options.includes('MJPG') ? 'MJPG' : options[0];
	}

	async function load() {
		loading = true;
		error = null;
		status = '';
		try {
			const res = await fetch(`${getBackendHttpBase()}/api/cameras/capture-modes/${role}`, {
				cache: 'no-store'
			});
			if (!res.ok) throw new Error(await res.text());
			const parsed = (await res.json()) as CaptureModeResponse;
			data = parsed;
			selectedKey = modeKey(parsed.current) || modeKey(parsed.live) || '';
			selectedFourcc = pickInitialFourcc(selectedKey, parsed.current?.fourcc ?? null);
		} catch (e: any) {
			error = e.message ?? 'Failed to load capture modes';
		} finally {
			loading = false;
		}
	}

	async function save(key: string, fourccChoice: string) {
		if (!data) return;
		const fcUpper = (fourccChoice || '').toUpperCase();
		const mode =
			data.modes.find(
				(m) => modeKey(m) === key && (m.fourcc || '').toUpperCase() === fcUpper
			) ?? data.modes.find((m) => modeKey(m) === key);
		if (!mode) return;
		saving = true;
		error = null;
		status = '';
		try {
			const res = await fetch(`${getBackendHttpBase()}/api/cameras/capture-modes/${role}`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					width: mode.width,
					height: mode.height,
					fps: mode.fps,
					fourcc: fcUpper || mode.fourcc
				})
			});
			if (!res.ok) throw new Error(await res.text());
			const parsed = await res.json();
			status = parsed.message ?? 'Capture mode saved.';
			selectedKey = key;
			selectedFourcc = fcUpper;
			await load();
		} catch (e: any) {
			error = e.message ?? 'Failed to save capture mode';
		} finally {
			saving = false;
		}
	}

	function onResolutionChange(ev: Event) {
		const value = (ev.target as HTMLSelectElement).value;
		if (!value || value === selectedKey) return;
		const nextFourcc = pickInitialFourcc(value, selectedFourcc);
		void save(value, nextFourcc);
	}

	function onFourccChange(ev: Event) {
		const value = (ev.target as HTMLSelectElement).value;
		if (!value || value === selectedFourcc) return;
		void save(selectedKey, value);
	}

	$effect(() => {
		void role;
		void load();
	});
</script>

<div class="grid gap-2 border-t border-border pt-3">
	<div class="flex items-baseline justify-between">
		<div class="text-xs font-semibold tracking-wider text-text-muted uppercase">Capture Mode</div>
		{#if data?.live?.width && data?.live?.height}
			<div class="text-xs text-text-muted">
				Live {data.live.width}×{data.live.height}{#if data.live.fps}
					 @ {data.live.fps} fps{/if}
			</div>
		{/if}
	</div>

	{#if error}
		<Alert variant="danger">
			<div class="text-sm text-text">{error}</div>
		</Alert>
	{/if}

	{#if loading}
		<div class="text-sm text-text-muted">Loading capture modes…</div>
	{:else if !data?.supported}
		<div class="text-sm text-text-muted">
			{data?.message ?? 'Resolution selection not available for this camera.'}
		</div>
	{:else}
		<div>
			<div class="mb-1 text-sm font-medium text-text">Resolution</div>
			<select
				class="w-full border border-border bg-surface px-2 py-2 text-sm text-text focus:border-primary focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
				value={selectedKey}
				disabled={saving}
				onchange={onResolutionChange}
			>
				{#if !selectedKey}
					<option value="" disabled>— pick a resolution —</option>
				{/if}
				{#each Array.from(new Set(data.modes.map((m) => modeKey(m)))) as key}
					{@const sample = data.modes.find((m) => modeKey(m) === key)}
					{#if sample}
						<option value={key}>
							{sample.width}×{sample.height} @ {sample.fps} fps
						</option>
					{/if}
				{/each}
			</select>
		</div>
		<div>
			<div class="mb-1 text-sm font-medium text-text">Pixel Format</div>
			<select
				class="w-full border border-border bg-surface px-2 py-2 text-sm text-text focus:border-primary focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
				value={selectedFourcc}
				disabled={saving || fourccOptions.length === 0}
				onchange={onFourccChange}
			>
				{#if fourccOptions.length === 0}
					<option value="">—</option>
				{/if}
				{#each fourccOptions as fc}
					<option value={fc}>{fc}{fc === 'MJPG' ? ' (default)' : ''}</option>
				{/each}
			</select>
			<div class="mt-1 text-sm text-text-muted">
				MJPG is the default — compressed, ~10× lower USB bandwidth than YUYV. Pick another only if this camera needs it.
			</div>
		</div>
		{#if status}
			<div class="text-sm text-text-muted">{status}</div>
		{/if}
	{/if}
</div>
