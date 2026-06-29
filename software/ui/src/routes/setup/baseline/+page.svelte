<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { backendHttpBaseUrl } from '$lib/backend';
	import Modal from '$lib/components/Modal.svelte';
	import { AlertTriangle, Play, Square, Check, Settings } from 'lucide-svelte';

	interface BaselineStatus {
		active: boolean;
		running?: boolean;
		camera?: string;
		frame?: number;
		total?: number;
		message?: string;
		done?: boolean;
		ok?: boolean;
		error?: string | null;
	}

	let camera = $state('all');
	let wipe = $state(true);
	let status = $state<BaselineStatus>({ active: false });
	let error = $state<string | null>(null);
	let poll: ReturnType<typeof setInterval> | null = null;

	// Chute wiggle settings (editable any time; applied live while a capture runs).
	let settingsOpen = $state(false);
	let chuteHz = $state(5.0);
	let chuteSteps = $state(40);
	let chuteMsg = $state('');

	async function loadChute() {
		try {
			const s = await (await fetch(`${backendHttpBaseUrl}/calibration/baseline/chute-settings`)).json();
			chuteHz = s.hz;
			chuteSteps = s.steps;
		} catch {
			/* ignore */
		}
	}

	async function saveChute() {
		chuteMsg = '';
		try {
			const res = await fetch(
				`${backendHttpBaseUrl}/calibration/baseline/chute-settings?hz=${chuteHz}&steps=${chuteSteps}`,
				{ method: 'POST' }
			);
			if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? res.statusText);
			const s = await res.json();
			chuteHz = s.hz;
			chuteSteps = s.steps;
			chuteMsg = running ? 'Applied live.' : 'Saved.';
		} catch (e) {
			chuteMsg = 'Failed: ' + (e as Error).message;
		}
	}

	async function refresh() {
		try {
			status = await (await fetch(`${backendHttpBaseUrl}/calibration/baseline/status`)).json();
		} catch (e) {
			error = (e as Error).message;
		}
	}

	async function start() {
		error = null;
		try {
			const res = await fetch(
				`${backendHttpBaseUrl}/calibration/baseline/start?camera=${camera}&wipe=${wipe}`,
				{ method: 'POST' }
			);
			if (!res.ok) {
				const d = await res.json().catch(() => ({}));
				throw new Error(d.detail ?? res.statusText);
			}
			status = { active: true, ...(await res.json()) };
		} catch (e) {
			error = (e as Error).message;
		}
	}

	async function cancel() {
		try {
			await fetch(`${backendHttpBaseUrl}/calibration/baseline/cancel`, { method: 'POST' });
		} catch {
			/* ignore */
		}
	}

	onMount(() => {
		refresh();
		loadChute();
		poll = setInterval(refresh, 700);
	});
	onDestroy(() => poll && clearInterval(poll));

	let running = $derived(status.active && status.running && !status.done);
	let pct = $derived(status.total ? Math.round(((status.frame ?? 0) / status.total) * 100) : 0);
</script>

<div class="dark:bg-bg-dark min-h-screen bg-bg p-6">
	<div class="mx-auto max-w-2xl">
		<div class="mb-4 flex items-center gap-3">
			<a href="/setup" class="dark:text-text-dark text-text">&larr;</a>
			<h1 class="dark:text-text-dark text-2xl font-bold text-text">Classification Baseline</h1>
			<button
				onclick={() => (settingsOpen = true)}
				title="Chute wiggle settings"
				class="dark:text-text-dark dark:hover:bg-surface-dark ml-auto flex items-center gap-1 rounded p-2 text-text hover:bg-surface"
			>
				<Settings size={20} />
			</button>
		</div>

		<div class="mb-4 flex items-start gap-3 rounded-lg bg-amber-500/15 p-4 text-amber-600 dark:text-amber-400">
			<AlertTriangle size={20} class="mt-0.5 flex-shrink-0" />
			<div class="text-sm">
				This rotates the <b>carousel</b> through a full sweep and vibrates the <b>chute</b> while
				capturing ~{status.total ?? 64} frames. Make sure the classification chamber is empty
				(no pieces) and the machine is clear before starting.
			</div>
		</div>

		{#if error}
			<div class="mb-4 rounded bg-red-500/15 px-4 py-2 text-sm text-red-500">{error}</div>
		{/if}

		<div class="dark:bg-surface-dark rounded-lg bg-surface p-4">
			{#if running}
				<div class="mb-2 flex items-center justify-between">
					<span class="dark:text-text-dark text-sm font-medium text-text">{status.message}</span>
					<span class="dark:text-text-muted-dark text-sm text-text-muted">{status.frame}/{status.total}</span>
				</div>
				<div class="dark:bg-bg-dark mb-4 h-3 w-full overflow-hidden rounded bg-bg">
					<div class="h-full bg-blue-600 transition-all" style="width: {pct}%"></div>
				</div>
				<button onclick={cancel} class="flex items-center gap-2 rounded bg-red-600 px-4 py-2 text-sm font-medium text-white">
					<Square size={16} /> Cancel
				</button>
			{:else if status.done && status.ok}
				<div class="mb-4 flex items-center gap-2 text-green-500"><Check size={20} /> Baseline captured.</div>
				<a href="/setup" class="rounded bg-green-600 px-4 py-2 text-sm font-medium text-white">Back to Setup</a>
			{:else}
				{#if status.done && !status.ok}
					<div class="mb-3 text-sm text-red-500">Last run: {status.error ?? status.message ?? 'failed'}</div>
				{/if}
				<div class="mb-4 flex flex-wrap items-center gap-4">
					<label class="dark:text-text-dark text-sm text-text">
						Cameras:
						<select bind:value={camera} class="dark:bg-bg-dark ml-2 rounded bg-bg px-2 py-1">
							<option value="all">Classification + Carousel</option>
							<option value="classification">Classification only</option>
							<option value="carousel">Carousel only</option>
						</select>
					</label>
					<label class="dark:text-text-dark flex items-center gap-2 text-sm text-text">
						<input type="checkbox" bind:checked={wipe} /> Wipe previous frames
					</label>
				</div>
				<button onclick={start} class="flex items-center gap-2 rounded bg-green-600 px-4 py-2 font-medium text-white">
					<Play size={18} /> Capture Baseline
				</button>
			{/if}
		</div>
	</div>
</div>

<Modal bind:open={settingsOpen} title="Chute wiggle settings">
	<div class="flex flex-col gap-4">
		<p class="dark:text-text-muted-dark text-sm text-text-muted">
			The chute vibrates during capture so the baseline absorbs normal machine vibration.
			Changes save immediately and apply <b>live</b> if a capture is already running.
		</p>
		<label class="dark:text-text-dark flex items-center justify-between text-sm text-text">
			Frequency (Hz)
			<input type="number" step="0.5" min="0" bind:value={chuteHz}
				class="dark:bg-bg-dark w-32 rounded bg-bg px-2 py-1 text-right" />
		</label>
		<label class="dark:text-text-dark flex items-center justify-between text-sm text-text">
			Amplitude (microsteps)
			<input type="number" step="1" min="0" bind:value={chuteSteps}
				class="dark:bg-bg-dark w-32 rounded bg-bg px-2 py-1 text-right" />
		</label>
		<div class="flex items-center gap-3">
			<button onclick={saveChute} class="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white">Save</button>
			{#if chuteMsg}<span class="dark:text-text-muted-dark text-sm text-text-muted">{chuteMsg}</span>{/if}
		</div>
	</div>
</Modal>
