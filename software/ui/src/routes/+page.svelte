<script lang="ts">
	import { onMount } from 'svelte';
	import { getMachinesContext, getMachineContext } from '$lib/machines/context';
	import CameraFeed from '$lib/components/CameraFeed.svelte';
	import RecentObjects from '$lib/components/RecentObjects.svelte';
	import SettingsModal from '$lib/components/SettingsModal.svelte';
	import RuntimeVariablesModal from '$lib/components/RuntimeVariablesModal.svelte';
	import MachineDropdown from '$lib/components/MachineDropdown.svelte';
	import { Settings, Wrench, Pause, Play, SlidersHorizontal } from 'lucide-svelte';
	import type { components } from '$lib/api/rest';
	import { backendHttpBaseUrl, backendWsBaseUrl } from '$lib/backend';

	type StateResponse = components['schemas']['StateResponse'];

	const manager = getMachinesContext();
	const machine = getMachineContext();

	let settings_open = $state(false);
	let runtime_vars_open = $state(false);
	let machine_state = $state<string>('initializing');

	// Draggable split between the camera grid (left) and Recent Pieces (right).
	// leftPct = % of the row width given to the cameras; the rest goes to Recent Pieces.
	let leftPct = $state(60);
	let splitContainer = $state<HTMLDivElement | null>(null);

	// Cameras shown, in a stable order; only those currently delivering frames.
	const CAMERA_ORDER = ['c_channel_2', 'c_channel_3', 'carousel', 'classification', 'feeder'];

	function startDrag(e: PointerEvent) {
		e.preventDefault();
		const onMove = (ev: PointerEvent) => {
			if (!splitContainer) return;
			const rect = splitContainer.getBoundingClientRect();
			const pct = ((ev.clientX - rect.left) / rect.width) * 100;
			leftPct = Math.min(85, Math.max(25, pct));
		};
		const onUp = () => {
			window.removeEventListener('pointermove', onMove);
			window.removeEventListener('pointerup', onUp);
			try {
				localStorage.setItem('dashboard_left_pct', String(leftPct));
			} catch {
				/* ignore */
			}
		};
		window.addEventListener('pointermove', onMove);
		window.addEventListener('pointerup', onUp);
	}

	async function fetchState() {
		try {
			const res = await fetch(`${backendHttpBaseUrl}/state`);
			if (res.ok) {
				const data: StateResponse = await res.json();
				machine_state = data.state;
			}
		} catch {
			// ignore
		}
	}

	async function togglePauseResume() {
		const endpoint = machine_state === 'paused' ? '/resume' : '/pause';
		try {
			await fetch(`${backendHttpBaseUrl}${endpoint}`, { method: 'POST' });
			await fetchState();
		} catch {
			// ignore
		}
	}

	onMount(() => {
		const stored = Number(localStorage.getItem('dashboard_left_pct'));
		if (stored >= 25 && stored <= 85) leftPct = stored;
		manager.connect(`${backendWsBaseUrl}/ws`);
		fetchState();
		const interval = setInterval(fetchState, 1000);
		return () => clearInterval(interval);
	});
</script>

<div class="dark:bg-bg-dark min-h-screen bg-bg p-6">
	<div class="mb-4 flex items-center justify-between">
		<h1 class="dark:text-text-dark text-2xl font-bold text-text">Sorter</h1>
		<div class="flex items-center gap-2">
			<MachineDropdown />
			<a
				href="/setup"
				class="dark:text-text-dark dark:hover:bg-surface-dark p-2 text-text transition-colors hover:bg-surface"
				title="Setup & Calibration"
			>
				<SlidersHorizontal size={24} />
			</a>
			<button
				onclick={togglePauseResume}
				class="dark:text-text-dark dark:hover:bg-surface-dark p-2 text-text transition-colors hover:bg-surface"
				title={machine_state === 'paused' ? 'Resume' : 'Pause'}
			>
				{#if machine_state === 'paused'}
					<Play size={24} />
				{:else}
					<Pause size={24} />
				{/if}
			</button>
			<button
				onclick={() => (runtime_vars_open = true)}
				class="dark:text-text-dark dark:hover:bg-surface-dark p-2 text-text transition-colors hover:bg-surface"
				title="Runtime Variables"
			>
				<Wrench size={24} />
			</button>
			<button
				onclick={() => (settings_open = true)}
				class="dark:text-text-dark dark:hover:bg-surface-dark p-2 text-text transition-colors hover:bg-surface"
				title="Settings"
			>
				<Settings size={24} />
			</button>
		</div>
	</div>

	{#if machine.machine}
		{@const cams = CAMERA_ORDER.filter((c) => machine.frames.has(c))}
		<div bind:this={splitContainer} class="flex items-stretch">
			<!-- Camera grid: 2 columns, each cell aspect-locked (no side whitespace).
			     Scales with the splitter width. -->
			<div class="grid grid-cols-2 content-start gap-3" style="width: {leftPct}%">
				{#each cams as cam (cam)}
					<CameraFeed camera={cam} />
				{/each}
			</div>

			<!-- Draggable splitter: left = smaller cameras / wider list; right = bigger cameras. -->
			<div
				role="separator"
				aria-orientation="vertical"
				title="Drag to resize"
				onpointerdown={startDrag}
				class="dark:bg-border-dark mx-1.5 w-1.5 flex-shrink-0 cursor-col-resize rounded bg-border transition-colors hover:bg-blue-500"
			></div>

			<!-- Recent Pieces takes all remaining horizontal space. -->
			<div class="min-w-0 flex-1">
				<RecentObjects />
			</div>
		</div>
	{:else}
		<div class="dark:text-text-muted-dark py-12 text-center text-text-muted">
			No machine selected. Connect to a machine in Settings.
		</div>
	{/if}
</div>

<SettingsModal bind:open={settings_open} />
<RuntimeVariablesModal bind:open={runtime_vars_open} />
