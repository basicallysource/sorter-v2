<script lang="ts">
	import { onMount } from 'svelte';
	import { Gauge, Play, RefreshCw, Square } from 'lucide-svelte';
	import {
		cancelContinuousMotion,
		fetchContinuousMotionStatus,
		startContinuousMotion,
		type ContinuousMotionChannelKey,
		type ContinuousMotionMode,
		type ContinuousMotionStatus
	} from '$lib/runtime/continuous-motion';

	interface Props {
		baseUrl: string;
		hardwareReady?: boolean;
	}

	let { baseUrl, hardwareReady = false }: Props = $props();

	const CHANNELS: { key: ContinuousMotionChannelKey; label: string }[] = [
		{ key: 'c1', label: 'C1' },
		{ key: 'c2', label: 'C2' },
		{ key: 'c3', label: 'C3' },
		{ key: 'c4', label: 'C4' }
	];

	let mode = $state<ContinuousMotionMode>('factor');
	let baseRpm = $state(0.1);
	let absoluteRpm = $state<Record<ContinuousMotionChannelKey, number>>({
		c1: 0.1,
		c2: 0.2,
		c3: 0.4,
		c4: 0.8
	});
	let factors = $state<Record<ContinuousMotionChannelKey, number>>({
		c1: 1,
		c2: 2,
		c3: 2,
		c4: 2
	});
	let durationMinutes = $state(10);
	let status = $state<ContinuousMotionStatus | null>(null);
	let loading = $state(false);
	let error = $state<string | null>(null);

	const active = $derived(Boolean(status?.active));
	const phaseLabel = $derived(
		status?.phase === 'running'
			? 'Running'
			: status?.phase === 'starting'
				? 'Starting'
				: status?.phase === 'cancelling'
					? 'Stopping'
					: 'Idle'
	);

	function clampRpm(value: number): number {
		if (!Number.isFinite(value)) return 0.1;
		return Math.max(0.01, Math.min(30, value));
	}

	function clampFactor(value: number): number {
		if (!Number.isFinite(value)) return 1;
		return Math.max(0.1, Math.min(16, value));
	}

	function targetRpms(): Record<ContinuousMotionChannelKey, number> {
		if (mode === 'rpm') {
			return {
				c1: clampRpm(absoluteRpm.c1),
				c2: clampRpm(absoluteRpm.c2),
				c3: clampRpm(absoluteRpm.c3),
				c4: clampRpm(absoluteRpm.c4)
			};
		}
		const c1 = clampRpm(baseRpm);
		const c2 = clampRpm(c1 * clampFactor(factors.c2));
		const c3 = clampRpm(c2 * clampFactor(factors.c3));
		const c4 = clampRpm(c3 * clampFactor(factors.c4));
		return { c1, c2, c3, c4 };
	}

	function channelStatus(key: ContinuousMotionChannelKey) {
		return status?.channels?.[key] ?? null;
	}

	function displayedRpm(key: ContinuousMotionChannelKey): number {
		const live = channelStatus(key)?.target_rpm;
		return typeof live === 'number' && Number.isFinite(live) ? live : targetRpms()[key];
	}

	function stepCount(key: ContinuousMotionChannelKey): number {
		const value = channelStatus(key)?.step_count;
		return typeof value === 'number' && Number.isFinite(value) ? value : 0;
	}

	function modeButtonClass(id: ContinuousMotionMode): string {
		const base = 'flex-1 border px-2 py-1 text-xs font-medium transition-colors';
		return mode === id
			? `${base} border-primary bg-primary/10 text-primary`
			: `${base} border-border bg-bg text-text-muted hover:text-text`;
	}

	async function refreshStatus() {
		try {
			const next = await fetchContinuousMotionStatus(baseUrl);
			if (next) status = next;
		} catch {
			// dashboard polling should stay quiet on transient disconnects
		}
	}

	async function toggle() {
		loading = true;
		error = null;
		try {
			if (active) {
				status = await cancelContinuousMotion(baseUrl);
			} else {
				status = await startContinuousMotion(baseUrl, {
					channel_rpm: targetRpms(),
					duration_s: Math.max(1, durationMinutes) * 60,
					poll_s: 0.02
				});
			}
		} catch (e) {
			error = e instanceof Error ? e.message : 'Continuous motion failed.';
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		void refreshStatus();
	});

	onMount(() => {
		void refreshStatus();
		const interval = setInterval(() => void refreshStatus(), 1000);
		return () => clearInterval(interval);
	});
