<!--
	The setup flow's shell: which steps apply to this machine, which one is
	open (the address's ?step=), which are done, and the way between them.
	Each step is a component that loads, saves and shows its own errors
	(src/lib/components/setup/steps/); the steps and what makes each done are
	in src/lib/setup/steps.ts, the shared state in src/lib/setup/flow.svelte.ts.
-->
<script lang="ts">
	import type { Component } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import RefreshCcw from '@lucide/svelte/icons/refresh-ccw';
	import AppShell from '$lib/components/AppShell.svelte';
	import SetupNavFooter from '$lib/components/setup/SetupNavFooter.svelte';
	import SetupStepperNav from '$lib/components/setup/SetupStepperNav.svelte';
	import BinsStep from '$lib/components/setup/steps/BinsStep.svelte';
	import BoardsStep from '$lib/components/setup/steps/BoardsStep.svelte';
	import CamerasStep from '$lib/components/setup/steps/CamerasStep.svelte';
	import ChuteHomeStep from '$lib/components/setup/steps/ChuteHomeStep.svelte';
	import ChuteStep from '$lib/components/setup/steps/ChuteStep.svelte';
	import DiscardStep from '$lib/components/setup/steps/DiscardStep.svelte';
	import DoneStep from '$lib/components/setup/steps/DoneStep.svelte';
	import DoorsStep from '$lib/components/setup/steps/DoorsStep.svelte';
	import HiveStep from '$lib/components/setup/steps/HiveStep.svelte';
	import IdentityStep from '$lib/components/setup/steps/IdentityStep.svelte';
	import MotorsStep from '$lib/components/setup/steps/MotorsStep.svelte';
	import SharingStep from '$lib/components/setup/steps/SharingStep.svelte';
	import ThemeStep from '$lib/components/setup/steps/ThemeStep.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import { getMachineContext } from '$lib/machines/context';
	import { SetupFlow } from '$lib/setup/flow.svelte';
	import { isStepId, stepsFor, type StepDefinition, type StepId } from '$lib/setup/steps';

	type StepProps = { flow: SetupFlow; onnext: () => void; ongoto: (id: StepId) => void };

	// The sharing step is the notice Settings › Hive shows too, with props of its own.
	const BODIES: Record<Exclude<StepId, 'sharing'>, Component<StepProps>> = {
		identity: IdentityStep,
		theme: ThemeStep,
		boards: BoardsStep,
		chute: ChuteStep,
		motors: MotorsStep,
		home: ChuteHomeStep,
		bins: BinsStep,
		discard: DiscardStep,
		doors: DoorsStep,
		cameras: CamerasStep,
		hive: HiveStep,
		done: DoneStep
	};

	const machine = getMachineContext();
	const flow = new SetupFlow(machine);

	const ctx = $derived(flow.context);
	const steps = $derived(stepsFor(ctx));
	const requested = $derived(page.url.searchParams.get('step'));
	const step = $derived<StepDefinition>(steps.find((entry) => entry.id === requested) ?? steps[0]);
	const index = $derived(steps.indexOf(step));
	const status = $derived(ctx ? step.status(ctx) : { done: false, blocker: null });
	const Body = $derived(step.id === 'sharing' ? null : BODIES[step.id]);

	let advancing = $state(false);

	function statusOf(id: string): 'current' | 'done' | 'ready' {
		if (id === step.id) return 'current';
		const entry = steps.find((candidate) => candidate.id === id);
		return entry && ctx && entry.status(ctx).done ? 'done' : 'ready';
	}

	function go(id: string, replaceState = false) {
		const params = new URLSearchParams(page.url.searchParams);
		params.set('step', id);
		void goto(`${page.url.pathname}?${params}`, { replaceState, noScroll: false, keepFocus: true });
	}

	function next() {
		const following = steps[index + 1];
		if (following) go(following.id);
	}

	async function onContinue() {
		advancing = true;
		try {
			if (flow.beforeNext && !(await flow.beforeNext())) return;
			if (step.id === 'done') {
				flow.mark({ finished: true });
				await goto('/');
				return;
			}
			next();
		} finally {
			advancing = false;
		}
	}

	// A step named in the address that does not apply to this machine (or no
	// step at all) opens the first one.
	$effect(() => {
		if (ctx && !isStepId(requested)) go(steps[0].id, true);
		else if (ctx && requested !== step.id) go(step.id, true);
	});

	// The summary follows the machine: load it for each machine, and again
	// whenever its hardware changes state (it powered up, it homed, it failed).
	let loadedFor = '';
	let lastState = '';
	$effect(() => {
		const key = `${machine.machine?.url ?? ''}`;
		if (key === loadedFor) return;
		loadedFor = key;
		void flow.reload();
	});
	$effect(() => {
		const state = machine.machine?.systemStatus?.hardware_state ?? '';
		if (!state || state === lastState) return;
		const first = lastState === '';
		lastState = state;
		if (!first) void flow.reload();
	});
</script>

<svelte:head><title>Sorter - Setup</title></svelte:head>

<AppShell>
	<div class="mx-auto flex w-full max-w-6xl flex-col gap-(--gap-panels) px-4 py-6 sm:px-6">
		{#if !machine.machine}
			<PageHeader
				title="Setup"
				description="Choose or connect a machine first. Then this walks through its setup one step at a time."
			/>
		{:else if !flow.summary}
			<PageHeader title="Setup" description="Every step of setting up this machine, one at a time." />
			{#if flow.error}
				<Alert tone="danger" title="The setup did not load">
					{flow.error}
					{#snippet actions()}
						<Button size="sm" icon={RefreshCcw} loading={flow.loading} onclick={() => void flow.reload()}>
							Try again
						</Button>
					{/snippet}
				</Alert>
			{:else}
				<Panel>
					<p class="flex items-center gap-2 text-sm text-ink-muted">
						<Spinner size={16} />
						Checking the machine's settings and what is plugged in
					</p>
				</Panel>
			{/if}
		{:else}
			<SetupStepperNav {steps} getStatus={statusOf} onSelect={(id) => go(id)} />
			<PageHeader title={step.title} description={step.description} />
			{#if flow.error}
				<Alert tone="warning" title="The machine's setup did not refresh">
					{flow.error} What is shown may be out of date.
					{#snippet actions()}
						<Button size="sm" icon={RefreshCcw} loading={flow.loading} onclick={() => void flow.reload()}>
							Try again
						</Button>
					{/snippet}
				</Alert>
			{/if}

			{#key step.id}
				{#if step.id === 'sharing'}
					<SharingStep base={flow.base} onagreed={() => void flow.reload().then(next)} />
				{:else if Body}
					<Body {flow} onnext={next} ongoto={(id: StepId) => go(id)} />
				{/if}
			{/key}

			<SetupNavFooter
				blocker={status.blocker ?? null}
				showBack={index > 0}
				showContinue={!step.ownContinue}
				finish={step.id === 'done'}
				busy={advancing}
				onBack={() => index > 0 && go(steps[index - 1].id)}
				{onContinue}
			/>
		{/if}
	</div>
</AppShell>
