<script lang="ts">
	import { page } from '$app/state';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import { getMachinesContext } from '$lib/machines/context';
	import {
		settingsNavItemsForSetup,
		stepperLabels,
		type MachineSetupKey,
		type StepperKey
	} from '$lib/settings/stations';
	import {
		CLASSIFICATION_CHANNEL_STEPPER_LABEL,
		stepperGearRatioForSetup,
		triggerStoredStepperPulse
	} from '$lib/settings/stepper-control';
	import { onMount } from 'svelte';

	let { children } = $props();

	const manager = getMachinesContext();

	const HOTKEY_STEPPER_KEYS: Record<string, StepperKey> = {
		Digit1: 'c_channel_1',
		Digit2: 'c_channel_2',
		Digit3: 'c_channel_3',
		Digit4: 'carousel',
		Numpad1: 'c_channel_1',
		Numpad2: 'c_channel_2',
		Numpad3: 'c_channel_3',
		Numpad4: 'carousel'
	};

	let hotkeyStatusMsg = $state('');
	let hotkeyErrorMsg = $state<string | null>(null);
	let hotkeyBusy = $state<Partial<Record<StepperKey, boolean>>>({});
	let hotkeyStatusTimeout: ReturnType<typeof setTimeout> | null = null;
	let machineSetup = $state<MachineSetupKey>('standard_carousel');

	const visibleSettingsNavItems = $derived(settingsNavItemsForSetup(machineSetup));

	function currentBackendBaseUrl(): string {
		return (
			machineHttpBaseUrlFromWsUrl(
				manager.selectedMachine?.status === 'connected' ? manager.selectedMachine.url : null
			) ?? backendHttpBaseUrl
		);
	}

	function shouldIgnoreGlobalHotkey(event: KeyboardEvent): boolean {
		if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.repeat) {
			return true;
		}
		const target = event.target;
		if (!(target instanceof HTMLElement)) return false;
		if (target.isContentEditable) return true;
		return ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(target.tagName);
	}

	function showHotkeyStatus(message: string, isError = false) {
		if (hotkeyStatusTimeout) clearTimeout(hotkeyStatusTimeout);
		hotkeyStatusMsg = isError ? '' : message;
		hotkeyErrorMsg = isError ? message : null;
		hotkeyStatusTimeout = setTimeout(() => {
			hotkeyStatusMsg = '';
			hotkeyErrorMsg = null;
		}, 2200);
	}

	function stepperHotkeyLabel(stepperKey: StepperKey): string {
		if (stepperKey === 'carousel' && machineSetup === 'classification_channel') {
			return CLASSIFICATION_CHANNEL_STEPPER_LABEL;
		}
		return stepperLabels[stepperKey];
	}

	async function triggerGlobalStepperHotkey(stepperKey: StepperKey) {
		if (hotkeyBusy[stepperKey]) return;
		hotkeyBusy = { ...hotkeyBusy, [stepperKey]: true };
		try {
			const message = await triggerStoredStepperPulse(currentBackendBaseUrl(), stepperKey, 'cw', {
				gearRatio: stepperGearRatioForSetup(stepperKey, machineSetup)
			});
			showHotkeyStatus(`${stepperHotkeyLabel(stepperKey)}: ${message}`);
		} catch (error: unknown) {
			const detail =
				error instanceof Error && error.message
					? error.message
					: `${stepperHotkeyLabel(stepperKey)} hotkey failed.`;
			showHotkeyStatus(`${stepperHotkeyLabel(stepperKey)}: ${detail}`, true);
		} finally {
			hotkeyBusy = { ...hotkeyBusy, [stepperKey]: false };
		}
	}

	function handleSettingsHotkey(event: KeyboardEvent) {
		if (shouldIgnoreGlobalHotkey(event)) return;
		const stepperKey = HOTKEY_STEPPER_KEYS[event.code];
		if (!stepperKey) return;
		event.preventDefault();
		void triggerGlobalStepperHotkey(stepperKey);
	}

	async function loadMachineSetup() {
		try {
			const res = await fetch(`${currentBackendBaseUrl()}/api/machine-setup`);
			if (!res.ok) return;
			const payload = await res.json();
			if (
				payload?.setup === 'classification_channel' ||
				payload?.setup === 'manual_carousel' ||
				payload?.setup === 'standard_carousel'
			) {
				machineSetup = payload.setup;
			}
		} catch {
			// Ignore transient backend fetch issues in the nav shell.
		}
	}

	onMount(() => {
		void loadMachineSetup();
	});
</script>

<svelte:window onkeydown={handleSettingsHotkey} />

<div class="min-h-screen bg-bg">
	<AppHeader />
	<div class="p-4 sm:p-6">

	{#if hotkeyStatusMsg || hotkeyErrorMsg}
		<div
			class={`mb-4 border px-3 py-2 text-sm ${
				hotkeyErrorMsg
					? 'border-danger bg-danger/10 text-danger dark:border-danger dark:bg-danger/10 dark:text-red-400'
					: 'border-success bg-success/10 text-success dark:border-success dark:bg-success/10 dark:text-emerald-300'
			}`}
		>
			{hotkeyErrorMsg ?? hotkeyStatusMsg}
		</div>
	{/if}

	<div class="flex flex-col gap-4 lg:flex-row lg:gap-6">
		<nav class="w-full lg:w-48 lg:flex-shrink-0">
			<div class="grid grid-cols-2 gap-1 sm:grid-cols-3 lg:grid-cols-1">
				{#each visibleSettingsNavItems as entry, i (i)}
					{#if 'href' in entry}
						{@const active =
							page.url.pathname === entry.href ||
							(entry.href !== '/settings' && page.url.pathname.startsWith(`${entry.href}/`))}
						<a
							href={entry.href}
							aria-current={active ? 'page' : undefined}
							class="flex items-center gap-2 px-3 py-2 text-left text-sm transition-colors {active
								? 'bg-primary/10 font-medium text-primary'
								: 'text-text-muted hover:bg-surface'}"
						>
							<entry.icon size={16} />
							{entry.label}
						</a>
					{:else}
						<div
							class="col-span-full mt-3 px-3 pb-1 pt-2 text-xs font-semibold uppercase tracking-wider text-text-muted lg:mt-4"
						>
							{entry.label}
						</div>
					{/if}
				{/each}
			</div>
		</nav>

		<div class="min-w-0 flex-1">
			{@render children()}
		</div>
	</div>
	</div>
</div>