</script>

<section class="flex shrink-0 flex-col border border-border bg-surface">
	<div class="setup-card-header flex items-center justify-between gap-3 px-3 py-2 text-sm">
		<div class="flex min-w-0 items-center gap-2 font-medium text-text">
			<Gauge size={16} class="text-text-muted" />
			<span>Continuous Motion</span>
			<span
				class="border border-border bg-bg px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-text-muted"
			>
				{phaseLabel}
			</span>
		</div>
		<button
			type="button"
			onclick={() => void toggle()}
			disabled={loading || (!active && !hardwareReady)}
			title={active ? 'Stop continuous motion' : 'Start continuous motion'}
			class="inline-flex h-8 w-8 items-center justify-center border border-border bg-bg text-text transition-colors hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
		>
			{#if loading}
				<RefreshCw size={15} class="animate-spin" />
			{:else if active}
				<Square size={15} />
			{:else}
				<Play size={15} />
			{/if}
		</button>
	</div>

	<div class="flex flex-col gap-3 px-3 py-3">
		<div class="flex gap-1">
			<button type="button" class={modeButtonClass('factor')} onclick={() => (mode = 'factor')}>
				Factor
			</button>
			<button type="button" class={modeButtonClass('rpm')} onclick={() => (mode = 'rpm')}>
				RPM
			</button>
		</div>

		{#if mode === 'factor'}
			<div class="grid grid-cols-[64px_1fr] items-center gap-2 text-xs">
				<label class="text-text-muted" for="continuous-base-rpm">C1 rpm</label>
				<input
					id="continuous-base-rpm"
					type="number"
					min="0.01"
					max="30"
					step="0.01"
					bind:value={baseRpm}
					class="w-full border border-border bg-bg px-2 py-1 text-sm text-text"
				/>
				{#each CHANNELS.slice(1) as channel (channel.key)}
					<label class="text-text-muted" for={`continuous-factor-${channel.key}`}>
						{channel.label}
					</label>
					<input
						id={`continuous-factor-${channel.key}`}
						type="number"
						min="0.1"
						max="16"
						step="0.1"
						bind:value={factors[channel.key]}
						class="w-full border border-border bg-bg px-2 py-1 text-sm text-text"
					/>
				{/each}
			</div>
		{:else}
			<div class="grid grid-cols-[64px_1fr] items-center gap-2 text-xs">
				{#each CHANNELS as channel (channel.key)}
					<label class="text-text-muted" for={`continuous-rpm-${channel.key}`}>
						{channel.label}
					</label>
					<input
						id={`continuous-rpm-${channel.key}`}
						type="number"
						min="0.01"
						max="30"
						step="0.01"
						bind:value={absoluteRpm[channel.key]}
						class="w-full border border-border bg-bg px-2 py-1 text-sm text-text"
					/>
				{/each}
			</div>
		{/if}

		<div class="grid grid-cols-[64px_1fr] items-center gap-2 text-xs">
			<label class="text-text-muted" for="continuous-duration">Minutes</label>
			<input
				id="continuous-duration"
				type="number"
				min="1"
				max="60"
				step="1"
				bind:value={durationMinutes}
				class="w-full border border-border bg-bg px-2 py-1 text-sm text-text"
			/>
		</div>

		<div class="grid grid-cols-4 gap-1 border-t border-border pt-2">
			{#each CHANNELS as channel (channel.key)}
				<div class="min-w-0 text-center">
					<div class="text-[10px] font-semibold uppercase tracking-wider text-text-muted">
						{channel.label}
					</div>
					<div class="mt-0.5 font-mono text-sm text-text">
						{displayedRpm(channel.key).toFixed(2)}
					</div>
					<div class="font-mono text-[10px] text-text-muted">{stepCount(channel.key)}</div>
				</div>
			{/each}
		</div>

		{#if error}
			<div class="border border-danger/25 bg-danger/[0.06] px-2 py-1.5 text-xs text-danger">
				{error}
			</div>
		{/if}
	</div>
</section>
