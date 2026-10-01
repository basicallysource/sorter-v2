<script lang="ts" module>
	/** The network the form is for. `hidden` is "Other network": the person
	 *  types its name, and `ssid` is only what the field starts with. */
	export type Target = { ssid: string; security: string; hidden: boolean };

	export type JoinDraft = { ssid: string; password: string; hidden: boolean; name: string };
</script>

<script lang="ts">
	import ChevronLeft from '@lucide/svelte/icons/chevron-left';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import type { Join } from '$lib/api';
	import { joinFailure } from '$lib/words';
	import Alert from './Alert.svelte';
	import Button from './Button.svelte';
	import Input from './Input.svelte';

	let {
		target,
		failure,
		currentName,
		busy,
		error,
		ssid = $bindable(),
		password = $bindable(),
		name = $bindable(),
		naming = $bindable(),
		onback,
		onjoin
	}: {
		target: Target;
		/** The last join, when it failed for this network. */
		failure: Join | null;
		currentName: string;
		busy: boolean;
		error: string | null;
		ssid: string;
		password: string;
		name: string;
		naming: boolean;
		onback: () => void;
		onjoin: (draft: JoinDraft) => void;
	} = $props();

	const open = $derived(!target.hidden && target.security.trim() === '');

	let ssidInput = $state<HTMLInputElement>();
	let passwordInput = $state<HTMLInputElement>();
	let nameInput = $state<HTMLInputElement>();
	let showPassword = $state(false);
	let problems = $state<{ ssid?: string; password?: string; name?: string }>({});

	/** The field the person needs next. */
	export function focusFirst() {
		(target.hidden && !ssid.trim() ? ssidInput : passwordInput)?.focus();
	}

	// The same rules the Sorter applies, so a typo is caught before it tries.
	const NAME = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/;

	function submit(event: SubmitEvent) {
		event.preventDefault();
		const wanted = target.hidden ? ssid.trim() : target.ssid;
		const newName = name.trim().toLowerCase();
		problems = {};
		if (!wanted) problems.ssid = "Type the network's name.";
		if (!open && (password.length > 0 || !target.hidden) && (password.length < 8 || password.length > 63)) {
			problems.password = 'Wi-Fi passwords are 8 to 63 characters.';
		}
		if (newName && (newName.length > 63 || !NAME.test(newName))) {
			problems.name = 'Use lowercase letters, digits and dashes.';
		}
		if (problems.ssid) return ssidInput?.focus();
		if (problems.password) return passwordInput?.focus();
		if (problems.name) return nameInput?.focus();
		onjoin({ ssid: wanted, password: open ? '' : password, hidden: target.hidden, name: newName });
	}


</script>

<form class="flex flex-col gap-5" onsubmit={submit} novalidate>
	<div class="-ml-3 self-start">
		<Button variant="ghost" icon={ChevronLeft} onclick={onback}>All networks</Button>
	</div>

	{#if failure}
		<Alert tone="danger" title={joinFailure(failure)}>
			{#if failure.reason === 'other' && failure.detail}
				<span class="text-ink-muted">{failure.detail}</span>
			{/if}
		</Alert>
	{/if}

	{#if target.hidden}
		<h1 class="text-2xl font-semibold tracking-tight text-ink">Other network</h1>
		<div class="flex flex-col gap-1.5">
			<label for="ssid" class="text-sm font-medium text-ink">Network name</label>
			<Input
				id="ssid"
				bind:element={ssidInput}
				bind:value={ssid}
				class="text-base"
				autocomplete="off"
				autocapitalize="off"
				autocorrect="off"
				spellcheck="false"
				invalid={!!problems.ssid}
			/>
			{#if problems.ssid}<p class="text-sm text-danger-ink">{problems.ssid}</p>{/if}
		</div>
	{:else}
		<div>
			<h1 class="text-2xl font-semibold tracking-tight break-words text-ink">{target.ssid}</h1>
			{#if open}<p class="mt-1 text-sm text-ink-muted">Open network. No password needed.</p>{/if}
		</div>
	{/if}

	{#if !open}
		<div class="flex flex-col gap-1.5">
			<label for="password" class="text-sm font-medium text-ink">Password</label>
			<Input
				id="password"
				bind:element={passwordInput}
				bind:value={password}
				type={showPassword ? 'text' : 'password'}
				autocomplete="off"
				autocapitalize="off"
				autocorrect="off"
				spellcheck="false"
				enterkeyhint="go"
				invalid={!!problems.password}
			>
				{#snippet end()}
					<Button
						size="sm"
						variant="ghost"
						aria-pressed={showPassword}
						onclick={() => (showPassword = !showPassword)}>{showPassword ? 'Hide' : 'Show'}</Button
					>
				{/snippet}
			</Input>
			{#if problems.password}
				<p class="text-sm text-danger-ink">{problems.password}</p>
			{:else if target.hidden}
				<p class="text-sm text-ink-muted">Leave it empty if the network is open.</p>
			{/if}
		</div>
	{/if}

	<div>
		<button
			type="button"
			class="-ml-1 inline-flex h-(--size-control) items-center gap-1 px-1 text-sm font-medium text-ink-muted hover:text-ink"
			aria-expanded={naming}
			onclick={() => (naming = !naming)}
		>
			<ChevronRight size={16} class="transition-transform {naming ? 'rotate-90' : ''}" />
			Name this Sorter
		</button>
		{#if naming}
			<div class="mt-2 flex flex-col gap-1.5">
				<Input
					bind:element={nameInput}
					bind:value={name}
					placeholder={currentName}
					aria-label="Name this Sorter"
					autocomplete="off"
					autocapitalize="off"
					autocorrect="off"
					spellcheck="false"
					invalid={!!problems.name}
				/>
				<p class="text-sm {problems.name ? 'text-danger-ink' : 'text-ink-muted'}">
					{problems.name ?? 'Lowercase letters, digits and dashes.'}
				</p>
			</div>
		{/if}
	</div>

	{#if error}
		<Alert tone="danger">{error}</Alert>
	{/if}

	<Button variant="primary" type="submit" size="lg" class="w-full" loading={busy}>Join</Button>
</form>
