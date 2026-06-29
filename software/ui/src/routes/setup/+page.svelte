<script lang="ts">
	import { onMount } from 'svelte';
	import { station, STEP_LABELS, type StationState } from '$lib/station';
	import { Check, Circle, Camera, Hexagon, Crosshair, Power, PowerOff, ArrowLeft } from 'lucide-svelte';

	let state = $state<StationState | null>(null);
	let error = $state<string | null>(null);
	let busy = $state(false);

	const steps = [
		{ key: 'cameras_assigned', icon: Camera, href: '/setup/cameras', label: STEP_LABELS.cameras_assigned },
		{ key: 'feeder_polygons', icon: Hexagon, href: '/setup/polygons', label: STEP_LABELS.feeder_polygons },
		{ key: 'classification_polygons', icon: Hexagon, href: '/setup/polygons', label: STEP_LABELS.classification_polygons },
		{ key: 'classification_baseline', icon: Crosshair, href: '/setup/baseline', label: STEP_LABELS.classification_baseline }
	] as const;

	async function refresh() {
		try {
			state = await station.state();
			error = null;
		} catch (e) {
			error = (e as Error).message;
		}
	}

	function done(key: string): boolean {
		return !!state?.readiness[key as keyof StationState['readiness']];
	}

	// A step is unlocked once every step before it is done (sequential wizard).
	function unlocked(i: number): boolean {
		return steps.slice(0, i).every((s) => done(s.key));
	}

	async function activate() {
		busy = true;
		try {
			state = await station.run();
			error = null;
		} catch (e) {
			error = (e as Error).message;
		} finally {
			busy = false;
		}
	}

	async function deactivate() {
		busy = true;
		try {
			state = await station.stop();
		} catch (e) {
			error = (e as Error).message;
		} finally {
			busy = false;
		}
	}

	onMount(() => {
		refresh();
		const t = setInterval(refresh, 2000);
		return () => clearInterval(t);
	});

	let canRun = $derived(state != null && state.missing_to_run.length === 0);
</script>

<div class="dark:bg-bg-dark min-h-screen bg-bg p-6">
	<div class="mb-6 flex items-center justify-between">
		<div class="flex items-center gap-3">
			<a href="/" class="dark:text-text-dark p-2 text-text" title="Live view"><ArrowLeft size={22} /></a>
			<h1 class="dark:text-text-dark text-2xl font-bold text-text">Setup &amp; Calibration</h1>
		</div>
		{#if state}
			<span class="dark:text-text-muted-dark text-sm text-text-muted">station: <b>{state.mode}</b></span>
		{/if}
	</div>

	{#if error}
		<div class="mb-4 rounded bg-red-500/15 px-4 py-2 text-sm text-red-500">{error}</div>
	{/if}

	<div class="mx-auto flex max-w-2xl flex-col gap-3">
		{#each steps as step, i}
			{@const isDone = done(step.key)}
			{@const isOpen = unlocked(i)}
			<a
				href={isOpen ? step.href : undefined}
				aria-disabled={!isOpen}
				class="dark:bg-surface-dark flex items-center gap-4 rounded-lg bg-surface p-4 transition-colors
					{isOpen ? 'hover:ring-2 hover:ring-blue-500/50' : 'cursor-not-allowed opacity-50'}"
			>
				<div class="flex h-10 w-10 items-center justify-center rounded-full
					{isDone ? 'bg-green-500/20 text-green-500' : 'dark:bg-bg-dark bg-bg text-text-muted'}">
					{#if isDone}<Check size={20} />{:else}<step.icon size={20} />{/if}
				</div>
				<div class="flex-1">
					<div class="dark:text-text-dark font-medium text-text">{i + 1}. {step.label}</div>
					<div class="dark:text-text-muted-dark text-xs text-text-muted">
						{isDone ? 'Done' : isOpen ? 'Ready' : 'Complete previous steps first'}
					</div>
				</div>
				{#if isDone}
					<Check class="text-green-500" size={18} />
				{:else}
					<Circle class="text-text-muted" size={18} />
				{/if}
			</a>
		{/each}

		<div class="dark:bg-surface-dark mt-4 flex items-center justify-between rounded-lg bg-surface p-4">
			<div>
				<div class="dark:text-text-dark font-medium text-text">Sorter</div>
				<div class="dark:text-text-muted-dark text-xs text-text-muted">
					{#if state?.mode === 'running'}
						Active — control operation from the <a href="/" class="underline">main page</a>.
					{:else if canRun}
						All steps complete. Activate to power up the machine.
					{:else if state}
						Blocked: {state.missing_to_run.map((m) => STEP_LABELS[m] ?? m).join(', ')}
					{/if}
				</div>
			</div>
			{#if state?.mode === 'running'}
				<button onclick={deactivate} disabled={busy}
					class="flex items-center gap-2 rounded bg-red-600 px-4 py-2 font-medium text-white disabled:opacity-50">
					<PowerOff size={18} /> Deactivate Sorter
				</button>
			{:else}
				<button onclick={activate} disabled={!canRun || busy}
					class="flex items-center gap-2 rounded bg-green-600 px-4 py-2 font-medium text-white disabled:opacity-50">
					<Power size={18} /> Activate Sorter
				</button>
			{/if}
		</div>
	</div>
</div>
