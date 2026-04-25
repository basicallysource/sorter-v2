<script lang="ts">
	import { onMount } from 'svelte';
	import { Check, RefreshCw, SlidersHorizontal } from 'lucide-svelte';
	import {
		fetchRuntimeTuning,
		updateRuntimeTuning,
		type RuntimeTuning,
		type RuntimeTuningPatch
	} from '$lib/runtime/tuning';

	interface Props {
		baseUrl: string;
	}

	let { baseUrl }: Props = $props();

	let tuning = $state<RuntimeTuning>({});
	let loading = $state(false);
	let saving = $state(false);
	let error = $state<string | null>(null);
	let savedAt = $state<number | null>(null);
	let pendingPatch: RuntimeTuningPatch = {};
	let timer: ReturnType<typeof setTimeout> | null = null;

	const c2 = $derived(tuning.channels?.c2 ?? {});
	const c3 = $derived(tuning.channels?.c3 ?? {});
	const c4 = $derived(tuning.channels?.c4 ?? {});
	const slots = $derived(tuning.slots ?? {});
	const savedRecently = $derived(savedAt !== null && Date.now() - savedAt < 2500);

	function numberValue(value: unknown, fallback: number): number {
		return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
	}

	function boolValue(value: unknown, fallback: boolean): boolean {
		return typeof value === 'boolean' ? value : fallback;
	}

	function msValue(seconds: unknown, fallbackMs: number): number {
		return numberValue(seconds, fallbackMs / 1000) * 1000;
	}

	function inputNumber(event: Event): number {
		const target = event.currentTarget as HTMLInputElement;
		return Number(target.value);
	}

	function inputChecked(event: Event): boolean {
		const target = event.currentTarget as HTMLInputElement;
		return target.checked;
	}

	function mergePatch(base: RuntimeTuningPatch, next: RuntimeTuningPatch): RuntimeTuningPatch {
		const merged: RuntimeTuningPatch = {
			channels: { ...(base.channels ?? {}) },
			slots: { ...(base.slots ?? {}) }
		};
		for (const [channel, values] of Object.entries(next.channels ?? {})) {
			merged.channels![channel] = { ...(merged.channels![channel] ?? {}), ...values };
		}
		for (const [slot, value] of Object.entries(next.slots ?? {})) {
			merged.slots![slot] = value;
		}
		if (Object.keys(merged.channels ?? {}).length === 0) delete merged.channels;
		if (Object.keys(merged.slots ?? {}).length === 0) delete merged.slots;
		return merged;
	}

	function mergeLocal(next: RuntimeTuningPatch) {
		tuning = {
			...tuning,
			channels: {
				...(tuning.channels ?? {}),
				...Object.fromEntries(
					Object.entries(next.channels ?? {}).map(([channel, values]) => [
						channel,
						{ ...(tuning.channels?.[channel] ?? {}), ...values }
					])
				)
			},
			slots: { ...(tuning.slots ?? {}), ...(next.slots ?? {}) }
		};
	}

	function queuePatch(next: RuntimeTuningPatch) {
		pendingPatch = mergePatch(pendingPatch, next);
		mergeLocal(next);
		if (timer) clearTimeout(timer);
		timer = setTimeout(() => {
			timer = null;
			void flushPatch();
		}, 300);
	}

	async function flushPatch() {
		const patch = pendingPatch;
		pendingPatch = {};
		if (!patch.channels && !patch.slots) return;
		saving = true;
		error = null;
		try {
			tuning = await updateRuntimeTuning(baseUrl, patch);
			savedAt = Date.now();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Runtime tuning failed.';
			await refresh();
		} finally {
			saving = false;
		}
	}

	async function refresh() {
		loading = true;
		error = null;
		try {
			tuning = await fetchRuntimeTuning(baseUrl);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Runtime tuning unavailable.';
		} finally {
			loading = false;
		}
	}

	function updateChannel(channel: 'c2' | 'c3' | 'c4', values: Record<string, unknown>) {
		queuePatch({ channels: { [channel]: values } });
	}

	function updateRotor(
		channel: 'c2' | 'c3' | 'c4',
		group: 'normal' | 'precision' | 'eject',
		values: Record<string, unknown>
	) {
		queuePatch({ channels: { [channel]: { [group]: values } } });
	}

	function updateSlot(slot: string, value: number) {
		queuePatch({ slots: { [slot]: Math.round(value) } });
	}

	onMount(() => {
		void refresh();
		const interval = setInterval(() => {
			if (!saving && !timer) void refresh();
		}, 3000);
		return () => {
			if (timer) clearTimeout(timer);
			clearInterval(interval);
		};
	});
