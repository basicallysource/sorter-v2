<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import { Alert } from '$lib/components/primitives';
	import SettingRow from '$lib/components/settings/SettingRow.svelte';

	let { channelKey }: { channelKey: string } = $props();

	const CHANNEL_LABELS: Record<string, string> = {
		c_channel_2: 'C-Channel 2',
		c_channel_3: 'C-Channel 3',
		classification_channel: 'Classification C-Channel'
	};
	// Applied while dragging the brightness slider so we don't POST per pixel.
	const BRIGHTNESS_DEBOUNCE_MS = 200;

	type LedOutput = { output_id: string; board_role: string; gpio: number };

	const machine = getMachineContext();

	let outputs = $state<LedOutput[]>([]);
	let assignments = $state<Record<string, string | null>>({});
	let brightness = $state<Record<string, number>>({});
	let loading = $state(true);
	let errorMsg = $state<string | null>(null);
	let debounce: ReturnType<typeof setTimeout> | null = null;

	const assigned = $derived(assignments[channelKey] ?? null);
	const percent = $derived(assigned ? (brightness[assigned] ?? 100) : 0);
	const sharedWith = $derived(
		Object.entries(assignments)
			.filter(([key, output]) => key !== channelKey && assigned !== null && output === assigned)
			.map(([key]) => CHANNEL_LABELS[key] ?? key)
	);

	function currentBackendBaseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? getBackendHttpBase();
	}

	async function request(body: Record<string, unknown> | null) {
		try {
			const res = await fetch(
				`${currentBackendBaseUrl()}/api/leds`,
				body
					? {
							method: 'POST',
							headers: { 'Content-Type': 'application/json' },
							body: JSON.stringify(body)
						}
					: {}
			);
			if (!res.ok) throw new Error(await res.text());
			const payload = await res.json();
			outputs = payload?.outputs ?? [];
			assignments = payload?.assignments ?? {};
			brightness = payload?.brightness ?? {};
			errorMsg = null;
		} catch (e: any) {
			errorMsg = e?.message ?? 'Failed to reach the LED settings.';
		} finally {
			loading = false;
		}
	}

	function save(output: string | null, brightnessPercent: number) {
		void request({ channel: channelKey, output, brightness_percent: brightnessPercent });
	}

	function saveOutput(next: string | null) {
		// Adopt whatever the target pin is already running at, so picking a GPIO a
		// sibling channel is using does not yank its brightness.
		save(next, next ? (brightness[next] ?? 100) : 100);
	}

	function saveBrightness(next: number) {
		if (!assigned) return;
		const clamped = Math.max(0, Math.min(100, Math.round(next)));
		brightness = { ...brightness, [assigned]: clamped };
		if (debounce) clearTimeout(debounce);
		debounce = setTimeout(() => save(assigned, clamped), BRIGHTNESS_DEBOUNCE_MS);
	}

	onMount(() => void request(null));
	onDestroy(() => {
		if (debounce) clearTimeout(debounce);
	});
</script>

<div class="flex flex-col gap-2" class:opacity-50={!loading && outputs.length === 0}>
	{#if errorMsg}
		<Alert variant="danger">{errorMsg}</Alert>
	{:else if !loading && outputs.length === 0}
		<Alert variant="info">No LED outputs are available to assign right now.</Alert>
	{/if}

	<SettingRow
		label="Output"
		description="Which board GPIO drives this channel's light. Several channels may share one GPIO — it is one physical pin."
	>
		<select
			value={assigned ?? ''}
			disabled={loading || outputs.length === 0}
			aria-label="LED output"
			onchange={(e) => saveOutput(e.currentTarget.value || null)}
			class="w-56 border border-border bg-bg px-2 py-1.5 text-sm text-text"
		>
			<option value="">Not assigned</option>
			{#each outputs as output (output.output_id)}
				<option value={output.output_id}>{output.board_role} board — GPIO {output.gpio}</option>
			{/each}
		</select>
	</SettingRow>

	<SettingRow
		label="Brightness"
		description="PWM duty driven onto the assigned GPIO. 0% is off — there is no separate on/off."
	>
		<div class="flex items-center gap-3">
			<input
				type="range"
				min="0"
				max="100"
				step="1"
				value={percent}
				disabled={loading || !assigned}
				aria-label="LED brightness percent"
				oninput={(e) => saveBrightness(Number(e.currentTarget.value))}
				class="w-40"
			/>
			<span class="w-12 shrink-0 text-right text-sm text-text tabular-nums">{percent}%</span>
		</div>
	</SettingRow>

	{#if sharedWith.length > 0}
		<div class="border border-border bg-bg px-3 py-2.5 text-sm text-text-muted">
			Shares this GPIO with <span class="text-text">{sharedWith.join(', ')}</span> — one pin, one
			brightness.
		</div>
	{/if}
</div>
