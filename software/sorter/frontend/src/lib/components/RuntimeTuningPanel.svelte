<script lang="ts">
	import { onMount } from 'svelte';
	import { Check, CircleQuestionMark, RefreshCw, SlidersHorizontal } from 'lucide-svelte';
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

	const c1 = $derived(tuning.channels?.c1 ?? {});
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

	function updateChannel(channel: 'c1' | 'c2' | 'c3' | 'c4', values: Record<string, unknown>) {
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

{#snippet tuningLabel(forId: string, label: string, help: string)}
	<span class="group relative inline-flex min-h-10 items-center gap-1.5 text-text-muted">
		<label for={forId}>{label}</label>
		<button
			type="button"
			aria-label={`${label}: ${help}`}
			aria-describedby={`${forId}-tooltip`}
			class="inline-flex h-6 w-6 shrink-0 items-center justify-center text-text-muted outline-none transition-[color] hover:text-text focus:text-text"
		>
			<CircleQuestionMark
				size={12}
				class="opacity-55 transition-[opacity] group-hover:opacity-90 group-focus-within:opacity-90"
				aria-hidden="true"
			/>
		</button>
		<span
			id={`${forId}-tooltip`}
			class="pointer-events-none invisible absolute left-0 top-full z-50 mt-1 w-64 max-w-[min(16rem,calc(100vw-2rem))] translate-y-1 border border-border bg-surface px-2.5 py-2 text-left text-[11px] font-normal leading-snug text-text opacity-0 shadow-lg transition-[opacity,transform,visibility] duration-150 group-hover:visible group-hover:translate-y-0 group-hover:opacity-100 group-focus-within:visible group-focus-within:translate-y-0 group-focus-within:opacity-100 motion-reduce:transition-none"
			role="tooltip"
		>
			{help}
		</span>
	</span>
{/snippet}

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
			{@render tuningLabel(
				'tune-c4-accel',
				'Accel',
				'Stepper ramp for normal C4 transport moves. Lower values start and stop softer; higher values react harder and can sound aggressive.'
			)}
			<input
				id="tune-c4-accel"
				type="range"
				min="1000"
				max="60000"
				step="1000"
				value={numberValue(c4.transport_acceleration_usteps_per_s2, 4000)}
				oninput={(e) =>
					updateChannel('c4', { transport_acceleration_usteps_per_s2: inputNumber(e) })}
			/>
			<input
				type="number"
				min="1000"
				max="60000"
				step="1000"
				value={numberValue(c4.transport_acceleration_usteps_per_s2, 4000)}
				onchange={(e) =>
					updateChannel('c4', { transport_acceleration_usteps_per_s2: inputNumber(e) })}
				class="w-full border border-border bg-bg px-1.5 py-1 text-right font-mono text-xs text-text"
			/>

			{@render tuningLabel(
				'tune-c4-scale',
				'Scale',
				'Multiplier for C4 carousel transport speed. Lower slows the tray down globally; higher increases throughput but also mechanical stress.'
			)}
			<input
				id="tune-c4-scale"
				type="range"
				min="0.5"
				max="12"
				step="0.5"
				value={numberValue(c4.transport_speed_scale, 4)}
				oninput={(e) => updateChannel('c4', { transport_speed_scale: inputNumber(e) })}
			/>
			<input
				type="number"
				min="0.5"
				max="12"
				step="0.5"
				value={numberValue(c4.transport_speed_scale, 4)}
				onchange={(e) => updateChannel('c4', { transport_speed_scale: inputNumber(e) })}
				class="w-full border border-border bg-bg px-1.5 py-1 text-right font-mono text-xs text-text"
			/>

			{@render tuningLabel(
				'tune-c4-step',
				'Step',
				'Nominal tray degrees per C4 transport pulse. Smaller steps move parts more gently; larger steps clear space faster.'
			)}
			<input
				id="tune-c4-step"
				type="range"
				min="1"
				max="24"
				step="0.5"
				value={numberValue(c4.transport_step_deg, 3)}
				oninput={(e) => updateChannel('c4', { transport_step_deg: inputNumber(e) })}
			/>
			<input
				type="number"
				min="1"
				max="24"
				step="0.5"
				value={numberValue(c4.transport_step_deg, 3)}
				onchange={(e) => updateChannel('c4', { transport_step_deg: inputNumber(e) })}
				class="w-full border border-border bg-bg px-1.5 py-1 text-right font-mono text-xs text-text"
			/>

			{@render tuningLabel(
				'tune-c4-max-step',
				'Max Step',
				'Upper limit for one C4 transport move when runtime asks for more motion. Caps sudden jumps and keeps recovery moves bounded.'
			)}
			<input
				id="tune-c4-max-step"
				type="range"
				min="1"
				max="36"
				step="0.5"
				value={numberValue(c4.transport_max_step_deg, 8)}
				oninput={(e) => updateChannel('c4', { transport_max_step_deg: inputNumber(e) })}
			/>
			<input
				type="number"
				min="1"
				max="36"
				step="0.5"
				value={numberValue(c4.transport_max_step_deg, 8)}
				onchange={(e) => updateChannel('c4', { transport_max_step_deg: inputNumber(e) })}
				class="w-full border border-border bg-bg px-1.5 py-1 text-right font-mono text-xs text-text"
			/>

			{@render tuningLabel(
				'tune-c4-cooldown',
				'Cooldown',
				'Minimum wait between C4 transport pulses in milliseconds. Higher values reduce chattering and pile-up pressure; lower values move faster.'
			)}
			<input
				id="tune-c4-cooldown"
				type="range"
				min="20"
				max="500"
				step="10"
				value={msValue(c4.transport_cooldown_s, 180)}
				oninput={(e) => updateChannel('c4', { transport_cooldown_ms: inputNumber(e) })}
			/>
			<input
				type="number"
				min="20"
				max="500"
				step="10"
				value={msValue(c4.transport_cooldown_s, 180)}
				onchange={(e) => updateChannel('c4', { transport_cooldown_ms: inputNumber(e) })}
				class="w-full border border-border bg-bg px-1.5 py-1 text-right font-mono text-xs text-text"
			/>

			{@render tuningLabel(
				'tune-c4-exit-slow',
				'Exit Slow',
				'Angular window before the C4 exit where transport switches to the gentler approach step. Smaller clears intake faster; larger approaches the exit more cautiously.'
			)}
			<input
				id="tune-c4-exit-slow"
				type="range"
				min="0"
				max="60"
				step="1"
				value={numberValue(c4.exit_approach_angle_deg, 36)}
				oninput={(e) => updateChannel('c4', { exit_approach_angle_deg: inputNumber(e) })}
			/>
			<input
				type="number"
				min="0"
				max="60"
				step="1"
				value={numberValue(c4.exit_approach_angle_deg, 36)}
				onchange={(e) => updateChannel('c4', { exit_approach_angle_deg: inputNumber(e) })}
				class="w-full border border-border bg-bg px-1.5 py-1 text-right font-mono text-xs text-text"
			/>

			{@render tuningLabel(
				'tune-c4-exit-step',
				'Exit Step',
				'C4 tray degrees per gentle approach move near the exit. Lower is softer; higher reduces how long one ready piece blocks upstream intake.'
			)}
			<input
				id="tune-c4-exit-step"
				type="range"
				min="0.5"
				max="8"
				step="0.5"
				value={numberValue(c4.exit_approach_step_deg, 3)}
				oninput={(e) => updateChannel('c4', { exit_approach_step_deg: inputNumber(e) })}
			/>
			<input
				type="number"
				min="0.5"
				max="8"
				step="0.5"
				value={numberValue(c4.exit_approach_step_deg, 3)}
				onchange={(e) => updateChannel('c4', { exit_approach_step_deg: inputNumber(e) })}
				class="w-full border border-border bg-bg px-1.5 py-1 text-right font-mono text-xs text-text"
			/>
		</div>
	</div>

	<div class="border-t border-border pt-3">
		<div class="mb-2 text-xs font-semibold uppercase text-text-muted">C4 Flow</div>
		<div class="grid grid-cols-[92px_minmax(0,1fr)_76px] items-center gap-2 text-xs">
			{@render tuningLabel(
				'tune-c4-zones',
				'Zones',
				'Maximum number of occupied C4 slot zones before upstream channels should slow down or wait. Lower protects C4 from overfilling.'
			)}
			<input
				id="tune-c4-zones"
				type="range"
				min="1"
				max="12"
				step="1"
				value={numberValue(c4.max_zones, 4)}
				oninput={(e) => updateChannel('c4', { max_zones: inputNumber(e) })}
			/>
			<input
				type="number"
				min="1"
				max="12"
				step="1"
				value={numberValue(c4.max_zones, 4)}
				onchange={(e) => updateChannel('c4', { max_zones: inputNumber(e) })}
				class="w-full border border-border bg-bg px-1.5 py-1 text-right font-mono text-xs text-text"
			/>

			{@render tuningLabel(
				'tune-c4-zone-half',
				'Zone Half',
				'Angular half-width for one tracked C4 piece zone. Smaller values let nearby tracked pieces coexist; too small can allow noisy duplicate zones.'
			)}
			<input
				id="tune-c4-zone-half"
				type="range"
				min="3"
				max="24"
				step="1"
				value={numberValue(c4.intake_body_half_width_deg, 10)}
				oninput={(e) => updateChannel('c4', { intake_body_half_width_deg: inputNumber(e) })}
			/>
			<input
				type="number"
				min="3"
				max="24"
				step="1"
				value={numberValue(c4.intake_body_half_width_deg, 10)}
				onchange={(e) => updateChannel('c4', { intake_body_half_width_deg: inputNumber(e) })}
				class="w-full border border-border bg-bg px-1.5 py-1 text-right font-mono text-xs text-text"
			/>

			{@render tuningLabel(
				'tune-c4-guard',
				'Guard',
				'Extra angular spacing around each C4 zone. Lower values allow denser tracked C4 queues; higher values enforce more physical separation.'
			)}
			<input
				id="tune-c4-guard"
				type="range"
				min="0"
				max="30"
				step="1"
				value={numberValue(c4.intake_guard_deg, 28)}
				oninput={(e) => updateChannel('c4', { intake_guard_deg: inputNumber(e) })}
			/>
			<input
				type="number"
				min="0"
				max="30"
				step="1"
				value={numberValue(c4.intake_guard_deg, 28)}
				onchange={(e) => updateChannel('c4', { intake_guard_deg: inputNumber(e) })}
				class="w-full border border-border bg-bg px-1.5 py-1 text-right font-mono text-xs text-text"
			/>

			{@render tuningLabel(
				'tune-c4-release',
				'Release',
				'Tray degrees for the C4 exit-release wiggle. Smaller values reduce tailgating into the same bin; too small may leave the matched piece on the edge.'
			)}
			<input
				id="tune-c4-release"
				type="range"
				min="0.5"
				max="4"
				step="0.1"
				value={numberValue(c4.exit_release_shimmy_amplitude_deg, 1.5)}
				oninput={(e) =>
					updateChannel('c4', { exit_release_shimmy_amplitude_deg: inputNumber(e) })}
			/>
			<input
				type="number"
				min="0.5"
				max="4"
				step="0.1"
				value={numberValue(c4.exit_release_shimmy_amplitude_deg, 1.5)}
				onchange={(e) =>
					updateChannel('c4', { exit_release_shimmy_amplitude_deg: inputNumber(e) })}
				class="w-full border border-border bg-bg px-1.5 py-1 text-right font-mono text-xs text-text"
			/>

			{@render tuningLabel(
				'tune-c4-release-cycles',
				'Cycles',
				'Number of tiny forward/back release wiggles per matched C4 piece. More cycles shake harder without advancing the queue.'
			)}
			<input
				id="tune-c4-release-cycles"
				type="range"
				min="1"
				max="4"
				step="1"
				value={numberValue(c4.exit_release_shimmy_cycles, 2)}
				oninput={(e) => updateChannel('c4', { exit_release_shimmy_cycles: inputNumber(e) })}
			/>
			<input
				type="number"
				min="1"
				max="4"
				step="1"
				value={numberValue(c4.exit_release_shimmy_cycles, 2)}
				onchange={(e) => updateChannel('c4', { exit_release_shimmy_cycles: inputNumber(e) })}
				class="w-full border border-border bg-bg px-1.5 py-1 text-right font-mono text-xs text-text"
			/>

			{@render tuningLabel(
				'tune-c4-rpm',
				'Target rpm',
				'Desired tray rotation rate used to size C4 transport pulses. Higher rpm increases clearing speed; zero disables rpm-driven enlargement.'
			)}
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

			{@render tuningLabel(
				'tune-c4-unjam',
				'Unjam',
				'Time without enough C4 progress before the unjam strategy may kick in. Higher waits longer; lower reacts sooner.'
			)}
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

			{@render tuningLabel(
				'tune-c4-idle',
				'Idle Jog',
				'Allows small C4 nudges while waiting so parts do not sit forever between useful positions. Disable when diagnosing unwanted movement.'
			)}
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
			{@render tuningLabel(
				'tune-c3-max',
				'C3 Max',
				'Maximum pieces C3 should tolerate before backpressure blocks C2. Lower reduces crowding; higher feeds C4 more aggressively.'
			)}
			<input
				id="tune-c3-max"
				type="range"
				min="1"
				max="12"
				step="1"
				value={numberValue(c3.max_piece_count, 3)}
				oninput={(e) => updateChannel('c3', { max_piece_count: inputNumber(e) })}
			/>
			<input
				type="number"
				min="1"
				max="12"
				step="1"
				value={numberValue(c3.max_piece_count, 3)}
				onchange={(e) => updateChannel('c3', { max_piece_count: inputNumber(e) })}
				class="w-full border border-border bg-bg px-1.5 py-1 text-right font-mono text-xs text-text"
			/>

			{@render tuningLabel(
				'tune-c3-speed',
				'C3 Speed',
				'C3 rotor pulse speed in microsteps per second. Higher moves parts onward faster; lower is quieter and gentler.'
			)}
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

			{@render tuningLabel(
				'tune-c3-cooldown',
				'C3 Cool',
				'Minimum wait between C3 pulses in milliseconds. Higher values slow feeding and give tracking more time to settle.'
			)}
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

			{@render tuningLabel(
				'tune-c2-max',
				'C2 Max',
				'Maximum pieces C2 should hold before C1 is blocked. Lower prevents a large queue; higher lets C2 buffer more parts.'
			)}
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

			{@render tuningLabel(
				'tune-c2-cooldown',
				'C2 Cool',
				'Minimum wait between C2 pulses in milliseconds. Higher values slow how quickly C2 refills C3.'
			)}
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

			{@render tuningLabel(
				'tune-c1-cooldown',
				'C1 Cool',
				'Minimum wait between blind C1 feed pulses into C2. Higher values slow bulk feed and reduce C2 overfill pressure.'
			)}
			<input
				id="tune-c1-cooldown"
				type="range"
				min="100"
				max="3000"
				step="50"
				value={msValue(c1.pulse_cooldown_s, 250)}
				oninput={(e) => updateChannel('c1', { pulse_cooldown_ms: inputNumber(e) })}
			/>
			<input
				type="number"
				min="100"
				max="3000"
				step="50"
				value={msValue(c1.pulse_cooldown_s, 250)}
				onchange={(e) => updateChannel('c1', { pulse_cooldown_ms: inputNumber(e) })}
				class="w-full border border-border bg-bg px-1.5 py-1 text-right font-mono text-xs text-text"
			/>

			{@render tuningLabel(
				'tune-c1-jam-timeout',
				'C1 Jam',
				'Seconds without downstream progress before C1 starts jam recovery. Higher values avoid premature recovery while C2 is intentionally slowed.'
			)}
			<input
				id="tune-c1-jam-timeout"
				type="range"
				min="1"
				max="20"
				step="0.5"
				value={numberValue(c1.jam_timeout_s, 4)}
				oninput={(e) => updateChannel('c1', { jam_timeout_s: inputNumber(e) })}
			/>
			<input
				type="number"
				min="1"
				max="20"
				step="0.5"
				value={numberValue(c1.jam_timeout_s, 4)}
				onchange={(e) => updateChannel('c1', { jam_timeout_s: inputNumber(e) })}
				class="w-full border border-border bg-bg px-1.5 py-1 text-right font-mono text-xs text-text"
			/>
		</div>
	</div>

	<div class="border-t border-border pt-3">
		<div class="mb-2 text-xs font-semibold uppercase text-text-muted">Slots</div>
		<div class="grid grid-cols-[92px_minmax(0,1fr)_76px] items-center gap-2 text-xs">
			{@render tuningLabel(
				'tune-slot-c3-c4',
				'C3->C4',
				'Virtual slot allowance between C3 and C4. Lower tightens handoff backpressure; higher lets more pieces queue toward C4.'
			)}
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
