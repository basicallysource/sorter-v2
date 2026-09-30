<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import AppShell from '$lib/components/AppShell.svelte';
	import SideNav from '$lib/components/ui/SideNav.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import { getMachinesContext } from '$lib/machines/context';
	import {
		settingsNavGroups,
		stepperLabels,
		type StepperKey
	} from '$lib/settings/stations';
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
			) ?? getBackendHttpBase()
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

	// A page whose main thing is a camera (a channel page) takes the whole width, up
	// to 1800px; a page of forms stays at 1152px (design system docs/layout.md).
	const wide = $derived(page.route.id === '/settings/[station]');

	const navItems = settingsNavGroups.flatMap((g) => g.items);
	// The phone's select lists every page, so a page is named with its group.
	const navOptions = settingsNavGroups.flatMap((g) =>
		g.items.map((i) => ({ value: i.href, label: g.label ? `${g.label}: ${i.label}` : i.label }))
	);
	const here = $derived(
		navItems
			.filter((i) => page.url.pathname === i.href || page.url.pathname.startsWith(i.href + '/'))
			.sort((a, b) => b.href.length - a.href.length)[0]?.href ?? navItems[0].href
	);
</script>

<svelte:window onkeydown={handleSettingsHotkey} />

<AppShell fit>
	<div class="flex min-h-0 flex-1">
		<aside class="hidden w-60 shrink-0 overflow-y-auto bg-surface px-3 py-5 lg:block">
			<SideNav groups={settingsNavGroups} label="Settings" />
		</aside>
		<div class="min-w-0 flex-1 lg:overflow-y-auto">
			<div
				class="flex flex-col gap-(--gap-panels) px-4 py-6 sm:px-8 {wide
					? 'max-w-[1800px]'
					: 'max-w-6xl'}"
			>
				<div class="lg:hidden">
					<Select
						label="Settings page"
						value={here}
						options={navOptions}
						onchange={(href) => goto(href)}
					/>
				</div>
				{#if hotkeyErrorMsg}
					<Alert tone="danger">{hotkeyErrorMsg}</Alert>
				{:else if hotkeyStatusMsg}
					<Alert tone="success">{hotkeyStatusMsg}</Alert>
				{/if}
				{@render children()}
			</div>
		</div>
	</div>
</AppShell>
