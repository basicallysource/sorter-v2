<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import SectionCard from '$lib/components/settings/SectionCard.svelte';
	import { Alert, Button, Input } from '$lib/components/primitives';
	import { getMachinesContext } from '$lib/machines/context';

	const manager = getMachinesContext();

	type StressEvent = {
		id: number;
		created_at: number;
		event_type: string;
		phase: string | null;
		details: Record<string, unknown>;
	};

	type StressRun = {
		id: string;
		started_at: number;
		ended_at: number | null;
		duration_target_s: number;
		stepper_speed_microsteps_per_sec: number;
		chute_speed_microsteps_per_sec: number;
		chute_max_deg: number;
		status: string;
		total_time_s: number;
		current_phase: string | null;
		current_segment?: number;
		error: string | null;
		hardware?: {
			steppers: string[];
			servo_count: number;
			led_output_count: number;
			perception_workers_alive: number;
			camera_roles: string[];
		};
		events?: StressEvent[];
	};

	let durationMinutes = $state(10);
	let stepperSpeed = $state(6000);
	let chuteSpeed = $state(3000);
	let chuteMax = $state(345);
	let active = $state(false);
	let run = $state<StressRun | null>(null);
	let runs = $state<StressRun[]>([]);
	let busy = $state(false);
	let errorMsg = $state<string | null>(null);
	let pollTimer: ReturnType<typeof setInterval> | null = null;

	const progressPercent = $derived(
		run ? Math.min(100, (run.total_time_s / run.duration_target_s) * 100) : 0
	);

	function backendBase(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? getBackendHttpBase()
		);
	}

	async function readError(response: Response): Promise<string> {
		try {
			const payload = await response.json();
			if (typeof payload?.detail === 'string') return payload.detail;
		} catch {
			return `Request failed with status ${response.status}`;
		}
		return `Request failed with status ${response.status}`;
	}

	async function loadStatus() {
		try {
			const response = await fetch(`${backendBase()}/api/power-stress/status`);
			if (!response.ok) throw new Error(await readError(response));
			const payload = await response.json();
			active = Boolean(payload.active);
			if (payload.run) run = payload.run;
		} catch (error) {
			errorMsg = error instanceof Error ? error.message : String(error);
		}
	}

	async function loadRuns() {
		try {
			const response = await fetch(`${backendBase()}/api/power-stress/runs?limit=20`);
			if (!response.ok) throw new Error(await readError(response));
			runs = (await response.json()).runs ?? [];
		} catch (error) {
			errorMsg = error instanceof Error ? error.message : String(error);
		}
	}

	async function startTest() {
		busy = true;
		errorMsg = null;
		try {
			const response = await fetch(`${backendBase()}/api/power-stress/start`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					duration_s: durationMinutes * 60,
					stepper_speed_microsteps_per_sec: stepperSpeed,
					chute_speed_microsteps_per_sec: chuteSpeed,
					chute_max_deg: chuteMax
				})
			});
			if (!response.ok) throw new Error(await readError(response));
			const payload = await response.json();
			active = Boolean(payload.active);
			run = payload.run;
			await loadRuns();
		} catch (error) {
			errorMsg = error instanceof Error ? error.message : String(error);
		} finally {
			busy = false;
		}
	}

	async function stopTest() {
		busy = true;
		errorMsg = null;
		try {
			const response = await fetch(`${backendBase()}/api/power-stress/stop`, {
				method: 'POST'
			});
			if (!response.ok) throw new Error(await readError(response));
			const payload = await response.json();
			active = Boolean(payload.active);
			run = payload.run;
		} catch (error) {
			errorMsg = error instanceof Error ? error.message : String(error);
		} finally {
			busy = false;
		}
	}

	async function downloadRun(runId: string) {
		errorMsg = null;
		try {
			const response = await fetch(`${backendBase()}/api/power-stress/runs/${runId}`);
			if (!response.ok) throw new Error(await readError(response));
			const payload = await response.json();
			const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
			const url = URL.createObjectURL(blob);
			const link = document.createElement('a');
			link.href = url;
			link.download = `power-stress-${runId}.json`;
			link.click();
			URL.revokeObjectURL(url);
		} catch (error) {
			errorMsg = error instanceof Error ? error.message : String(error);
		}
	}

	function formatTime(timestamp: number | null): string {
		return timestamp ? new Date(timestamp * 1000).toLocaleString() : '—';
	}

	function formatDuration(seconds: number): string {
		const minutes = Math.floor(seconds / 60);
		const remainder = Math.round(seconds % 60);
		return `${minutes}m ${remainder}s`;
	}

	onMount(() => {
		void loadStatus();
		void loadRuns();
		pollTimer = setInterval(() => {
			void loadStatus();
			if (!active) void loadRuns();
		}, 1000);
	});

	onDestroy(() => {
		if (pollTimer) clearInterval(pollTimer);
	});
</script>

<svelte:head><title>Sorter - Power Stress Test</title></svelte:head>

