<script lang="ts">
	// Where a piece would go under the profile this machine runs now, kit counts
	// included. Nothing moves: it only asks.
	import Search from '@lucide/svelte/icons/search';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Field from '$lib/components/ui/Field.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import ProfileBin, { type Bin } from '$lib/components/ui/ProfileBin.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import { fetchLegoColors, type BrickLinkColor } from '$lib/pieces/colors';

	let { baseUrl }: { baseUrl: string } = $props();

	// The machine's BrickLink palette, by name; the value is the color's ID.
	let colors = $state<BrickLinkColor[]>([]);
	$effect(() => {
		fetchLegoColors(baseUrl)
			.then((list) => (colors = list))
			.catch(() => (colors = []));
	});
	const colorOptions = $derived([
		{ value: '', label: 'Any color' },
		...colors.map((c) => ({ value: String(c.id), label: c.name, hint: String(c.id) }))
	]);
	const colorName = (id: string) => colors.find((c) => String(c.id) === id)?.name ?? `color ${id}`;

	type Answer = { category_id: string; category_name: string; bin: Partial<Bin> | null };

	let part = $state('');
	let color = $state('');
	let checking = $state(false);
	let error = $state<string | null>(null);
	let answer = $state<{ part: string; color: string; result: Answer } | null>(null);

	async function check(event: Event) {
		event.preventDefault();
		// A number field gives a number.
		const partId = String(part ?? '').trim();
		const colorId = String(color ?? '').trim();
		if (!partId) return;
		checking = true;
		error = null;
		try {
			const url = new URL(`${baseUrl}/api/sorting-profiles/route`);
			url.searchParams.set('part_id', partId);
			if (colorId) url.searchParams.set('color_id', colorId);
			const res = await fetch(url.toString());
			if (!res.ok) {
				const body = (await res.json().catch(() => null)) as { detail?: string } | null;
				throw new Error(body?.detail ?? `HTTP ${res.status}`);
			}
			answer = { part: partId, color: colorId, result: (await res.json()) as Answer };
		} catch (e: unknown) {
			answer = null;
			error = e instanceof Error ? e.message : 'Could not ask the profile';
		} finally {
			checking = false;
		}
	}

	// A profile saved before bins were described has no description for the bin:
	// the category's name is all there is.
	const bin = $derived<Bin | null>(
		answer
			? answer.result.bin && answer.result.bin.name
				? (answer.result.bin as Bin)
				: { name: answer.result.category_name }
			: null
	);
</script>

<Panel
	title="Where would a piece go?"
	description="Asks the profile this machine runs. Nothing moves."
>
	<form class="flex flex-col gap-3" onsubmit={check}>
		<div class="grid gap-3 sm:grid-cols-[1fr_12rem]">
			<Field label="BrickLink part" for="route-part">
				<Input id="route-part" placeholder="Like 3001" autocomplete="off" bind:value={part} />
			</Field>
			<Field label="Color" for="route-color" help="Type a name to jump to it.">
				<Select id="route-color" options={colorOptions} bind:value={color} />
			</Field>
		</div>
		<div>
			<Button
				type="submit"
				variant="primary"
				icon={Search}
				loading={checking}
				disabled={!String(part ?? '').trim()}
			>
				Where does it go
			</Button>
		</div>
	</form>

	{#if error}
		<Alert tone="warning" class="mt-3">{error}</Alert>
	{:else if answer && bin}
		<div class="mt-3 flex flex-col gap-1.5">
			<p class="text-sm text-ink-muted">
				<span class="num font-medium text-ink">{answer.part}</span>{answer.color
					? ` in ${colorName(answer.color)}`
					: ''} goes to
			</p>
			<div class="overflow-hidden rounded-control bg-well">
				<ProfileBin layout="row" {bin} plane="well" />
			</div>
		</div>
	{/if}
</Panel>
