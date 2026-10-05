<script lang="ts">
	import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
	import Pause from '@lucide/svelte/icons/pause';
	import House from '@lucide/svelte/icons/house';
	import Pencil from '@lucide/svelte/icons/pencil';
	import Copy from '@lucide/svelte/icons/copy';
	import Trash from '@lucide/svelte/icons/trash-2';
	import Ellipsis from '@lucide/svelte/icons/ellipsis';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import CircleUser from '@lucide/svelte/icons/circle-user';
	import Settings from '@lucide/svelte/icons/settings';
	import Users from '@lucide/svelte/icons/users';
	import Cpu from '@lucide/svelte/icons/cpu';
	import LogOut from '@lucide/svelte/icons/log-out';
	import PageHeader from '$lib/site/PageHeader.svelte';
	import SiteSection from '$lib/site/SiteSection.svelte';
	import Specimen from '$lib/site/Specimen.svelte';
	import Button from '$lib/components/Button.svelte';
	import Popover from '$lib/components/Popover.svelte';
	import Menu from '$lib/components/Menu.svelte';
	import Tooltip from '$lib/components/Tooltip.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import Field from '$lib/components/Field.svelte';
	import Input from '$lib/components/Input.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Sheet from '$lib/components/Sheet.svelte';
	import Lightbox from '$lib/components/Lightbox.svelte';
	import PartTile from '$lib/components/PartTile.svelte';
	import ExternalLink from '@lucide/svelte/icons/external-link';

	let profile = $state('september');
	let contextMenu: Menu | undefined = $state();
	let last = $state('');
	let confirmOpen = $state(false);
	let restarting = $state(false);
	let renameOpen = $state(false);
	let profileName = $state('September');

	const sheetParts = [
		{ partNum: '3001', name: 'Brick 2 x 4', color: { name: 'Red', rgb: 'C91A09' }, ldraw: 4, quantity: 12 },
		{ partNum: '3004', name: 'Brick 1 x 2', color: { name: 'White', rgb: 'FFFFFF' }, ldraw: 15, quantity: 30 },
		{ partNum: '3022', name: 'Plate 2 x 2', color: { name: 'Black', rgb: '05131D' }, ldraw: 0, quantity: 24 },
		{ partNum: '3069b', name: 'Tile 1 x 2', color: { name: 'Light Bluish Gray', rgb: 'A0A5A9' }, ldraw: 71, quantity: 8 }
	];
	let picked = $state<(typeof sheetParts)[number] | null>(null);
	let zoomed = $state<{ src: string; alt: string } | null>(null);
	const render = (num: string, color: number) => `https://cdn.rebrickable.com/media/parts/ldraw/${color}/${num}.png`;

	function restart() {
		restarting = true;
		setTimeout(() => {
			restarting = false;
			confirmOpen = false;
			last = 'Restart backend';
		}, 4000);
	}

	const profiles = [
		{ id: 'september', name: 'September' },
		{ id: 'bulk', name: 'Bulk by color' },
		{ id: 'technic', name: 'Technic parts' }
	];
</script>

<svelte:head><title>Overlays · Sorter design system</title></svelte:head>

