<script lang="ts">
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachinesContext } from '$lib/machines/context';
	import type { StepperKey } from '$lib/settings/stations';
	import { stepperLabels } from '$lib/settings/stations';

	type StepperOption = {
		key: StepperKey;
		label: string;
	};

	let {
		steppers,
		title = 'Stepper Test / Control',
		keyboardShortcutStepper = null
	}: {
		steppers: StepperKey[];
		title?: string;
		keyboardShortcutStepper?: StepperKey | null;
	} = $props();

	const manager = getMachinesContext();

	const stepperOptions = $derived(
		steppers.map(
			(stepper) => ({ key: stepper, label: stepperLabels[stepper] }) satisfies StepperOption
		)
	);

	let pulseDuration = $state(0.25);
	let pulseSpeed = $state(800);
	let pulsing = $state<Record<string, boolean>>({});
	let stopping = $state<Record<string, boolean>>({});
	let statusMsg = $state('');
	let errorMsg = $state<string | null>(null);

	function currentBackendBaseUrl(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? backendHttpBaseUrl
		);
	}

	function humanizeStepperError(message: string): string {
		if (message.includes('Controller not initialized')) {
			return 'The selected backend is not running the full machine controller yet. Start the machine process to use live stepper control.';
		}
		return message;
	}

	function shouldIgnoreKeyboardShortcut(event: KeyboardEvent): boolean {
		if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return true;
		const target = event.target;
		if (!(target instanceof HTMLElement)) return false;
		if (target.isContentEditable) return true;
		return ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(target.tagName);
	}

	async function readErrorMessage(res: Response): Promise<string> {
		try {
			const data = await res.json();
			if (typeof data?.detail === 'string') return data.detail;
			if (typeof data?.message === 'string') return data.message;
		} catch {
			// fall through
		}
		try {
			return await res.text();
		} catch {
			return `Request failed with status ${res.status}`;
		}
	}

	async function pulse(stepper: StepperKey, direction: 'cw' | 'ccw') {
		const key = `${stepper}:${direction}`;
		if (pulsing[key]) return;
		pulsing = { ...pulsing, [key]: true };
		statusMsg = '';
		errorMsg = null;
		try {
			const params = new URLSearchParams({
				stepper,
				direction,
				duration_s: String(pulseDuration),
				speed: String(pulseSpeed)
			});
			const res = await fetch(`${currentBackendBaseUrl()}/stepper/pulse?${params.toString()}`, {
				method: 'POST'
			});
			if (!res.ok) {
				const errText = humanizeStepperError(await readErrorMessage(res));
				errorMsg = `${stepperLabels[stepper]} ${direction.toUpperCase()} failed: ${errText}`;
				console.error(`Pulse failed for ${stepper} ${direction}:`, errText);
				return;
			}
			statusMsg = `${stepperLabels[stepper]} pulsing ${direction.toUpperCase()}.`;
		} catch (e) {
			errorMsg = `${stepperLabels[stepper]} ${direction.toUpperCase()} request failed.`;
			console.error(`Pulse request failed for ${stepper} ${direction}:`, e);
		} finally {
			pulsing = { ...pulsing, [key]: false };
		}
	}

	async function stop(stepper: StepperKey) {
		stopping = { ...stopping, [stepper]: true };
		statusMsg = '';
		errorMsg = null;
		try {
			const params = new URLSearchParams({ stepper });
			const res = await fetch(`${currentBackendBaseUrl()}/stepper/stop?${params.toString()}`, {
				method: 'POST'
			});
			if (!res.ok) {
				const errText = humanizeStepperError(await readErrorMessage(res));
				errorMsg = `${stepperLabels[stepper]} stop failed: ${errText}`;
				console.error(`Stop failed for ${stepper}:`, errText);
				return;
			}
			statusMsg = `${stepperLabels[stepper]} stopped.`;
		} catch (e) {
			errorMsg = `${stepperLabels[stepper]} stop request failed.`;
			console.error(`Stop request failed for ${stepper}:`, e);
		} finally {
			stopping = { ...stopping, [stepper]: false };
		}
	}

	function handleWindowKeydown(event: KeyboardEvent) {
		if (!keyboardShortcutStepper) return;
		if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
		if (shouldIgnoreKeyboardShortcut(event)) return;
		event.preventDefault();
		void pulse(keyboardShortcutStepper, event.key === 'ArrowRight' ? 'cw' : 'ccw');
	}
