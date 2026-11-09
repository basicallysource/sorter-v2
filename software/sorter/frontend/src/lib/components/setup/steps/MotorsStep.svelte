<!--
	Each motor's direction: power the motors, turn each one a little, and say
	which way it went, seen from above. A motor that went the wrong way is
	reversed. Which board drives each motor comes from the boards found; the
	wiring picture shows only when a board it is for was found.
-->
<script lang="ts">
	import Cable from '@lucide/svelte/icons/cable';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import HardwarePower from '$lib/components/setup/HardwarePower.svelte';
	import { errorMessage } from '$lib/api/http';
	import { jogMotor, setMotorInverted, type MotorDirection } from '$lib/api/setup';
	import { boardForMotor, boardName, motorSocket } from '$lib/setup/boards';
	import type { SetupFlow } from '$lib/setup/flow.svelte';

	let { flow }: { flow: SetupFlow; onnext: () => void } = $props();

	const ORDER = ['c_channel_1', 'c_channel_2', 'c_channel_3', 'c_channel_4', 'chute'];

	// Each motor from above with an arrow for clockwise, rendered from the CAD.
	const PICTURES: Record<string, string> = {
		c_channel_1_rotor: 'https://assets.basically.website/sorter-docs/setup-motion-c-channel-1-w1024-6755b34839a9.jpg',
		c_channel_2_rotor: 'https://assets.basically.website/sorter-docs/setup-motion-c-channel-2-w1024-46dedaff70f3.jpg',
		c_channel_3_rotor: 'https://assets.basically.website/sorter-docs/setup-motion-c-channel-3-w1024-05be25b17475.jpg',
		carousel: 'https://assets.basically.website/sorter-docs/setup-motion-c-channel-4-w1024-b2a8701ff15a.jpg',
		chute_stepper: 'https://assets.basically.website/sorter-docs/setup-motion-chute-w1024-944ab7fcd1a7.jpg'
	};

	// The SKR Pico's headers, for a machine whose boards are SKR Picos.
	const SKR_WIRING_PICTURE = '/setup/skr-pico-v1.0-headers.png';
	const SKR_PORTS: Record<string, Record<string, string>> = {
		feeder: { c_channel_1: 'E0', c_channel_2: 'X', c_channel_3: 'Y', c_channel_4: 'Z1' },
		distribution: { chute: 'E0' }
	};

	const motors = $derived(
		[...flow.summary!.config.stepper_directions].sort((a, b) => ORDER.indexOf(a.name) - ORDER.indexOf(b.name))
	);
	const skrBoards = $derived(flow.summary!.discovery.boards.filter((board) => board.family === 'skr_pico'));
	const checkedCount = $derived(motors.filter((motor) => flow.marks.motors?.[motor.name]).length);

	let showWiring = $state(false);
	let jogging = $state<string | null>(null);
	let answering = $state<string | null>(null);
	// The last failure, by the motor it belongs to.
	let errors = $state<Record<string, string>>({});

	function setError(name: string, message: string | null) {
		const next = { ...errors };
		if (message) next[name] = message;
		else delete next[name];
		errors = next;
	}

	function where(motor: MotorDirection): string {
		const board = boardForMotor(flow.summary!, motor.name);
		if (!board) return 'On no board found';
		const port = board.family === 'skr_pico' ? SKR_PORTS[board.role]?.[motor.name] : undefined;
		return port ? `${boardName(board)}, ${port}` : boardName(board);
	}

	async function jog(motor: MotorDirection) {
		jogging = motor.name;
		setError(motor.name, null);
		try {
			await jogMotor(flow.base, motor.name, 'cw');
		} catch (e) {
			setError(motor.name, errorMessage(e, 'The motor did not turn.'));
		} finally {
			jogging = null;
		}
	}

	// It turned the way it was told (clockwise), or the other way and is reversed.
	async function answer(motor: MotorDirection, observed: 'cw' | 'ccw') {
		answering = motor.name;
		setError(motor.name, null);
		try {
			if (observed === 'ccw') await setMotorInverted(flow.base, motor.name, !motor.inverted);
			flow.mark({ motors: { ...flow.marks.motors, [motor.name]: true } });
			if (observed === 'ccw') await flow.reload();
		} catch (e) {
			setError(motor.name, errorMessage(e, 'The direction was not saved.'));
		} finally {
			answering = null;
		}
	}
</script>

<div class="flex flex-col gap-(--gap-panels)">
	<HardwarePower {flow} unlocks="The motors can be turned once they are on." />

	<Panel
		title="Each motor"
		description="Use very short turns on an empty machine. Turn a motor, then say which way it went, looking down from above."
	>
		{#snippet actions()}
			<Badge tone={checkedCount === motors.length ? 'success' : 'primary'}>
				{checkedCount} of {motors.length} checked
			</Badge>
			{#if skrBoards.length}
				<Button size="sm" variant="ghost" icon={Cable} onclick={() => (showWiring = !showWiring)}>
					<span class="max-sm:sr-only">{showWiring ? 'Hide the wiring' : 'Show the wiring'}</span>
				</Button>
			{/if}
		{/snippet}
		{#if showWiring && skrBoards.length}
			<div class="mb-4 grid grid-cols-1 gap-4 rounded-control bg-well p-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
				<a href={SKR_WIRING_PICTURE} target="_blank" rel="noopener noreferrer" class="block">
					<img src={SKR_WIRING_PICTURE} alt="The SKR Pico's headers" loading="lazy" class="block h-auto w-full rounded-control" />
				</a>
				<p class="text-sm text-ink-muted">
					Each motor's card names the header on the SKR Pico it plugs into.
				</p>
			</div>
		{/if}
		<div class="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
			{#each motors as motor (motor.name)}
				{@const checked = !!flow.marks.motors?.[motor.name]}
				{@const picture = PICTURES[motorSocket(motor.name)]}
				<section class="flex flex-col gap-3 rounded-control p-3 transition-colors {checked ? 'bg-success-soft' : 'bg-well'}">
					<div class="flex items-start justify-between gap-3">
						<div class="min-w-0 text-sm">
							<h3 class="font-medium text-ink">{motor.label}</h3>
							<p class="text-ink-muted">{where(motor)}</p>
						</div>
						<div class="flex shrink-0 flex-wrap justify-end gap-1.5">
							{#if checked}<Badge tone="success">Checked</Badge>{/if}
							{#if motor.inverted}<Badge>Reversed</Badge>{/if}
						</div>
					</div>
					{#if picture}
						<img
							src={picture}
							alt="{motor.label} seen from above, with an arrow showing clockwise"
							loading="lazy"
							class="aspect-4/3 w-full rounded-control object-cover"
						/>
					{/if}
					<Button
						variant="primary"
						class="self-center"
						loading={jogging === motor.name}
						disabled={!flow.hardwareUp || jogging !== null}
						onclick={() => void jog(motor)}
					>
						Turn it a little
					</Button>
					<p class="text-center text-sm text-ink-muted">Which way did it turn, seen from above?</p>
					<div class="grid grid-cols-2 gap-2">
						<Button
							disabled={!flow.hardwareUp || answering === motor.name}
							onclick={() => void answer(motor, 'cw')}
						>
							Clockwise
						</Button>
						<Button
							disabled={!flow.hardwareUp || answering === motor.name}
							onclick={() => void answer(motor, 'ccw')}
						>
							Counterclockwise
						</Button>
					</div>
					{#if errors[motor.name]}
						<Alert tone="danger">{errors[motor.name]}</Alert>
					{/if}
				</section>
			{/each}
		</div>
	</Panel>
</div>
