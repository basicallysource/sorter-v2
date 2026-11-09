<!--
	Finds the servo on one layer's door without moving anything: every servo is
	let go, the person turns that door by hand, and the servo whose position
	changed is offered for it. Shows each servo's movement live, a few times a
	second, while it is open; closing it stops the watch.
-->
<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import { errorMessage } from '$lib/api/http';
	import { readHandWatch, startHandWatch, stopHandWatch } from '$lib/api/doors';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import ProgressBar from '$lib/components/ui/ProgressBar.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import { layerName, type DoorsController } from './controller.svelte';

	// Turning a door by hand moves its servo at least this far
	// (machine_platform/door_setup.py HAND_MOVE_DEG); the bars are full at FULL.
	const HAND_MOVE_DEG = 5;
	const FULL_DEG = 30;
	const POLL_MS = 250;

	let {
		controller,
		layerIndex,
		assign,
		onclose
	}: {
		controller: DoorsController;
		layerIndex: number;
		// Gives the servo this layer's door; true when it did.
		assign: (servoId: number) => Promise<boolean>;
		onclose: () => void;
	} = $props();

	const place = $derived(`match-${layerIndex}`);
	const name = $derived(layerName(layerIndex).toLowerCase());

	let starting = $state(true);
	let watching = $state(false);
	let turned = $state<{ id: number; degrees: number }[]>([]);
	let moved = $state<number | null>(null);
	let timer: ReturnType<typeof setTimeout> | null = null;
	let gone = false;

	const owners = $derived(
		new Map(
			(controller.doors?.servos ?? [])
				.filter((s) => s.layer_index != null)
				.map((s) => [s.servo_id, s.layer_index as number])
		)
	);
	const turnedMany = $derived(turned.filter((t) => t.degrees >= HAND_MOVE_DEG).length > 1);
	const movedOwner = $derived(moved == null ? undefined : owners.get(moved));

	async function start() {
		stopPolling();
		watching = false;
		starting = true;
		turned = [];
		moved = null;
		const answer = await controller.run('watch-start', place, startHandWatch, () => null);
		starting = false;
		if (!answer || gone) return;
		watching = true;
		void poll();
	}

	async function poll() {
		if (gone || !watching) return;
		try {
			const watch = await readHandWatch(controller.base);
			if (gone || !watching) return;
			turned = Object.entries(watch.turned_degrees)
				.map(([id, degrees]) => ({ id: Number(id), degrees }))
				.sort((a, b) => a.id - b.id);
			moved = watch.moved;
		} catch (e) {
			watching = false;
			controller.fail(place, errorMessage(e, 'The machine stopped answering.'));
			return;
		}
		timer = setTimeout(() => void poll(), POLL_MS);
	}

	function stopPolling() {
		if (timer) clearTimeout(timer);
		timer = null;
	}

	async function use(servoId: number) {
		stopPolling();
		watching = false;
		if (await assign(servoId)) onclose();
		else void start();
	}

	onMount(() => void start());

	onDestroy(() => {
		gone = true;
		stopPolling();
		void stopHandWatch(controller.base).catch(() => {});
	});
</script>

<div class="flex flex-col gap-3">
	<p class="text-sm text-ink">
		Turn {name}'s door by hand, a little either way. Every servo is let go, so the doors turn freely
		and nothing moves on its own.
	</p>

	{#if controller.errors[place]}
		<Alert tone="danger" title="The machine could not watch the servos">
			{controller.errors[place]}
		</Alert>
	{:else if starting}
		<p class="flex items-center gap-2 text-sm text-ink-muted">
			<Spinner size={14} /> Letting the servos go
		</p>
	{:else if moved != null}
		<Alert tone="info" title="Servo {moved} moved">
			Use it for {name}'s door?{movedOwner != null && movedOwner !== layerIndex
				? ` It turns ${layerName(movedOwner).toLowerCase()}'s door now; using it here takes it from that layer.`
				: ''}
			{#snippet actions()}
				<Button
					variant="primary"
					size="sm"
					loading={controller.busy === 'assign'}
					disabled={controller.busy !== null}
					onclick={() => use(moved as number)}>Use servo {moved}</Button
				>
			{/snippet}
		</Alert>
	{:else if turnedMany}
		<Alert tone="warning" title="More than one servo turned">
			Hold the other doors still, then start again.
		</Alert>
	{:else if watching}
		<p class="flex items-center gap-2 text-sm text-ink-muted">
			<Spinner size={14} /> Watching for a door to turn
		</p>
	{/if}

	{#if turned.length}
		<ul class="flex flex-col gap-2" aria-label="How far each servo has turned">
			{#each turned as servo (servo.id)}
				{@const owner = owners.get(servo.id)}
				<li class="grid grid-cols-[7rem_minmax(0,1fr)_3rem] items-center gap-3 text-sm">
					<span class="text-ink">
						Servo {servo.id}
						{#if owner != null && owner !== layerIndex}
							<span class="block text-xs text-ink-muted">{layerName(owner)}'s door</span>
						{/if}
					</span>
					<ProgressBar
						value={Math.min(servo.degrees, FULL_DEG)}
						max={FULL_DEG}
						label="How far servo {servo.id} has turned"
						tone={servo.id === moved ? 'success' : 'primary'}
					/>
					<span class="num text-right text-ink-muted">{Math.round(servo.degrees)}°</span>
				</li>
			{/each}
		</ul>
	{/if}

	<div class="flex flex-wrap gap-2">
		<Button variant="ghost" disabled={controller.busy === 'assign'} onclick={onclose}>Cancel</Button
		>
		<Button
			icon={RefreshCw}
			disabled={controller.busy !== null}
			onclick={() => {
				controller.clear(place);
				void start();
			}}>Start again</Button
		>
	</div>
</div>