</script>

<svelte:window onkeydown={handleWindowKeydown} />

<div class="flex flex-col gap-4">
	<div>
		<h3 class="dark:text-text-dark mb-2 text-sm font-medium text-text">{title}</h3>
		{#if manager.selectedMachine}
			<div class="dark:text-text-muted-dark mb-2 text-xs text-text-muted">
				Sending commands to
				<span class="dark:text-text-dark font-medium text-text">
					{manager.selectedMachine.identity?.nickname ??
						manager.selectedMachine.identity?.machine_id.slice(0, 8)}
				</span>
			</div>
		{/if}
		{#if keyboardShortcutStepper}
			<div class="dark:text-text-muted-dark mb-2 text-xs text-text-muted">
				Left/Right arrow keys also pulse this stepper while no field is focused.
			</div>
		{/if}
		<div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
			<label class="dark:text-text-dark text-xs text-text">
				Duration (s)
				<input
					type="number"
					min="0.05"
					max="5"
					step="0.05"
					bind:value={pulseDuration}
					class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark mt-1 w-full border border-border bg-bg px-2 py-1.5 text-sm text-text"
				/>
			</label>
			<label class="dark:text-text-dark text-xs text-text">
				Speed
				<input
					type="number"
					min="1"
					step="50"
					bind:value={pulseSpeed}
					class="dark:border-border-dark dark:bg-bg-dark dark:text-text-dark mt-1 w-full border border-border bg-bg px-2 py-1.5 text-sm text-text"
				/>
			</label>
		</div>
		{#if errorMsg}
			<div class="mt-3 text-sm text-red-600 dark:text-red-400">{errorMsg}</div>
		{:else if statusMsg}
			<div class="dark:text-text-muted-dark mt-3 text-sm text-text-muted">{statusMsg}</div>
		{/if}
	</div>

	<div class="flex flex-col gap-2">
		{#each stepperOptions as stepper}
			<div
				class="dark:border-border-dark dark:bg-bg-dark flex flex-col gap-2 border border-border bg-bg px-2 py-2 sm:flex-row sm:items-center sm:justify-between"
			>
				<span class="dark:text-text-dark text-sm text-text">{stepper.label}</span>
				<div class="grid grid-cols-3 gap-2 sm:flex sm:flex-wrap">
					<button
						onclick={() => pulse(stepper.key, 'cw')}
						disabled={Boolean(pulsing[`${stepper.key}:cw`])}
						class="dark:border-border-dark dark:bg-surface-dark dark:text-text-dark dark:hover:bg-bg-dark w-full cursor-pointer border border-border bg-surface px-3 py-1.5 text-xs text-text hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto"
					>
						Pulse CW
					</button>
					<button
						onclick={() => pulse(stepper.key, 'ccw')}
						disabled={Boolean(pulsing[`${stepper.key}:ccw`])}
						class="dark:border-border-dark dark:bg-surface-dark dark:text-text-dark dark:hover:bg-bg-dark w-full cursor-pointer border border-border bg-surface px-3 py-1.5 text-xs text-text hover:bg-bg disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto"
					>
						Pulse CCW
					</button>
					<button
						onclick={() => stop(stepper.key)}
						disabled={Boolean(stopping[stepper.key])}
						class="w-full cursor-pointer border border-red-500 bg-red-500/20 px-3 py-1.5 text-xs text-red-600 hover:bg-red-500/30 disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto dark:text-red-400"
					>
						Stop
					</button>
				</div>
			</div>
		{/each}
	</div>
</div>
