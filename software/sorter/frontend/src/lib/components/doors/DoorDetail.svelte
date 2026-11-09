<!--
	One layer's door, set up as three steps: find its servo, find where it
	stops (shut and open), and try it. Which step is open follows from what the
	machine says about the door, so the page is right after a reload; a running
	or asking search for its stops opens its step wherever it was started.
-->
<script lang="ts">
	import DoorClosed from '@lucide/svelte/icons/door-closed';
	import DoorOpen from '@lucide/svelte/icons/door-open';
	import Hand from '@lucide/svelte/icons/hand';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import Square from '@lucide/svelte/icons/square';
	import Unplug from '@lucide/svelte/icons/unplug';
	import Crosshair from '@lucide/svelte/icons/crosshair';
	import {
		answerWhichEnd,
		findStops,
		markDoorEnd,
		moveDoor,
		nudgeDoorEnd,
		releaseDoors,
		scanServos,
		setLayerServo,
		stopFindingStops,
		type DoorEnd,
		type DoorLayer
	} from '$lib/api/doors';
	import { confirmDialog } from '$lib/confirm.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import NudgeControl from '$lib/components/ui/NudgeControl.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import Step from '$lib/components/ui/Step.svelte';
	import ServoMatch from './ServoMatch.svelte';
	import { layerName, type DoorsController } from './controller.svelte';

	let { controller, layer }: { controller: DoorsController; layer: DoorLayer } = $props();

	const i = $derived(layer.layer_index);
	const name = $derived(layerName(i));
	const lower = $derived(name.toLowerCase());
	const doors = $derived(controller.doors);
	const held = $derived(controller.held);
	const ready = $derived(doors?.ready ?? false);

	// Where each step's sentences go.
	const top = $derived(`door-${i}`);
	const servoPlace = $derived(`servo-${i}`);
	const stopsPlace = $derived(`stops-${i}`);
	const tryPlace = $derived(`try-${i}`);

	// What the person opened or is doing here; none of it comes from the machine.
	let changingServo = $state(false);
	let changingStops = $state(false);
	let byHand = $state(false);
	let hideFailure = $state(false);
	let nudgeBy = $state<Record<DoorEnd, number>>({ closed: 2, open: 2 });
	// Where Shut or Open last sent the door, while nothing else has moved it.
	let moved = $state<DoorEnd | null>(null);
	let tryTitle = $state('That did not work');
	// The ends marked by hand since Set by hand was pressed.
	let marked = $state<Record<DoorEnd, boolean>>({ closed: false, open: false });

	// Another layer chosen: start it fresh.
	let shownLayer = -1;
	$effect.pre(() => {
		if (i === shownLayer) return;
		shownLayer = i;
		changingServo = false;
		changingStops = false;
		byHand = false;
		hideFailure = false;
		moved = null;
	});

	const hasServo = $derived(layer.servo_id != null);
	const answering = $derived(layer.available !== false);
	const matching = $derived(controller.matching === i);

	const search = $derived(doors?.search?.layer_index === i ? doors.search : null);
	const searchRunning = $derived(search?.state === 'running');
	const searchAsking = $derived(search?.state === 'asking');
	const searchFailed = $derived(search?.state === 'failed' && !hideFailure);

	// Servos the last scan heard that can be given a door.
	const usable = $derived((doors?.servos ?? []).filter((s) => s.state === 'ok'));
	const free = $derived(usable.filter((s) => s.layer_index == null));
	// Scan is the thing to do when nothing usable answers, or this door's servo is lost.
	const showScan = $derived(
		(!usable.length && !doors?.shared_ids.length) || (hasServo && !answering)
	);
	const choices = $derived(
		usable
			.filter((s) => s.layer_index !== i)
			.map((s) => ({
				value: String(s.servo_id),
				label: `Servo ${s.servo_id}`,
				hint:
					s.layer_index != null
						? `${layerName(s.layer_index)}'s door`
						: s.factory_id
							? 'New'
							: 'No door yet'
			}))
	);

	const step1 = $derived<'done' | 'current'>(hasServo && answering ? 'done' : 'current');
	const step1Open = $derived(step1 === 'current' || changingServo || matching);
	const stopsBusy = $derived(searchRunning || searchAsking || searchFailed || byHand);
	const step2 = $derived<'locked' | 'current' | 'done'>(
		!hasServo || (!answering && !searchRunning && !searchAsking)
			? 'locked'
			: layer.calibrated && !stopsBusy
				? 'done'
				: 'current'
	);
	const step2Open = $derived(step2 === 'current' || (hasServo && changingStops));
	const step3 = $derived<'locked' | 'current'>(
		layer.calibrated && hasServo && answering ? 'current' : 'locked'
	);
	const stepNow = $derived(step1 !== 'done' ? 1 : step2 !== 'done' ? 2 : 3);

	// Which way a nudge goes: the shut end lies on this side of the open one.
	const shutSide = $derived(
		Math.sign((layer.closed_position ?? 0) - (layer.open_position ?? 0)) || 1
	);
	const samePlace = $derived(
		layer.closed_position != null && layer.closed_position === layer.open_position
	);

	async function assign(servoId: number): Promise<boolean> {
		const found = doors?.servos.find((s) => s.servo_id === servoId);
		const owner = found?.layer_index;
		if (owner != null && owner !== i) {
			const ok = await confirmDialog({
				title: `Move servo ${servoId} to ${lower}?`,
				message: `It turns ${layerName(owner).toLowerCase()}'s door now. That door will have no servo, and where it stops will be forgotten.`,
				action: 'Move it'
			});
			if (!ok) return false;
		}
		const wasNew = found?.factory_id ?? false;
		const answer = await controller.run(
			'assign',
			servoPlace,
			(base) => setLayerServo(base, i, servoId),
			(answer) => {
				const now = answer.doors.layers[i]?.servo_id;
				if (wasNew && now != null && now !== servoId) {
					return {
						tone: 'success',
						title: `Servo ${servoId} is now servo ${now}`,
						text: `It was new, so it was given a number of its own, kept with the power off. You can plug in the next new servo now and scan.`
					};
				}
				return null;
			},
			top
		);
		if (answer) changingServo = false;
		return answer != null;
	}

	async function takeAway() {
		const ok = await confirmDialog({
			title: `Take servo ${layer.servo_id} away from ${lower}?`,
			message: `${name}'s door will have no servo, and where it stops will be forgotten. The servo keeps its number.`,
			action: 'Take it away',
			danger: true
		});
		if (!ok) return;
		const answer = await controller.run('take-away', servoPlace, (base) =>
			setLayerServo(base, i, null)
		);
		if (answer) changingServo = false;
	}

	function scan() {
		void controller.run('scan', servoPlace, scanServos);
	}

	function startMatching() {
		controller.clear(servoPlace);
		controller.matching = i;
	}

	async function startSearch() {
		// The last search's failure stays hidden until this one has started.
		hideFailure = true;
		byHand = false;
		const answer = await controller.run('find-stops', stopsPlace, (base) => findStops(base, i));
		hideFailure = !answer;
	}

	function stopSearch() {
		hideFailure = true;
		void controller.run('stop-search', stopsPlace, stopFindingStops);
	}

	function answerEnd(closedNow: boolean) {
		void controller
			.run(
				'answer',
				stopsPlace,
				(base) => answerWhichEnd(base, i, closedNow),
				(answer) =>
					answer.message?.startsWith('Saved, but')
						? { tone: 'warning', title: `${name}'s door is set up`, text: answer.message }
						: null,
				top
			)
			.then((ok) => {
				if (ok) changingStops = false;
			});
	}

	async function setByHand() {
		hideFailure = true;
		const ok = await controller.run('release', stopsPlace, releaseDoors);
		if (ok) {
			marked = { closed: false, open: false };
			byHand = true;
		}
	}

	async function mark(end: DoorEnd) {
		const answer = await controller.run(`mark-${end}`, stopsPlace, (base) =>
			markDoorEnd(base, i, end)
		);
		if (answer) marked = { ...marked, [end]: true };
	}

	async function move(to: DoorEnd) {
		moved = null;
		tryTitle = `${name}'s door did not ${to === 'closed' ? 'shut' : 'open'}`;
		const answer = await controller.run(`move-${to}`, tryPlace, (base) => moveDoor(base, i, to));
		if (answer) moved = to;
	}

	function nudge(end: DoorEnd, side: 'left' | 'right') {
		// Right goes further toward its own end, left back toward the other.
		const away = end === 'closed' ? shutSide : -shutSide;
		const degrees = (side === 'right' ? away : -away) * nudgeBy[end];
		moved = null;
		tryTitle = 'The position was not changed';
		void controller.run(`nudge-${end}-${side}`, tryPlace, (base) =>
			nudgeDoorEnd(base, i, end, degrees)
		);
	}

	const tryError = $derived(controller.errors[tryPlace]);