</script>

<div class="flex max-h-[52vh] flex-col gap-3 overflow-y-auto px-3 py-3">
	<div class="flex items-center justify-between gap-2">
		<div class="flex min-w-0 items-center gap-2 text-xs font-medium uppercase text-text-muted">
			<SlidersHorizontal size={14} />
			<span>Live</span>
			{#if saving}
				<span class="font-normal normal-case text-text-muted">Saving</span>
			{:else if savedRecently}
				<span class="inline-flex items-center gap-1 font-normal normal-case text-success">
					<Check size={13} /> Saved
				</span>
			{/if}
		</div>
		<button
			type="button"
			onclick={() => void refresh()}
			disabled={loading}
			title="Refresh runtime tuning"
			class="inline-flex h-7 w-7 items-center justify-center border border-border bg-bg text-text transition-colors hover:bg-white disabled:opacity-50"
		>
			<RefreshCw size={14} class={loading ? 'animate-spin' : ''} />
		</button>
	</div>

	<div class="border-t border-border pt-3">
		<div class="mb-2 text-xs font-semibold uppercase text-text-muted">C4 Motion</div>
		<div class="grid grid-cols-[92px_minmax(0,1fr)_76px] items-center gap-2 text-xs">
			<label for="tune-c4-accel" class="text-text-muted">Accel</label>
			<input
				id="tune-c4-accel"
				type="range"
				min="20000"
				max="200000"
				step="5000"
				value={numberValue(c4.transport_acceleration_usteps_per_s2, 80000)}
				oninput={(e) =>
					updateChannel('c4', { transport_acceleration_usteps_per_s2: inputNumber(e) })}
			/>
			<input
				type="number"
				min="20000"
				max="200000"
				step="5000"
				value={numberValue(c4.transport_acceleration_usteps_per_s2, 80000)}
				onchange={(e) =>
					updateChannel('c4', { transport_acceleration_usteps_per_s2: inputNumber(e) })}
				class="w-full border border-border bg-bg px-1.5 py-1 text-right font-mono text-xs text-text"
			/>

			<label for="tune-c4-scale" class="text-text-muted">Scale</label>
			<input
				id="tune-c4-scale"
				type="range"
				min="1"
				max="24"
				step="0.5"
				value={numberValue(c4.transport_speed_scale, 8)}
				oninput={(e) => updateChannel('c4', { transport_speed_scale: inputNumber(e) })}
			/>
			<input
				type="number"
				min="1"
				max="24"
				step="0.5"
				value={numberValue(c4.transport_speed_scale, 8)}
				onchange={(e) => updateChannel('c4', { transport_speed_scale: inputNumber(e) })}
				class="w-full border border-border bg-bg px-1.5 py-1 text-right font-mono text-xs text-text"
			/>

			<label for="tune-c4-gear" class="text-text-muted">Gear</label>
			<input
				id="tune-c4-gear"
				type="range"
				min="1"
				max="80"
				step="1"
				value={numberValue(c4.stepper_degrees_per_tray_degree, 36)}
				oninput={(e) =>
					updateChannel('c4', { stepper_degrees_per_tray_degree: inputNumber(e) })}
			/>
			<input
				type="number"
				min="1"
				max="80"
				step="1"
				value={numberValue(c4.stepper_degrees_per_tray_degree, 36)}
				onchange={(e) =>
					updateChannel('c4', { stepper_degrees_per_tray_degree: inputNumber(e) })}
				class="w-full border border-border bg-bg px-1.5 py-1 text-right font-mono text-xs text-text"
			/>

			<label for="tune-c4-step" class="text-text-muted">Step</label>
			<input
				id="tune-c4-step"
				type="range"
				min="1"
				max="24"
				step="0.5"
				value={numberValue(c4.transport_step_deg, 6)}
				oninput={(e) => updateChannel('c4', { transport_step_deg: inputNumber(e) })}
			/>
			<input
				type="number"
				min="1"
				max="24"
				step="0.5"
				value={numberValue(c4.transport_step_deg, 6)}
				onchange={(e) => updateChannel('c4', { transport_step_deg: inputNumber(e) })}
				class="w-full border border-border bg-bg px-1.5 py-1 text-right font-mono text-xs text-text"
			/>

			<label for="tune-c4-max-step" class="text-text-muted">Max Step</label>
			<input
				id="tune-c4-max-step"
				type="range"
				min="1"
				max="36"
				step="0.5"
				value={numberValue(c4.transport_max_step_deg, 18)}
				oninput={(e) => updateChannel('c4', { transport_max_step_deg: inputNumber(e) })}
			/>
			<input
				type="number"
				min="1"
				max="36"
				step="0.5"
				value={numberValue(c4.transport_max_step_deg, 18)}
				onchange={(e) => updateChannel('c4', { transport_max_step_deg: inputNumber(e) })}
				class="w-full border border-border bg-bg px-1.5 py-1 text-right font-mono text-xs text-text"
			/>

			<label for="tune-c4-cooldown" class="text-text-muted">Cooldown</label>
			<input
				id="tune-c4-cooldown"
				type="range"
				min="20"
				max="500"
				step="10"
				value={msValue(c4.transport_cooldown_s, 80)}
				oninput={(e) => updateChannel('c4', { transport_cooldown_ms: inputNumber(e) })}
			/>
			<input
				type="number"
				min="20"
				max="500"
				step="10"
				value={msValue(c4.transport_cooldown_s, 80)}
				onchange={(e) => updateChannel('c4', { transport_cooldown_ms: inputNumber(e) })}
				class="w-full border border-border bg-bg px-1.5 py-1 text-right font-mono text-xs text-text"
			/>
		</div>
	</div>

	<div class="border-t border-border pt-3">
		<div class="mb-2 text-xs font-semibold uppercase text-text-muted">C4 Flow</div>
		<div class="grid grid-cols-[92px_minmax(0,1fr)_76px] items-center gap-2 text-xs">
			<label for="tune-c4-zones" class="text-text-muted">Zones</label>
			<input
				id="tune-c4-zones"
				type="range"
				min="1"
				max="8"
				step="1"
				value={numberValue(c4.max_zones, 4)}
				oninput={(e) => updateChannel('c4', { max_zones: inputNumber(e) })}
			/>
			<input
				type="number"
				min="1"
				max="8"
				step="1"
				value={numberValue(c4.max_zones, 4)}
				onchange={(e) => updateChannel('c4', { max_zones: inputNumber(e) })}
				class="w-full border border-border bg-bg px-1.5 py-1 text-right font-mono text-xs text-text"
			/>

			<label for="tune-c4-rpm" class="text-text-muted">Target rpm</label>
			<input
				id="tune-c4-rpm"
				type="range"
				min="0"
				max="4"
				step="0.1"
				value={numberValue(c4.transport_target_rpm, 1.2)}
				oninput={(e) => updateChannel('c4', { transport_target_rpm: inputNumber(e) })}
			/>
			<input
				type="number"
				min="0"
				max="4"
				step="0.1"
				value={numberValue(c4.transport_target_rpm, 1.2)}
				onchange={(e) => updateChannel('c4', { transport_target_rpm: inputNumber(e) })}
				class="w-full border border-border bg-bg px-1.5 py-1 text-right font-mono text-xs text-text"
			/>

			<label for="tune-c4-unjam" class="text-text-muted">Unjam</label>
			<input
				id="tune-c4-unjam"
				type="range"
				min="500"
				max="8000"
				step="100"
				value={msValue(c4.unjam_stall_s, 2500)}
				oninput={(e) => updateChannel('c4', { unjam_stall_ms: inputNumber(e) })}
			/>
			<input
				type="number"
				min="500"
				max="8000"
				step="100"
				value={msValue(c4.unjam_stall_s, 2500)}
				onchange={(e) => updateChannel('c4', { unjam_stall_ms: inputNumber(e) })}
				class="w-full border border-border bg-bg px-1.5 py-1 text-right font-mono text-xs text-text"
			/>

			<label class="text-text-muted" for="tune-c4-idle">Idle Jog</label>
			<input
				id="tune-c4-idle"
				type="checkbox"
				checked={boolValue(c4.idle_jog_enabled, true)}
				onchange={(e) => updateChannel('c4', { idle_jog_enabled: inputChecked(e) })}
				class="h-4 w-4"
			/>
			<div></div>
		</div>
	</div>

	<div class="border-t border-border pt-3">
		<div class="mb-2 text-xs font-semibold uppercase text-text-muted">C3 / C2</div>
		<div class="grid grid-cols-[92px_minmax(0,1fr)_76px] items-center gap-2 text-xs">
			<label for="tune-c3-max" class="text-text-muted">C3 Max</label>
			<input
				id="tune-c3-max"
				type="range"
				min="1"
				max="8"
				step="1"
				value={numberValue(c3.max_piece_count, 3)}
				oninput={(e) => updateChannel('c3', { max_piece_count: inputNumber(e) })}
			/>
			<input
				type="number"
				min="1"
				max="8"
				step="1"
				value={numberValue(c3.max_piece_count, 3)}
				onchange={(e) => updateChannel('c3', { max_piece_count: inputNumber(e) })}
				class="w-full border border-border bg-bg px-1.5 py-1 text-right font-mono text-xs text-text"
			/>

			<label for="tune-c3-speed" class="text-text-muted">C3 Speed</label>
			<input
				id="tune-c3-speed"
				type="range"
				min="1000"
				max="16000"
				step="500"
				value={numberValue(c3.normal?.microsteps_per_second, 12000)}
				oninput={(e) =>
					updateRotor('c3', 'normal', { microsteps_per_second: inputNumber(e) })}
			/>
			<input
				type="number"
				min="1000"
				max="16000"
				step="500"
				value={numberValue(c3.normal?.microsteps_per_second, 12000)}
				onchange={(e) =>
					updateRotor('c3', 'normal', { microsteps_per_second: inputNumber(e) })}
				class="w-full border border-border bg-bg px-1.5 py-1 text-right font-mono text-xs text-text"
			/>

			<label for="tune-c3-cooldown" class="text-text-muted">C3 Cool</label>
			<input
				id="tune-c3-cooldown"
				type="range"
				min="40"
				max="1000"
				step="20"
				value={msValue(c3.pulse_cooldown_s, 120)}
				oninput={(e) => updateChannel('c3', { pulse_cooldown_ms: inputNumber(e) })}
			/>
			<input
				type="number"
				min="40"
				max="1000"
				step="20"
				value={msValue(c3.pulse_cooldown_s, 120)}
				onchange={(e) => updateChannel('c3', { pulse_cooldown_ms: inputNumber(e) })}
				class="w-full border border-border bg-bg px-1.5 py-1 text-right font-mono text-xs text-text"
			/>

			<label for="tune-c2-max" class="text-text-muted">C2 Max</label>
			<input
				id="tune-c2-max"
				type="range"
				min="1"
				max="12"
				step="1"
				value={numberValue(c2.max_piece_count, 5)}
				oninput={(e) => updateChannel('c2', { max_piece_count: inputNumber(e) })}
			/>
			<input
				type="number"
				min="1"
				max="12"
				step="1"
				value={numberValue(c2.max_piece_count, 5)}
				onchange={(e) => updateChannel('c2', { max_piece_count: inputNumber(e) })}
				class="w-full border border-border bg-bg px-1.5 py-1 text-right font-mono text-xs text-text"
			/>

			<label for="tune-c2-cooldown" class="text-text-muted">C2 Cool</label>
			<input
				id="tune-c2-cooldown"
				type="range"
				min="40"
				max="1500"
				step="20"
				value={msValue(c2.pulse_cooldown_s, 120)}
				oninput={(e) => updateChannel('c2', { pulse_cooldown_ms: inputNumber(e) })}
			/>
			<input
				type="number"
				min="40"
				max="1500"
				step="20"
				value={msValue(c2.pulse_cooldown_s, 120)}
				onchange={(e) => updateChannel('c2', { pulse_cooldown_ms: inputNumber(e) })}
				class="w-full border border-border bg-bg px-1.5 py-1 text-right font-mono text-xs text-text"
			/>
		</div>
	</div>

	<div class="border-t border-border pt-3">
		<div class="mb-2 text-xs font-semibold uppercase text-text-muted">Slots</div>
		<div class="grid grid-cols-[92px_minmax(0,1fr)_76px] items-center gap-2 text-xs">
			<label for="tune-slot-c3-c4" class="text-text-muted">C3->C4</label>
			<input
				id="tune-slot-c3-c4"
				type="range"
				min="0"
				max="8"
				step="1"
				value={numberValue(slots.c3_to_c4, 4)}
				oninput={(e) => updateSlot('c3_to_c4', inputNumber(e))}
			/>
			<input
				type="number"
				min="0"
				max="8"
				step="1"
				value={numberValue(slots.c3_to_c4, 4)}
				onchange={(e) => updateSlot('c3_to_c4', inputNumber(e))}
				class="w-full border border-border bg-bg px-1.5 py-1 text-right font-mono text-xs text-text"
			/>
		</div>
	</div>

	{#if error}
		<div class="border border-danger/25 bg-danger/[0.06] px-2 py-1.5 text-xs text-danger">
			{error}
		</div>
	{/if}
</div>
