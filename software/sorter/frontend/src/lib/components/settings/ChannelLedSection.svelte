<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Field from '$lib/components/ui/Field.svelte';
	import Select from '$lib/components/ui/Select.svelte';

	let { channelKey }: { channelKey: string } = $props();

	// A SettingRow's label and control share a line, which squeezes the label
	// out of a 20rem sidebar; these fields stack instead.
	const outputId = $derived(`led-output-${channelKey}`);
	const brightnessId = $derived(`led-brightness-${channelKey}`);

	const CHANNEL_LABELS: Record<string, string> = {
		c_channel_2: 'C-channel 2',
		c_channel_3: 'C-channel 3',
		classification_channel: 'Classification C-channel'
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

<div class="flex flex-col gap-4" class:opacity-50={!loading && outputs.length === 0}>
	{#if errorMsg}
		<Alert tone="danger">{errorMsg}</Alert>
	{:else if !loading && outputs.length === 0}
		<Alert tone="info">No LED outputs are free to assign right now.</Alert>
	{/if}
	<Field
		label="Output"
		for={outputId}
		help="The board GPIO that drives this channel's light. Channels can share one GPIO; it is one physical pin."
	>
		<Select
			id={outputId}
			value={assigned ?? ''}
			disabled={loading || outputs.length === 0}
			options={[
				{ value: '', label: 'Not assigned' },
				...outputs.map((output) => ({
					value: output.output_id,
					label: `${output.board_role} board, GPIO ${output.gpio}`
				}))
			]}
			onchange={(id) => saveOutput(id || null)}
		/>
	</Field>
	<Field
		label="Brightness"
		for={brightnessId}
		help="The PWM duty on the assigned GPIO. 0% is off; there is no separate switch."
	>
		<div class="flex items-center gap-3">
			<input
				id={brightnessId}
				type="range"
				min="0"
				max="100"
				step="1"
				value={percent}
				disabled={loading || !assigned}
				oninput={(e) => saveBrightness(Number(e.currentTarget.value))}
				class="min-w-0 flex-1 accent-primary"
			/>
			<span class="num w-10 shrink-0 text-right text-sm text-ink">{percent}%</span>
		</div>
	</Field>
	{#if sharedWith.length > 0}
		<p class="text-sm text-ink-muted">
			Shares its GPIO with <span class="text-ink">{sharedWith.join(', ')}</span>: one pin, one
			brightness.
		</p>
	{/if}
</div>