</script>

{#snippet errorAt(place: string, title: string)}
	{#if controller.errors[place]}
		<Alert tone="danger" {title}>{controller.errors[place]}</Alert>
	{/if}
{/snippet}

<Panel title="{name}'s door" flush>
	{#snippet actions()}
		{#if layer.kind === 'fixed'}
			<Badge>Always shut</Badge>
		{:else if layer.calibrated && hasServo && answering}
			<Badge tone="success">Set up</Badge>
		{:else}
			<Badge tone="primary">Step {stepNow} of 3</Badge>
		{/if}
	{/snippet}

	{#if controller.notes[top]}
		{@const note = controller.notes[top]}
		<div class="px-(--pad-panel) pb-3">
			<Alert tone={note.tone} title={note.title}>{note.text}</Alert>
		</div>
	{/if}

	{#if layer.kind === 'fixed'}
		<p class="border-t border-line px-(--pad-panel) py-4 text-sm text-ink">
			This layer's door has no servo: it is always shut, so every piece that reaches it stays on
			this layer.
		</p>
	{:else}
		<ol class="divide-y divide-line border-t border-line">
			<Step
				n={1}
				title="Find its servo"
				status={step1}
				open={step1Open}
				hint={hasServo
					? answering
						? `Servo ${layer.servo_id}`
						: (layer.error ?? `Servo ${layer.servo_id} does not answer.`)
					: 'Which servo turns this door.'}
			>
				{#snippet actions()}
					{#if step1 === 'done' && !matching}
						{#if changingServo}
							<Button size="sm" variant="ghost" onclick={() => (changingServo = false)}
								>Close</Button
							>
						{:else}
							<Button size="sm" disabled={held} onclick={() => (changingServo = true)}
								>Change</Button
							>
						{/if}
					{/if}
				{/snippet}
				<div class="flex flex-col gap-3">
					{@render errorAt(servoPlace, 'That did not work')}
					{#if matching}
						<ServoMatch
							{controller}
							layerIndex={i}
							{assign}
							onclose={() => (controller.matching = null)}
						/>
					{:else}
						{#if hasServo && !answering}
							<p class="text-sm text-ink">
								Check the servo's cable and that the servos have power, then scan. If the servo was
								replaced, find this door's new one by turning the door.
							</p>
						{:else if !hasServo && free.length === 1}
							<p class="text-sm text-ink">
								One servo is plugged in that has no door yet: servo {free[0].servo_id}{free[0]
									.factory_id
									? ', a new one'
									: ''}.
							</p>
						{:else if usable.length}
							<p class="text-sm text-ink">
								Turn {lower}'s door by hand and the machine sees which servo moved. Nothing moves on
								its own.
							</p>
						{:else if doors?.shared_ids.length}
							<p class="text-sm text-ink">
								The servos plugged in all answer as number {doors.shared_ids[0]}. Unplug all of them
								but one, then scan again.
							</p>
						{:else}
							<p class="text-sm text-ink">
								No servo answers yet. Plug this door's servo in, then scan.
							</p>
						{/if}
						{#if hasServo || usable.length || showScan}
							<div class="flex flex-wrap items-center gap-2">
								{#if hasServo}
									<Button
										icon={Unplug}
										variant="ghost"
										loading={controller.busy === 'take-away'}
										disabled={held}
										onclick={takeAway}>Take the servo away</Button
									>
								{/if}
								{#if usable.length}
									<Button
										icon={Hand}
										variant={(!hasServo && free.length === 1) || !answering
											? 'secondary'
											: 'primary'}
										disabled={held || !ready}
										onclick={startMatching}>Find it by turning the door</Button
									>
								{/if}
								{#if !hasServo && free.length === 1}
									<Button
										variant="primary"
										loading={controller.busy === 'assign'}
										disabled={held}
										onclick={() => assign(free[0].servo_id)}
										>Use servo {free[0].servo_id} for {lower}</Button
									>
								{/if}
								{#if showScan}
									<Button
										icon={RefreshCw}
										variant="primary"
										loading={controller.busy === 'scan'}
										disabled={held}
										onclick={scan}>Scan</Button
									>
								{/if}
							</div>
						{/if}
						{#if choices.length > 1 || (hasServo && choices.length)}
							<div class="flex flex-wrap items-center gap-x-3 gap-y-2">
								<span class="text-sm text-ink-muted">Or choose it</span>
								<Select
									class="w-56"
									size="sm"
									label="Choose this door's servo"
									placeholder="Choose a servo"
									options={choices}
									disabled={held}
									onchange={(value) => assign(Number(value))}
								/>
							</div>
						{/if}
					{/if}
				</div>
			</Step>

			<Step
				n={2}
				title="Find where it stops"
				status={step2}
				open={step2Open}
				hint={step2 === 'locked'
					? hasServo
						? 'Its servo does not answer.'
						: 'Find its servo first.'
					: step2 === 'done'
						? 'Where it is shut and where it is open are saved.'
						: undefined}
			>
				{#snippet actions()}
					{#if step2 === 'done'}
						{#if changingStops}
							<Button size="sm" variant="ghost" onclick={() => (changingStops = false)}
								>Close</Button
							>
						{:else}
							<Button size="sm" disabled={held} onclick={() => (changingStops = true)}
								>Change</Button
							>
						{/if}
					{/if}
				{/snippet}
				<div class="flex flex-col gap-3">
					<p class="text-sm text-ink">
						A shut door catches the pieces for its layer; an open door lets them fall past to the
						layers below.
					</p>
					{@render errorAt(stopsPlace, 'That did not work')}
					{#if searchRunning}
						<div class="flex flex-wrap items-center gap-3">
							<div class="min-w-0 flex-1 text-sm">
								<p class="flex items-center gap-2 text-ink">
									<Spinner size={14} />
									{search?.message}
								</p>
								<p class="pl-5.5 text-ink-muted">Keep fingers clear while the door turns.</p>
							</div>
							<Button
								icon={Square}
								loading={controller.busy === 'stop-search'}
								disabled={controller.busy !== null}
								onclick={stopSearch}>Stop</Button
							>
						</div>
					{:else if searchAsking}
						<div class="flex flex-col gap-3 rounded-control bg-well px-4 py-3">
							<p class="text-sm font-semibold text-ink">{search?.message}</p>
							{#if search?.open_ended?.length}
								<p class="text-sm text-ink-muted">
									At one end the door met nothing before the servo's own limit, so that end is as
									far as the servo turns.
								</p>
							{/if}
							<div class="flex flex-wrap gap-2">
								<Button
									icon={DoorClosed}
									loading={controller.busy === 'answer'}
									disabled={controller.busy !== null}
									onclick={() => answerEnd(true)}>Yes, it is shut</Button
								>
								<Button
									icon={DoorOpen}
									disabled={controller.busy !== null}
									onclick={() => answerEnd(false)}>No, it is open</Button
								>
							</div>
						</div>
					{:else if byHand}
						<p class="text-sm text-ink">
							Every door servo is let go, so this door turns freely by hand.
						</p>
						<ol class="flex flex-col gap-3 text-sm text-ink">
							{#each [{ end: 'closed', text: '1. Hold the door shut across the chute, then press This is shut.', button: 'This is shut', icon: DoorClosed }, { end: 'open', text: '2. Hold it open against its wall, then press This is open.', button: 'This is open', icon: DoorOpen }] as row (row.end)}
								{@const end = row.end as DoorEnd}
								<li class="flex flex-col items-start gap-2">
									<span>{row.text}</span>
									<span class="flex items-center gap-3">
										<Button
											icon={row.icon}
											loading={controller.busy === `mark-${end}`}
											disabled={held}
											onclick={() => mark(end)}>{row.button}</Button
										>
										{#if marked[end]}<Badge tone="success">Saved</Badge>{/if}
									</span>
								</li>
							{/each}
						</ol>
						{#if samePlace}
							<Alert tone="warning" title="Shut and open are the same place">
								Hold the door at each end before you press its button.
							</Alert>
						{/if}
						<div class="flex flex-wrap gap-2">
							<Button
								variant={layer.calibrated && !samePlace ? 'primary' : 'ghost'}
								disabled={controller.busy !== null}
								onclick={() => {
									byHand = false;
									changingStops = false;
								}}>{layer.calibrated ? 'Done' : 'Cancel'}</Button
							>
						</div>
					{:else}
						{#if searchFailed}
							<Alert tone="danger" title="The stops were not found">
								{search?.message} You can set them by hand instead.
							</Alert>
						{/if}
						<p class="text-sm text-ink">
							The door turns slowly through its whole travel to find both ends. Keep fingers clear.
						</p>
						<div class="flex flex-wrap gap-2">
							<Button icon={Hand} disabled={held || !answering} onclick={setByHand}
								>Set by hand</Button
							>
							<Button
								variant="primary"
								icon={Crosshair}
								loading={controller.busy === 'find-stops'}
								disabled={held || !answering}
								onclick={startSearch}>{searchFailed ? 'Try again' : 'Find the stops'}</Button
							>
						</div>
					{/if}
				</div>
			</Step>

			<Step
				n={3}
				title="Try it"
				status={step3}
				hint={step3 === 'locked'
					? layer.calibrated && hasServo
						? 'Its servo does not answer.'
						: 'Find where it stops first.'
					: moved == null
						? 'Shut it and open it to see it work.'
						: moved === 'open'
							? 'It is open now.'
							: 'It is shut now.'}
			>
				<div class="flex flex-col gap-4">
					{#if tryError}
						<Alert tone="danger" title={tryTitle}>{tryError}</Alert>
					{/if}
					<div class="flex flex-wrap gap-2">
						<Button
							icon={DoorClosed}
							loading={controller.busy === 'move-closed'}
							disabled={held || !answering}
							onclick={() => move('closed')}>Shut</Button
						>
						<Button
							icon={DoorOpen}
							loading={controller.busy === 'move-open'}
							disabled={held || !answering}
							onclick={() => move('open')}>Open</Button
						>
					</div>
					<div class="flex flex-col gap-2">
						<p class="text-sm text-ink-muted">
							Fine tune where it stops. Each press moves the door to the new place, so you can see
							it.
						</p>
						{#each [{ end: 'closed', label: 'Shut', toward: 'open', further: 'further shut' }, { end: 'open', label: 'Open', toward: 'shut', further: 'further open' }] as row (row.end)}
							{@const end = row.end as DoorEnd}
							<div class="flex items-center gap-3">
								<span class="w-28 text-sm text-ink">{row.label} position</span>
								<NudgeControl
									bind:value={nudgeBy[end]}
									presets={[1, 2, 5]}
									max={10}
									label="{row.label} position"
									leftLabel="Move the {row.label.toLowerCase()} position {nudgeBy[
										end
									]}° toward {row.toward}"
									rightLabel="Move the {row.label.toLowerCase()} position {nudgeBy[
										end
									]}° {row.further}"
									busy={controller.busy === `nudge-${end}-left`
										? 'left'
										: controller.busy === `nudge-${end}-right`
											? 'right'
											: null}
									disabled={(held && !controller.busy?.startsWith(`nudge-${end}`)) || !answering}
									onnudge={(side) => nudge(end, side)}
								/>
							</div>
						{/each}
					</div>
				</div>
			</Step>
		</ol>
	{/if}
</Panel>
