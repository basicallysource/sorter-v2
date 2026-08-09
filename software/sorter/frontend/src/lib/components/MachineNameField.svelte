<script lang="ts">
	// Everywhere this Sorter asks for a machine name: the setup wizard's naming
	// step, and both Hive forms in settings. Each one starts from the name the
	// machine already has for itself and offers another roll, so the three stay
	// one behaviour rather than three that drift.
	import { onMount } from 'svelte';
	import { Shuffle } from 'lucide-svelte';

	let {
		value = $bindable(),
		backendBaseUrl,
		id,
		placeholder = '',
		variant = 'settings'
	}: {
		value: string;
		backendBaseUrl: string;
		id?: string;
		placeholder?: string;
		variant?: 'setup' | 'settings';
	} = $props();

	const inputClass = $derived(
		variant === 'setup'
			? 'setup-control min-w-0 flex-1 px-3 py-2 text-sm text-text'
			: 'min-w-0 flex-1 border border-border bg-bg px-2 py-1.5 text-sm text-text'
	);
	const buttonClass = $derived(
		variant === 'setup'
			? 'setup-control flex shrink-0 items-center gap-2 px-3 text-sm whitespace-nowrap text-text-muted transition-colors hover:text-text'
			: 'flex shrink-0 items-center gap-2 border border-border bg-bg px-2 py-1.5 text-sm whitespace-nowrap text-text-muted transition-colors hover:bg-surface hover:text-text'
	);

	// `roll` is the button: it wants a name nobody has seen yet, so it
	// overwrites the field rather than only filling an empty one.
	async function fill(roll: boolean) {
		if (!roll && value.trim()) return;
		try {
			const res = await fetch(
				`${backendBaseUrl}/api/settings/hive/suggested-machine-name${roll ? '?roll=1' : ''}`
			);
			if (!res.ok) return;
			const data = await res.json();
			const suggestion = typeof data?.name === 'string' ? data.name.trim() : '';
			if (suggestion && (roll || !value.trim())) value = suggestion;
		} catch {
			// Leave the field as it is; every form here still takes typing.
		}
	}

	onMount(() => {
		void fill(false);
	});
</script>

<div class="flex items-stretch gap-2">
	<input {id} type="text" bind:value {placeholder} class={inputClass} />
	<button type="button" onclick={() => void fill(true)} class={buttonClass}>
		<Shuffle class="h-4 w-4" />
		Generate New Name
	</button>
</div>
