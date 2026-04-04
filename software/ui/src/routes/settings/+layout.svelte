<script lang="ts">
	import { page } from '$app/state';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import { getMachinesContext } from '$lib/machines/context';
	import { settingsNavItems, stepperLabels, type StepperKey } from '$lib/settings/stations';
	import { triggerStoredStepperPulse } from '$lib/settings/stepper-control';

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

	async function triggerGlobalStepperHotkey(stepperKey: StepperKey) {
		if (hotkeyBusy[stepperKey]) return;
		hotkeyBusy = { ...hotkeyBusy, [stepperKey]: true };
		try {
			const message = await triggerStoredStepperPulse(currentBackendBaseUrl(), stepperKey, 'cw');
			showHotkeyStatus(`${stepperLabels[stepperKey]}: ${message}`);
		} catch (error: unknown) {
			const detail =
				error instanceof Error && error.message
					? error.message
					: `${stepperLabels[stepperKey]} hotkey failed.`;
			showHotkeyStatus(`${stepperLabels[stepperKey]}: ${detail}`, true);
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
</script>

<svelte:window onkeydown={handleSettingsHotkey} />

<div class="min-h-screen bg-bg p-4 sm:p-6">
	<AppHeader />

	{#if hotkeyStatusMsg || hotkeyErrorMsg}
		<div
			class={`mb-4 border px-3 py-2 text-sm ${
				hotkeyErrorMsg
					? 'border-[#D01012] bg-[#D01012]/10 text-[#D01012] dark:border-[#D01012] dark:bg-[#D01012]/10 dark:text-red-400'
					: 'border-[#00852B] bg-[#00852B]/10 text-[#00852B] dark:border-[#00852B] dark:bg-[#00852B]/10 dark:text-emerald-300'
			}`}
		>
			{hotkeyErrorMsg ?? hotkeyStatusMsg}
		</div>
	{/if}

	<div class="flex flex-col gap-4 lg:flex-row lg:gap-6">
		<nav class="w-full lg:w-48 lg:flex-shrink-0">
			<div class="grid grid-cols-2 gap-1 sm:grid-cols-3 lg:grid-cols-1">
				{#each settingsNavItems as item}
					{@const active = page.url.pathname === item.href}
					<a
						href={item.href}
						aria-current={active ? 'page' : undefined}
						class="flex items-center gap-2 px-3 py-2 text-left text-sm transition-colors {active
							? 'bg-surface font-medium text-text'
							: 'text-text-muted hover:bg-surface'}"
					>
						<item.icon size={16} />
						{item.label}
					</a>
				{/each}
			</div>
		</nav>

		<div class="min-w-0 flex-1">
			{@render children()}
		</div>
	</div>
</div>