<div class="flex items-start gap-6">
	<div class="flex min-w-0 flex-1 flex-col">
		<PageHeader
			title="Overlays"
			lead="What floats over the page: the popover, the menu, the select's list, the tooltip, the modal and the sheet. All of them are the raised plane: a fill and one line, and no shadow."
			doc="overlays"
		/>

		<SiteSection
			title="Popover"
			lead="A little content that opens from a button: a picker, a short form, a longer explanation. It closes on a click outside or Escape."
		>
			<Specimen
				code={`<Popover label="Camera exposure">
	{#snippet trigger(props)}<Button {...props}>Exposure</Button>{/snippet}
	...
</Popover>`}
			>
				<Popover label="Camera exposure" width="18rem">
					{#snippet trigger(props)}
						<Button {...props}>Exposure<ChevronDown size={16} /></Button>
					{/snippet}
					<Field
						label="Exposure"
						for="pop-exposure"
						help="In milliseconds. Multiples of 8.33 avoid banding under LED light."
					>
						<Input id="pop-exposure" type="number" value={16.66} unit="ms" />
					</Field>
				</Popover>
			</Specimen>
		</SiteSection>

		<SiteSection
			title="Menu"
			lead="Actions or links from one button. The arrow keys move, Enter chooses, Escape closes. The destructive item comes last, after a line, and asks first. A group's name sits over its items, as a label."
		>
			<Specimen
				code={`<Menu label="Machine" items={[
	{ label: 'Pause', icon: Pause, onselect: pause },
	{ label: 'Home again', icon: House, onselect: home },
	'separator',
	{ label: 'Restart backend', icon: RotateCcw, danger: true, onselect: confirm }
]}>
	{#snippet trigger(props)}<Button {...props} icon={Ellipsis} label="Machine" />{/snippet}
</Menu>`}
			>
				<div class="flex flex-wrap items-center gap-4">
					<Menu
						label="Machine"
						placement="bottom-start"
						items={[
							{ label: 'Pause', icon: Pause, hint: 'Space', onselect: () => (last = 'Pause') },
							{ label: 'Home again', icon: House, onselect: () => (last = 'Home again') },
							'separator',
							{
								label: 'Restart backend',
								icon: RotateCcw,
								danger: true,
								onselect: () => (confirmOpen = true)
							}
						]}
					>
						{#snippet trigger(props)}
							<Button {...props} icon={Ellipsis} label="Machine" />
						{/snippet}
					</Menu>
					<Menu
						label="Sorting profile"
						placement="bottom-start"
						items={profiles.map((p) => ({
							label: p.name,
							checked: p.id === profile,
							onselect: () => (profile = p.id)
						}))}
					>
						{#snippet trigger(props)}
							<Button {...props}>
								{profiles.find((p) => p.id === profile)?.name}<ChevronDown size={16} />
							</Button>
						{/snippet}
					</Menu>
					<Menu
						label="Account"
						placement="bottom-start"
						items={[
							{ label: 'Your settings', icon: Settings, onselect: () => (last = 'Your settings') },
							'separator',
							{
								group: 'Admin',
								items: [
									{ label: 'Users', icon: Users, onselect: () => (last = 'Users') },
									{ label: 'Machines', icon: Cpu, onselect: () => (last = 'Machines') }
								]
							},
							'separator',
							{ label: 'Sign out', icon: LogOut, onselect: () => (last = 'Sign out') }
						]}
					>
						{#snippet trigger(props)}
							<Button {...props} variant="ghost" icon={CircleUser} label="Account" />
						{/snippet}
					</Menu>
					<Menu
						label="Profile"
						placement="bottom-start"
						items={[
							{ label: 'Rename', icon: Pencil, onselect: () => (renameOpen = true) },
							{ label: 'Duplicate', icon: Copy, onselect: () => (last = 'Duplicate') },
							'separator',
							{ label: 'Delete', icon: Trash, danger: true, onselect: () => (last = 'Delete') }
						]}
					>
						{#snippet trigger(props)}
							<Button {...props} variant="ghost" icon={Ellipsis} label="More" />
						{/snippet}
					</Menu>
					{#if last}<span class="text-sm text-ink-muted">Chose: {last}</span>{/if}
				</div>
			</Specimen>
			<Specimen
				code={`<Menu bind:this={menu} label="Bin" items={[...]} />
<div oncontextmenu={(e) => { e.preventDefault(); menu.openAt(e); }}>...</div>`}
			>
				<Menu
					bind:this={contextMenu}
					label="Bin"
					items={[
						{ label: 'Point the chute here', onselect: () => (last = 'Point the chute here') },
						{ label: 'Show what is in it', onselect: () => (last = 'Show what is in it') }
					]}
				/>
				<div
					role="presentation"
					class="flex h-28 items-center justify-center rounded-panel bg-well text-sm text-ink-muted"
					oncontextmenu={(e) => {
						e.preventDefault();
						contextMenu?.openAt(e);
					}}
				>
					Right-click here
				</div>
			</Specimen>
		</SiteSection>

		<SiteSection
			title="Tooltip"
			lead="A name for something with no room for one: a cut-off value, a status dot. Not for explaining a setting; that is written under it."
		>
			<Specimen
				code={`<Tooltip text="Plate, Round 1 x 1 with Flower Edge">
	{#snippet children(props)}<a {...props} href="/parts/24866" class="truncate">...</a>{/snippet}
</Tooltip>`}
			>
				<div class="flex flex-wrap items-center gap-6">
					<div class="w-48">
						<Tooltip text="Plate, Round 1 x 1 with Flower Edge">
							{#snippet children(props)}
								<a {...props} href="#tooltip" class="block truncate text-sm text-ink hover:underline"
									>Plate, Round 1 x 1 with Flower Edge</a
								>
							{/snippet}
						</Tooltip>
					</div>
					<Tooltip text="Connected, last message 2 seconds ago">
						{#snippet children(props)}
							<button {...props} type="button" class="inline-flex">
								<Badge tone="success" dot>Online</Badge>
							</button>
						{/snippet}
					</Tooltip>
					<Button variant="ghost" icon={Pencil} label="Rename profile" />
				</div>
			</Specimen>
		</SiteSection>

		<SiteSection
			title="Modal"
			lead="For a decision that stops everything else, or a short form that belongs to nothing on the page. Escape and the close button close it; a click on the scrim does not. While something runs that must not be interrupted, it cannot be closed at all: no close button, Escape does nothing, and the foot says what is happening until the app closes it."
		>
			<Specimen
				code={`<Modal bind:open title="Restart the backend?" size="sm">
	<p>...</p>
	{#snippet footer()}
		<Button variant="ghost" onclick={() => (open = false)}>Cancel</Button>
		<Button variant="danger">Restart</Button>
	{/snippet}
</Modal>

<Modal open={restarting} title="Restarting the backend" size="sm"
	dismissible={false} status="Waiting for the backend to come back">
	<p>...</p>
</Modal>`}
			>
				<div class="flex flex-wrap gap-3">
					<Button onclick={() => (confirmOpen = true)}>Restart the backend</Button>
					<Button onclick={() => (renameOpen = true)}>Rename a profile</Button>
				</div>
			</Specimen>
		</SiteSection>

		<SiteSection
			title="Sheet"
			lead="One thing picked from a list, read beside it: a column the content narrows for, so every item stays in view. Another item swaps what it shows; Escape and the close button close it. In an app the open item lives in the URL, so Back closes it and the list is back at its scroll. Pick a part below."
		>
			<Specimen
				code={`<div class="flex items-start">
	<main class="min-w-0 flex-1">...</main>
	{#if picked}
		<Sheet title={picked.name} description="3001 · Red" onclose={() => (picked = null)}>...</Sheet>
	{/if}
</div>`}
			>
				<div class="grid grid-cols-[repeat(auto-fill,minmax(7.5rem,1fr))] gap-1">
					{#each sheetParts as p (p.partNum)}
						<PartTile
							layout="tile"
							name={p.name}
							bricklinkId={p.partNum}
							imgUrl={render(p.partNum, p.ldraw)}
							color={p.color}
							onclick={() => (picked = p)}
						/>
					{/each}
				</div>
			</Specimen>
		</SiteSection>

		<SiteSection
			title="Lightbox"
			lead="A picture as big as the window, to see a part up close. A part's picture opens it when given onzoom: the pointer turns to a magnifier and a magnifier shows in its corner. Escape, the close button, a click off the picture and, in an app, Back close it."
		>
			<Specimen
				code={`<PartTile ... onzoom={(src) => (zoomed = { src, alt: 'Brick 2 x 4, Red' })} />
<Lightbox src={zoomed?.src} alt={zoomed?.alt} onclose={() => (zoomed = null)} />`}
			>
				<div class="grid grid-cols-[repeat(auto-fill,minmax(7.5rem,1fr))] gap-3">
					{#each sheetParts as p (p.partNum)}
						<PartTile
							layout="tile"
							name={p.name}
							bricklinkId={p.partNum}
							imgUrl={render(p.partNum, p.ldraw)}
							color={p.color}
							onzoom={(src) => (zoomed = { src, alt: `${p.name}, ${p.color.name}` })}
						/>
					{/each}
				</div>
			</Specimen>
		</SiteSection>

		<SiteSection title="What there is not">
			<ul class="divide-y divide-line overflow-hidden rounded-panel bg-surface text-sm">
				<li class="px-5 py-3">
					<span class="font-medium text-ink">No toasts.</span>
					<span class="text-ink-muted"
						>A result shows where it happened: the button's own state, a sentence in the panel, or an
						Alert in the flow.</span
					>
				</li>
				<li class="px-5 py-3">
					<span class="font-medium text-ink">Nothing opens on hover but a tooltip.</span>
					<span class="text-ink-muted">A touch screen has no hover, and a machine may have one.</span>
				</li>
				<li class="px-5 py-3">
					<span class="font-medium text-ink">One overlay at a time.</span>
					<span class="text-ink-muted"
						>A menu item that needs a dialog closes the menu first; a dialog never opens another. A
						select in a popover or a sheet, and a picture seen up close from a sheet, are the
						exceptions.</span
					>
				</li>
			</ul>
		</SiteSection>
	</div>
	{#if picked}
		<Sheet
			title={picked.name}
			description={`${picked.partNum} · ${picked.color.name}`}
			onclose={() => (picked = null)}
		>
			{#snippet actions()}
				<Button variant="ghost" size="sm" icon={ExternalLink}>Rebrickable</Button>
			{/snippet}
				<section class="flex flex-col gap-3 border-b border-line p-5">
					<h3 class="text-sm font-semibold">In this profile</h3>
					<p class="text-sm text-ink-muted">
						{picked.quantity} of these went to the {picked.color.name.toLowerCase()} bin this week.
					</p>
				</section>
				<section class="flex flex-col gap-3 p-5">
					<h3 class="text-sm font-semibold">Every color</h3>
					<div class="grid grid-cols-[repeat(auto-fill,minmax(7.5rem,1fr))] gap-3">
						{#each sheetParts as p (p.partNum)}
							<PartTile
								layout="tile"
								name={p.name}
								bricklinkId={p.partNum}
								imgUrl={render(p.partNum, p.ldraw)}
								color={p.color}
								quantity={p.quantity}
								onzoom={(src) => (zoomed = { src, alt: `${p.name}, ${p.color.name}` })}
							/>
						{/each}
					</div>
				</section>
		</Sheet>
	{/if}
</div>

<Modal
	bind:open={confirmOpen}
	title={restarting ? 'Restarting the backend' : 'Restart the backend?'}
	size="sm"
	dismissible={!restarting}
	status={restarting ? 'Waiting for the backend to come back' : undefined}
>
	<p class="text-ink-muted">
		{#if restarting}
			This closes by itself when the backend answers again, in about half a minute.
		{:else}
			The machine stops sorting and comes back in standby in about half a minute. Parts on the
			channels stay where they are.
		{/if}
	</p>
	{#snippet footer()}
		{#if !restarting}
			<Button variant="ghost" onclick={() => (confirmOpen = false)}>Cancel</Button>
			<Button variant="danger" icon={RotateCcw} onclick={restart}>Restart</Button>
		{/if}
	{/snippet}
</Modal>

<Modal bind:open={renameOpen} title="Rename profile">
	<Field label="Name" for="rename-name">
		<Input id="rename-name" bind:value={profileName} />
	</Field>
	{#snippet footer()}
		<Button variant="ghost" onclick={() => (renameOpen = false)}>Cancel</Button>
		<Button
			variant="primary"
			onclick={() => {
				renameOpen = false;
				last = `Renamed to ${profileName}`;
			}}>Save</Button
		>
	{/snippet}
</Modal>

<Lightbox src={zoomed?.src} alt={zoomed?.alt} onclose={() => (zoomed = null)} />
