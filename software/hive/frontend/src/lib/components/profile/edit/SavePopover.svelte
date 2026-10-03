<!--
	Saving a version: the button, and under it a note on what changed (the
	assistant suggests one when it has a key and the rules changed). Saving makes
	the draft the newest version; it does not publish anything.
-->
<script lang="ts">
	import { tick, untrack } from 'svelte';
	import Save from '@lucide/svelte/icons/save';
	import { api } from '$lib/api';
	import Button from '$lib/components/Button.svelte';
	import Field from '$lib/components/Field.svelte';
	import Input from '$lib/components/Input.svelte';
	import Popover from '$lib/components/Popover.svelte';
	import type { Rule } from './rules';

	let {
		open = $bindable(false),
		profileId,
		hasOpenRouter,
		savedRules,
		draftRules,
		dirty,
		saving,
		onsave
	}: {
		open?: boolean;
		profileId: string;
		hasOpenRouter: boolean;
		// The rules as last saved, and as they stand.
		savedRules: Rule[];
		draftRules: Rule[];
		dirty: boolean;
		saving: boolean;
		onsave: (note: string | null) => void;
	} = $props();

	const uid = $props.id();

	let note = $state('');
	let field = $state<HTMLInputElement | undefined>();
	let suggesting = $state(false);
	let suggestError = $state<string | null>(null);

	// Each time it opens the note starts empty, and a suggestion fills it in.
	$effect(() => {
		if (!open) return;
		untrack(() => void suggest());
		void tick().then(() => field?.focus());
	});

	async function suggest() {
		note = '';
		suggesting = false;
		suggestError = null;
		if (!hasOpenRouter || JSON.stringify(savedRules) === JSON.stringify(draftRules)) return;
		suggesting = true;
		try {
			const result = await api.suggestChangeNote(profileId, { old_rules: savedRules, new_rules: draftRules });
			if (open && !note) note = result.change_note;
		} catch (e) {
			suggestError = (e as { error?: string })?.error ?? 'A note could not be suggested.';
		}
		suggesting = false;
	}
</script>

<Popover label="Save a new version" placement="bottom-end" width="22rem" bind:open>
	{#snippet trigger(props)}
		<Button {...props} variant="primary" icon={Save} disabled={!dirty || saving}>Save</Button>
	{/snippet}
	<form
		class="flex flex-col gap-3"
		onsubmit={(e) => {
			e.preventDefault();
			onsave(note.trim() || null);
		}}
	>
		<Field
			label="What changed?"
			for="{uid}-note"
			help={suggesting ? 'Writing a suggestion.' : 'Optional.'}
			error={suggestError ?? undefined}
		>
			<Input
				id="{uid}-note"
				bind:element={field}
				bind:value={note}
				autocomplete="off"
				placeholder={suggesting ? 'Writing a suggestion' : 'For example: added gear categories'}
			/>
		</Field>
		<div class="flex justify-end gap-2">
			<Button variant="ghost" size="sm" onclick={() => (open = false)}>Cancel</Button>
			<Button type="submit" variant="primary" size="sm" loading={saving}>Save version</Button>
		</div>
	</form>
</Popover>
