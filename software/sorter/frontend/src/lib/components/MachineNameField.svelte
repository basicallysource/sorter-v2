<script lang="ts">
	// Everywhere this Sorter asks for a machine name: the setup wizard's naming
	// step, and both Hive forms in settings. Each one starts from the name the
	// machine already has for itself and offers another roll, so the three stay
	// one behaviour rather than three that drift.
	import { onMount } from 'svelte';
	import Shuffle from '@lucide/svelte/icons/shuffle';
	import Input from '$lib/components/ui/Input.svelte';
	import Button from '$lib/components/ui/Button.svelte';

	let {
		value = $bindable(),
		backendBaseUrl,
		id,
		placeholder = '',
		size = 'md'
	}: {
		value: string;
		backendBaseUrl: string;
		id?: string;
		placeholder?: string;
		size?: 'md' | 'lg';
	} = $props();

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

<Input {id} {size} bind:value {placeholder}>
	{#snippet end()}
		<Button
			variant="ghost"
			size="sm"
			icon={Shuffle}
			label="Suggest another name"
			onclick={() => void fill(true)}
		/>
	{/snippet}
</Input>
