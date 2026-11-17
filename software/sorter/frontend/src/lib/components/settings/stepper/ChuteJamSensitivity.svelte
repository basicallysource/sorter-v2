<!--
	The chute's jam detection: one dial for how hard the chute may push on
	something in its way (a piece jammed in a full bin) before it stops. The
	StallGuard tuner (stallguard_tuner.py) turns it into the driver's trigger
	and speed floor from what the chute reads in normal running, and keeps
	them set as that changes.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Disclosure from '$lib/components/ui/Disclosure.svelte';
	import KeyValue from '$lib/components/ui/KeyValue.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import SettingRow from '$lib/components/ui/SettingRow.svelte';
	import type { AutoTuning } from '$lib/settings/stallguard';

	let { base }: { base: string } = $props();

	const POLL_MS = 4000;
	const START_AT = 50;
	const MIN = 10;
	const MAX = 90;

	let tuning = $state<AutoTuning | null>(null);
	let dial = $state(START_AT);
	let held = $state(false);
	let saving = $state(false);
	let error = $state<string | null>(null);

	async function readError(res: Response): Promise<string> {
		const body = await res.json().catch(() => ({}));
		return typeof body?.detail === 'string' ? body.detail : `HTTP ${res.status}`;
	}

	function take(next: AutoTuning) {
		tuning = next;
		if (!held && (next.sensitivity ?? 0) > 0) dial = next.sensitivity ?? START_AT;
	}

	async function load() {
		try {
			const res = await fetch(`${base}/stepper/chute/stallguard-auto`);
			if (!res.ok) throw new Error(await readError(res));
			take(await res.json());
			error = null;
		} catch (e: any) {
			error = e.message ?? 'The jam detection did not load';
		}
	}

	async function send(sensitivity: number) {
		saving = true;
		error = null;
		try {
			const res = await fetch(`${base}/stepper/chute/stallguard-auto`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ sensitivity })
			});
			if (!res.ok) throw new Error(await readError(res));
			take(await res.json());
		} catch (e: any) {
			error = e.message ?? 'The jam detection did not change';
		} finally {
			saving = false;
			held = false;
		}
	}

	onMount(() => {
		void load();
		const timer = setInterval(load, POLL_MS);
		return () => clearInterval(timer);
	});

	const sensitivity = $derived(tuning?.sensitivity ?? 0);
	const on = $derived(sensitivity > 0 && !!tuning?.auto && !!tuning?.running);
	const byHand = $derived(sensitivity > 0 && !tuning?.auto);
	const jam = $derived(on ? (tuning?.jam ?? null) : null);
	const speed = (value: number) => `${value.toLocaleString()} µsteps/s`;
	const facts = $derived.by(() => {
		if (!jam) return [];
		const items = [
			{ label: 'Stops at', value: `${jam.trigger} or lower` },
			{ label: 'Normal running', value: `${jam.lowest} or higher` },
			{
				label: 'Checks',
				value:
					jam.checked_travel != null
						? `above ${speed(jam.floor_speed)}, ${Math.round(jam.checked_travel * 100)}% of its travel`
						: `above ${speed(jam.floor_speed)}`
			}
		];
		const own = (tuning?.bands ?? []).reduce((sum, band) => sum + band.readings, 0);
		const recorded = (tuning?.bands ?? []).reduce((sum, band) => sum + band.recorded, 0);
		items.push({
			label: 'Learned from',
			value: `${own.toLocaleString()} readings of its own, ${recorded.toLocaleString()} from earlier sorting`
		});
		return items;
	});
</script>

{#if tuning?.supported}
	<Panel
		title="Jam detection"
		description="How hard the chute may push on something in its way, like a piece stuck in a full bin, before it stops."
		flush
	>
		{#snippet actions()}
			{#if byHand}
				<Badge>Set by hand</Badge>
			{:else if !on}
				<Badge>Off</Badge>
			{:else if jam}
				<Badge tone="success">On</Badge>
			{:else}
				<Badge tone="primary">Learning</Badge>
			{/if}
		{/snippet}
		<div class="divide-y divide-line border-t border-line">
			<SettingRow
				label="Sensitivity"
				for="chute-jam-sensitivity"
				help="It stops when its load reading falls to this share of normal running. Higher stops on a lighter push; too high stops on normal running."
			>
				<div class="flex items-center gap-3">
					<input
						id="chute-jam-sensitivity"
						type="range"
						min={MIN}
						max={MAX}
						step="5"
						bind:value={dial}
						disabled={saving || !tuning.running}
						oninput={() => (held = true)}
						onchange={() => on && send(dial)}
						aria-label="Sensitivity"
						class="w-40 accent-primary"
					/>
					<span class="w-10 text-right text-sm tabular-nums text-ink">{dial}%</span>
				</div>
			</SettingRow>
			{#if error || !tuning.running || byHand || (on && tuning.error)}
				<div class="flex flex-col gap-3 px-(--pad-panel) py-(--pad-row)">
					{#if error}<Alert tone="danger">{error}</Alert>{/if}
					{#if !tuning.running}
						<Alert tone="info">Not running: StallGuard is off on this machine.</Alert>
					{/if}
					{#if byHand}
						<Alert tone="info">
							A threshold set by hand on the StallGuard page holds now. Turn this on to use the dial again.
						</Alert>
					{/if}
					{#if on && tuning.error}<Alert tone="danger">{tuning.error}</Alert>{/if}
				</div>
			{/if}
			{#if facts.length > 0}
				<div class="px-(--pad-panel) py-1">
					<KeyValue items={facts} />
				</div>
			{/if}
			{#if on && (tuning.bands ?? []).length > 0}
				<Disclosure title="By speed" help="What normal running reads at each speed">
					<div class="px-(--pad-panel)">
						<KeyValue
							items={(tuning.bands ?? []).map((band) => ({
								label:
									band.to_speed == null
										? `Above ${speed(band.from_speed)}`
										: `${band.from_speed.toLocaleString()} to ${speed(band.to_speed)}`,
								value: `${band.normal_low ?? 'not enough readings'}${band.checked ? ', checked' : ''}`
							}))}
						/>
					</div>
				</Disclosure>
			{/if}
		</div>
		{#snippet footer()}
			{#if on}
				<Button variant="ghost" loading={saving} onclick={() => send(0)}>Turn off</Button>
			{:else}
				<Button loading={saving} disabled={!tuning.running} onclick={() => send(dial)}>Turn on</Button>
			{/if}
		{/snippet}
	</Panel>
{/if}
