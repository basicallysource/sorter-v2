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
		current?: {
			width?: number | null;
			height?: number | null;
			fps?: number | null;
			fourcc?: string | null;
		} | null;
		live?: { width?: number | null; height?: number | null; fps?: number | null } | null;
		message?: string;
	};

	let { role }: { role: CameraRole } = $props();

	let loading = $state(true);
	let saving = $state(false);
	let error = $state<string | null>(null);
	let status = $state('');
	let data = $state<CaptureModeResponse | null>(null);
	let selectedModeKey = $state<string>('');
	let displayModes = $derived(modesForDisplay(data?.modes ?? []));

	function modeKey(
		m: { width?: number | null; height?: number | null; fps?: number | null } | null | undefined
	): string {
		if (!m || !m.width || !m.height || !m.fps) return '';
		return `${m.width}x${m.height}@${m.fps}`;
	}

	function resolutionKey(
		m: { width?: number | null; height?: number | null } | null | undefined
	): string {
		if (!m || !m.width || !m.height) return '';
		return `${m.width}x${m.height}`;
	}

	function modesForDisplay(modes: CaptureMode[]): CaptureMode[] {
		const mjpg = modes.filter((m) => (m.fourcc || '').toUpperCase() === 'MJPG');
		return mjpg.length > 0 ? mjpg : modes;
	}

	function pickInitialModeKey(
		currentWidth: number | null | undefined,
		currentHeight: number | null | undefined,
		currentFps: number | null | undefined
	): string {
		const modes = displayModes;
		const wantRes = resolutionKey({ width: currentWidth, height: currentHeight });
		const wantFps = currentFps ?? 0;
		// Exact match first
		const exact = modes.find((m) => resolutionKey(m) === wantRes && m.fps === wantFps);
		if (exact) return modeKey(exact);
		// Same resolution, highest fps
		const sameRes = modes.filter((m) => resolutionKey(m) === wantRes).sort((a, b) => b.fps - a.fps);
		if (sameRes.length > 0) return modeKey(sameRes[0]);
		// First mode overall
		return modes.length > 0 ? modeKey(modes[0]) : '';
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
			selectedModeKey = pickInitialModeKey(
				parsed.current?.width ?? parsed.live?.width ?? null,
				parsed.current?.height ?? parsed.live?.height ?? null,
				parsed.current?.fps ?? null
			);
		} catch (e: any) {
			error = e.message ?? 'Failed to load capture modes';
		} finally {
			loading = false;
		}
	}

	async function save(modeKeyStr: string) {
		if (!data) return;
		const mode =
			displayModes.find((m) => modeKey(m) === modeKeyStr) ??
			data.modes.find((m) => modeKey(m) === modeKeyStr);
		if (!mode) return;
		saving = true;
		error = null;
		status = '';
		try {
			const res = await fetch(`${getBackendHttpBase()}/api/cameras/capture-modes/${role}`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ width: mode.width, height: mode.height, fps: mode.fps })
			});
			if (!res.ok) throw new Error(await res.text());
			const parsed = await res.json();
			status = parsed.message ?? 'Capture mode saved.';
			selectedModeKey = modeKeyStr;
			await load();
		} catch (e: any) {
			error = e.message ?? 'Failed to save capture mode';
		} finally {
			saving = false;
		}
	}

	function onModeChange(ev: Event) {
		const value = (ev.target as HTMLSelectElement).value;
		if (!value || value === selectedModeKey) return;
		void save(value);
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
			<div class="mb-1 text-sm font-medium text-text">Mode</div>
			<select
				class="w-full border border-border bg-surface px-2 py-2 text-sm text-text focus:border-primary focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
				value={selectedModeKey}
				disabled={saving}
				onchange={onModeChange}
			>
				{#if !selectedModeKey}
					<option value="" disabled>— pick a mode —</option>
				{/if}
				{#each Array.from(new Set(displayModes.map((m) => modeKey(m)))) as key}
					{@const sample = displayModes.find((m) => modeKey(m) === key)}
					{#if sample}
						<option value={key}>{sample.width}×{sample.height} @ {sample.fps} fps</option>
					{/if}
				{/each}
			</select>
		</div>
		{#if status}
			<div class="text-sm text-text-muted">{status}</div>
		{/if}
	{/if}
</div>