<div class="mx-auto flex max-w-4xl flex-col gap-6 p-6">
	<header class="flex flex-col gap-1">
		<h1 class="text-xl font-semibold tracking-wide">Power Stress Test</h1>
		<p class="text-sm text-neutral-400">
			Maximum-load sequence for wall-power measurement. Safe Home and Pause are required.
		</p>
	</header>

	<Alert variant="info">
		The chute homes before motion and stays at or below {chuteMax}°. LEDs remain at 100%, all
		configured vision workers must be live, C1–C4 use ramped motion, and servo channels exercise
		their full 0–180° range. Every phase boundary is stored as an epoch timestamp for correlation
		with the Shelly readings.
	</Alert>

	<SectionCard title="Sequence">
		<div class="grid gap-3 sm:grid-cols-3">
			<div class="border border-neutral-700/50 p-3">
				<div class="font-medium">1. Stable</div>
				<div class="mt-1 text-sm text-neutral-400">
					All four channel steppers run continuously, chute sweeps home-to-max, servos sweep
					min-to-max.
				</div>
			</div>
			<div class="border border-neutral-700/50 p-3">
				<div class="font-medium">2. Random</div>
				<div class="mt-1 text-sm text-neutral-400">
					Steppers brake and burst in either direction, chute uses random targets, servos use random
					full-range targets.
				</div>
			</div>
			<div class="border border-neutral-700/50 p-3">
				<div class="font-medium">3. Mixed</div>
				<div class="mt-1 text-sm text-neutral-400">
					Short segments mix continuous and burst steppers while alternating chute and servo modes.
				</div>
			</div>
		</div>
	</SectionCard>

	<SectionCard title="Parameters">
		<div class="grid gap-4 sm:grid-cols-2">
			<label class="flex flex-col gap-1">
				<span class="text-sm font-medium">Total motion time (minutes)</span>
				<Input type="number" bind:value={durationMinutes} disabled={active} />
			</label>
			<label class="flex flex-col gap-1">
				<span class="text-sm font-medium">C1–C4 maximum speed (µsteps/s)</span>
				<Input type="number" bind:value={stepperSpeed} disabled={active} />
			</label>
			<label class="flex flex-col gap-1">
				<span class="text-sm font-medium">Chute speed (µsteps/s)</span>
				<Input type="number" bind:value={chuteSpeed} disabled={active} />
			</label>
			<label class="flex flex-col gap-1">
				<span class="text-sm font-medium">Chute maximum angle</span>
				<Input type="number" bind:value={chuteMax} disabled={active} />
			</label>
		</div>
		<div class="mt-4 flex gap-3">
			{#if active}
				<Button variant="danger" loading={busy} onclick={stopTest}>Stop safely</Button>
			{:else}
				<Button variant="primary" loading={busy} onclick={startTest}>Start power stress test</Button
				>
			{/if}
		</div>
	</SectionCard>

	{#if errorMsg}
		<Alert variant="danger">{errorMsg}</Alert>
	{/if}

	{#if run}
		<SectionCard title="Current run">
			<div class="flex flex-wrap items-center justify-between gap-3">
				<div>
					<div class="text-lg font-semibold capitalize">{run.status}</div>
					<div class="text-sm text-neutral-400">
						{run.current_phase ?? 'finished'}{run.current_segment
							? ` · segment ${run.current_segment}`
							: ''}
						· {formatDuration(run.total_time_s)} / {formatDuration(run.duration_target_s)}
					</div>
				</div>
				<Button variant="secondary" size="sm" onclick={() => run && downloadRun(run.id)}
					>Download JSON</Button
				>
			</div>
			<div class="mt-4 h-2 overflow-hidden bg-neutral-800">
				<div class="h-full bg-primary transition-all" style={`width: ${progressPercent}%`}></div>
			</div>
			{#if run.hardware}
				<div class="mt-4 grid gap-2 text-sm sm:grid-cols-4">
					<div>
						<span class="text-neutral-400">Steppers</span><br />{run.hardware.steppers.length}
					</div>
					<div><span class="text-neutral-400">Servos</span><br />{run.hardware.servo_count}</div>
					<div>
						<span class="text-neutral-400">LED outputs</span><br />{run.hardware.led_output_count}
					</div>
					<div>
						<span class="text-neutral-400">Vision workers</span><br />{run.hardware
							.perception_workers_alive}
					</div>
				</div>
			{/if}
			{#if run.error}
				<div class="mt-4 text-sm text-red-400">{run.error}</div>
			{/if}
			{#if run.events?.length}
				<div class="mt-5 max-h-72 overflow-auto border border-neutral-700/50">
					{#each [...run.events].reverse() as event (event.id)}
						<div
							class="grid gap-1 border-b border-neutral-700/40 px-3 py-2 text-sm sm:grid-cols-[12rem_10rem_1fr]"
						>
							<span class="text-neutral-400">{formatTime(event.created_at)}</span>
							<span>{event.event_type.replaceAll('_', ' ')}</span>
							<span class="text-neutral-500">{event.phase ?? ''}</span>
						</div>
					{/each}
				</div>
			{/if}
		</SectionCard>
	{/if}

	<SectionCard title="Recorded runs">
		{#if runs.length === 0}
			<div class="text-sm text-neutral-400">No power stress runs recorded yet.</div>
		{:else}
			<div class="overflow-x-auto">
				<table class="w-full text-left text-sm">
					<thead class="text-neutral-400">
						<tr>
							<th class="pr-4 pb-2 font-medium">Started</th>
							<th class="pr-4 pb-2 font-medium">Status</th>
							<th class="pr-4 pb-2 font-medium">Duration</th>
							<th class="pb-2 font-medium"></th>
						</tr>
					</thead>
					<tbody>
						{#each runs as item (item.id)}
							<tr class="border-t border-neutral-700/40">
								<td class="py-2 pr-4">{formatTime(item.started_at)}</td>
								<td class="py-2 pr-4 capitalize">{item.status}</td>
								<td class="py-2 pr-4">{formatDuration(item.total_time_s)}</td>
								<td class="py-2 text-right">
									<Button variant="ghost" size="sm" onclick={() => downloadRun(item.id)}
										>JSON</Button
									>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</SectionCard>
</div>
