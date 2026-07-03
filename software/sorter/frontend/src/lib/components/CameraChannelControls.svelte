<script lang="ts">
	import { getMachineContext } from '$lib/machines/context';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { Button, Popover } from '$lib/components/primitives';
	import { RotateCw } from 'lucide-svelte';
	import {
		STEPPER_GEAR_RATIOS,
		loadStoredStepperPulseSetting
	} from '$lib/settings/stepper-control';
	import type { StepperKey } from '$lib/settings/stations';

	let { stepperKey }: { stepperKey: StepperKey } = $props();

	const machine = getMachineContext();

	type ChannelMoveAction = 'nudge_ccw' | 'nudge_cw' | 'rotate_180';

	let pendingAction = $state<ChannelMoveAction | null>(null);
	let errorMessage = $state<string | null>(null);

	function currentBackendBaseUrl(): string {
		return machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? getBackendHttpBase();
	}

	async function readErrorMessage(res: Response): Promise<string> {
		try {
			const data = await res.json();
			if (typeof data?.detail === 'string') return data.detail;
			if (typeof data?.message === 'string') return data.message;
		} catch {
			// fall through to text
		}
		try {
			const text = await res.text();
			if (text) return text;
		} catch {
			// fall through to status
		}
		return `Request failed with status ${res.status}`;
	}

	function humanizeStepperError(message: string): string {
		if (message.includes('Controller not initialized')) {
			return 'Hardware not started. Press Home in the dashboard first.';
		}
		return message;
	}

	async function moveOutputDegrees(action: ChannelMoveAction, output_degrees: number) {
		if (pendingAction) return;
		pendingAction = action;
		errorMessage = null;
		try {
			const gear_ratio = STEPPER_GEAR_RATIOS[stepperKey] ?? 1;
			const speed = loadStoredStepperPulseSetting<number>(stepperKey, 'pulseSpeed', 800);
			const params = new URLSearchParams({
				stepper: stepperKey,
				degrees: String(output_degrees * gear_ratio),
				speed: String(speed)
			});
			const res = await fetch(
				`${currentBackendBaseUrl()}/stepper/move-degrees?${params.toString()}`,
				{ method: 'POST' }
			);
			if (!res.ok) {
				throw new Error(humanizeStepperError(await readErrorMessage(res)));
			}
		} catch (e: any) {
			errorMessage = e?.message ?? 'Could not move channel';
		} finally {
			pendingAction = null;
		}
	}
</script>

{#if errorMessage}
	<span class="max-w-44 truncate text-sm text-danger" title={errorMessage}>{errorMessage}</span>
{/if}
<Popover placement="bottom">
	{#snippet trigger()}
		<Button
			variant="secondary"
			size="sm"
			loading={pendingAction === 'nudge_ccw'}
			disabled={pendingAction !== null}
			onclick={() => void moveOutputDegrees('nudge_ccw', -1)}
		>
			-1°
		</Button>
	{/snippet}
	Nudge channel 1° counter-clockwise
</Popover>
<Popover placement="bottom">
	{#snippet trigger()}
		<Button
			variant="secondary"
			size="sm"
			loading={pendingAction === 'nudge_cw'}
			disabled={pendingAction !== null}
			onclick={() => void moveOutputDegrees('nudge_cw', 1)}
		>
			+1°
		</Button>
	{/snippet}
	Nudge channel 1° clockwise
</Popover>
<Popover placement="bottom">
	{#snippet trigger()}
		<Button
			variant="secondary"
			size="sm"
			loading={pendingAction === 'rotate_180'}
			disabled={pendingAction !== null}
			onclick={() => void moveOutputDegrees('rotate_180', 180)}
		>
			<RotateCw size={12} />
			180°
		</Button>
	{/snippet}
	Rotate channel 180° clockwise
</Popover>
