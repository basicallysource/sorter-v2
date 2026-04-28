<script lang="ts">
	import { backendHttpBaseUrl } from '$lib/backend';
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

	function modeKey(m: { width?: number | null; height?: number | null } | null | undefined): string {
		if (!m || !m.width || !m.height) return '';
		return `${m.width}x${m.height}`;
	}

	async function load() {
		loading = true;
		error = null;
		status = '';
		try {
			const res = await fetch(`${backendHttpBaseUrl}/api/cameras/capture-modes/${role}`, {
				cache: 'no-store'
			});
			if (!res.ok) throw new Error(await res.text());
			const parsed = (await res.json()) as CaptureModeResponse;
			data = parsed;
			selectedKey = modeKey(parsed.current) || modeKey(parsed.live) || '';
		} catch (e: any) {
			error = e.message ?? 'Failed to load capture modes';
		} finally {
			loading = false;
		}
	}

	async function save(key: string) {
		if (!data) return;
		const mode = data.modes.find((m) => modeKey(m) === key);
		if (!mode) return;
		saving = true;
		error = null;
		status = '';
		try {
			const res = await fetch(`${backendHttpBaseUrl}/api/cameras/capture-modes/${role}`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					width: mode.width,
					height: mode.height,
					fps: mode.fps,
					fourcc: mode.fourcc
				})
			});
			if (!res.ok) throw new Error(await res.text());
			const parsed = await res.json();
			status = parsed.message ?? 'Capture mode saved.';
			selectedKey = key;
			await load();
		} catch (e: any) {
			error = e.message ?? 'Failed to save capture mode';
		} finally {
			saving = false;
		}
	}

	function onChange(ev: Event) {
		const value = (ev.target as HTMLSelectElement).value;
		if (value && value !== selectedKey) {
			void save(value);
		}
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
				onchange={onChange}
			>
				{#if !selectedKey}
					<option value="" disabled>— pick a resolution —</option>
				{/if}
				{#each data.modes as mode}
					<option value={modeKey(mode)}>
						{mode.width}×{mode.height} @ {mode.fps} fps
						{#if mode.fourcc}({mode.fourcc}){/if}
					</option>
				{/each}
			</select>
			<div class="mt-1 text-sm text-text-muted">
				FPS auto = max supported. JPEG-compressed FourCC (e.g. MJPG) for max throughput.
			</div>
		</div>
		{#if status}
			<div class="text-sm text-text-muted">{status}</div>
		{/if}
	{/if}
</div>
