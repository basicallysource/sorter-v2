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

	const field = 'setup-control w-full min-w-0 px-3 text-base';
</script>

<form class="flex flex-col gap-5" onsubmit={submit} novalidate>
	<button
		type="button"
		class="-my-2 -ml-2 inline-flex min-h-11 items-center gap-1 self-start px-2 text-sm font-medium text-text-muted hover:text-text"
		onclick={onback}
	>
		<ChevronLeft size={16} />
		All networks
	</button>

	{#if failure}
		<Alert variant="danger">
			<p class="font-medium">{joinFailure(failure)}</p>
			{#if failure.reason === 'other' && failure.detail}
				<p class="text-text-muted">{failure.detail}</p>
			{/if}
		</Alert>
	{/if}

	{#if target.hidden}
		<h1 class="text-2xl font-bold text-text">Other network</h1>
		<div>
			<label for="ssid" class="mb-1.5 block text-sm font-medium text-text">Network name</label>
			<input
				id="ssid"
				bind:this={ssidInput}
				bind:value={ssid}
				class={field}
				autocomplete="off"
				autocapitalize="off"
				autocorrect="off"
				spellcheck="false"
				aria-invalid={problems.ssid ? 'true' : undefined}
			/>
			{#if problems.ssid}<p class="mt-1.5 text-sm text-danger">{problems.ssid}</p>{/if}
		</div>
	{:else}
		<div>
			<h1 class="text-2xl font-bold break-words text-text">{target.ssid}</h1>
			{#if open}<p class="mt-1 text-sm text-text-muted">Open network. No password needed.</p>{/if}
		</div>
	{/if}

	{#if !open}
		<div>
			<label for="password" class="mb-1.5 block text-sm font-medium text-text">Password</label>
			<div class="flex">
				<input
					id="password"
					bind:this={passwordInput}
					bind:value={password}
					type={showPassword ? 'text' : 'password'}
					class={field}
					autocomplete="off"
					autocapitalize="off"
					autocorrect="off"
					spellcheck="false"
					enterkeyhint="go"
					aria-invalid={problems.password ? 'true' : undefined}
				/>
				<button
					type="button"
					class="setup-button-secondary -ml-px min-h-11 w-18 shrink-0 text-sm font-medium text-text"
					aria-pressed={showPassword}
					onclick={() => (showPassword = !showPassword)}
				>
					{showPassword ? 'Hide' : 'Show'}
				</button>
			</div>
			{#if problems.password}
				<p class="mt-1.5 text-sm text-danger">{problems.password}</p>
			{:else if target.hidden}
				<p class="mt-1.5 text-sm text-text-muted">Leave it empty if the network is open.</p>
			{/if}
		</div>
	{/if}

	<div>
		<button
			type="button"
			class="-my-2 -ml-2 inline-flex min-h-11 items-center gap-1 px-2 text-sm font-medium text-text-muted hover:text-text"
			aria-expanded={naming}
			onclick={() => (naming = !naming)}
		>
			<ChevronRight size={16} class="transition-transform {naming ? 'rotate-90' : ''}" />
			Name this Sorter
		</button>
		{#if naming}
			<input
				bind:this={nameInput}
				bind:value={name}
				class="{field} mt-3"
				placeholder={currentName}
				aria-label="Name this Sorter"
				autocomplete="off"
				autocapitalize="off"
				autocorrect="off"
				spellcheck="false"
				aria-invalid={problems.name ? 'true' : undefined}
			/>
			<p class="mt-1.5 text-sm {problems.name ? 'text-danger' : 'text-text-muted'}">
				{problems.name ?? 'Lowercase letters, digits and dashes.'}
			</p>
		{/if}
	</div>

	{#if error}
		<Alert variant="danger">{error}</Alert>
	{/if}

	<Button variant="primary" type="submit" wide loading={busy}>Join</Button>
</form>
