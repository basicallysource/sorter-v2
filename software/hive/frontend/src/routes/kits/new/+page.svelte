<script lang="ts">
	import { goto } from '$app/navigation';
	import { api } from '$lib/api';
	import Alert from '$lib/components/Alert.svelte';
	import Button from '$lib/components/Button.svelte';
	import Checkbox from '$lib/components/Checkbox.svelte';
	import Field from '$lib/components/Field.svelte';
	import Input from '$lib/components/Input.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import RadioGroup from '$lib/components/RadioGroup.svelte';
	import KitPicture from '$lib/components/profile/KitPicture.svelte';
	import SetSearch from '$lib/components/profile/SetSearch.svelte';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import Upload from '@lucide/svelte/icons/upload';

	type How = 'hand' | 'set' | 'list';
	type SetResult = { set_num: string; name: string; year: number; num_parts: number; img_url: string | null };

	let how = $state<How>('hand');
	let name = $state('');
	let nameTouched = false;
	let creating = $state(false);
	let error = $state<string | null>(null);

	let chosenSet = $state<SetResult | null>(null);
	let includeSpares = $state(false);

	let fileInput = $state<HTMLInputElement>();
	let fileName = $state<string | null>(null);
	let csv = $state('');

	const ready = $derived(
		how === 'hand' ? name.trim().length > 0 : how === 'set' ? chosenSet !== null : csv.trim().length > 0
	);

	// A name suggested from what was chosen, until the person types their own.
	function suggest(text: string) {
		if (!nameTouched) name = text;
	}

	function chooseSet(set: SetResult) {
		chosenSet = set;
		suggest(set.name);
	}

	async function chooseFile(event: Event) {
		const input = event.currentTarget as HTMLInputElement;
		const file = input.files?.[0];
		input.value = '';
		if (!file) return;
		error = null;
		try {
			csv = await file.text();
			fileName = file.name;
			suggest(file.name.replace(/\.[^.]+$/, ''));
		} catch {
			error = 'Could not read that file.';
		}
	}

	async function create(event: Event) {
		event.preventDefault();
		if (creating || !ready) return;
		creating = true;
		error = null;
		try {
			const title = name.trim() || null;
			if (how === 'hand') {
				const kit = await api.createKit({ name: title ?? 'Untitled kit', parts: [] });
				await goto(`/kits/${kit.id}`);
			} else if (how === 'set' && chosenSet) {
				const kit = await api.createKitFromSet({
					set_num: chosenSet.set_num,
					include_spares: includeSpares,
					name: title
				});
				await goto(`/kits/${kit.id}`);
			} else {
				const kit = await api.createKitFromBricklinkCsv({ csv_content: csv, filename: fileName, name: title });
				try {
					// The kit's page tells what the list left out.
					sessionStorage.setItem(`kit-import:${kit.id}`, JSON.stringify(kit.warnings));
				} catch {
					/* the page just will not say */
				}
				await goto(`/kits/${kit.id}`);
			}
		} catch (e: any) {
			error = e.error || 'Could not make the kit.';
			creating = false;
		}
	}
</script>

<svelte:head><title>New kit - Hive</title></svelte:head>

<div class="mx-auto flex w-full max-w-xl flex-col gap-(--gap-panels)">
	<div>
		<Button href="/kits" size="sm" variant="ghost" icon={ArrowLeft}>Kits</Button>
	</div>

	<PageHeader title="New kit" description="Choose how to start, then name it." />

	{#if error}<Alert tone="danger">{error}</Alert>{/if}

	<Panel>
		<form id="new-kit" onsubmit={create} class="flex flex-col gap-5">
			<RadioGroup
				name="kit-source"
				label="How to start"
				bind:value={how}
				options={[
					{ value: 'hand', label: 'By hand', help: 'Name it, then add parts with their colors and quantities.' },
					{ value: 'set', label: 'From a LEGO set', help: "Every part of a set, in the set's colors." },
					{
						value: 'list',
						label: 'From a BrickLink list',
						help: 'A wanted list saved as a CSV file, with the columns BLItemNo, BLColorId and Qty.'
					}
				]}
			/>

			{#if how === 'set'}
				{#if chosenSet}
					<div class="flex items-center gap-3">
						<KitPicture src={chosenSet.img_url} class="size-14 shrink-0" />
						<span class="min-w-0 flex-1 text-sm">
							<span class="block truncate font-medium text-ink">{chosenSet.name}</span>
							<span class="block text-ink-muted"
								><span class="num">{chosenSet.set_num}</span>, {chosenSet.year},
								<span class="num">{chosenSet.num_parts.toLocaleString('en-US')}</span> parts</span
							>
						</span>
						<Button size="sm" variant="ghost" onclick={() => (chosenSet = null)}>Change</Button>
					</div>
					<Checkbox bind:checked={includeSpares}>Include spare parts</Checkbox>
				{:else}
					<SetSearch title="Find a LEGO set" onSelect={chooseSet} />
				{/if}
			{:else if how === 'list'}
				<div class="flex flex-wrap items-center gap-3">
					<Button icon={Upload} onclick={() => fileInput?.click()}>{fileName ? 'Choose another file' : 'Choose a file'}</Button>
					{#if fileName}
						<span class="min-w-0 truncate text-sm text-ink">{fileName}</span>
					{:else}
						<span class="text-sm text-ink-muted">Hive reads the file in your browser, then sends its rows.</span>
					{/if}
					<input
						bind:this={fileInput}
						type="file"
						accept=".csv,text/csv,text/plain"
						class="hidden"
						onchange={chooseFile}
					/>
				</div>
			{/if}

			<Field
				label="Name"
				for="kit-name"
				help={how === 'hand' ? undefined : 'Left empty, the kit is named for its set or its file.'}
			>
				<Input
					id="kit-name"
					bind:value={name}
					oninput={() => (nameTouched = true)}
					placeholder={how === 'hand' ? 'For example: Order 42' : undefined}
				/>
			</Field>
		</form>
		{#snippet footer()}
			<Button href="/kits" variant="ghost">Cancel</Button>
			<Button type="submit" form="new-kit" variant="primary" loading={creating} disabled={!ready}>Create kit</Button>
		{/snippet}
	</Panel>
</div>
