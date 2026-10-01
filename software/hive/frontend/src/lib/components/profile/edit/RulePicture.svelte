<!--
	A rule's picture, the one its bin is shown by. Unless one is chosen it is the
	best known part the rule takes, so nothing has to be done; choose one of the
	parts the rule takes, or upload a picture, and "Use the best known part" gives
	the automatic one back. What is chosen is the picture's address, kept on the
	rule as its image_url.
-->
<script module lang="ts">
	// A part to choose a picture from.
	export type Candidate = {
		key: string;
		name: string;
		imgUrl: string | null;
		bricklinkId?: string | null;
		partNum?: string | null;
	};
</script>

<script lang="ts">
	import { tick } from 'svelte';
	import ImageIcon from '@lucide/svelte/icons/image';
	import Upload from '@lucide/svelte/icons/upload';
	import { api } from '$lib/api';
	import Button from '$lib/components/Button.svelte';
	import Input from '$lib/components/Input.svelte';
	import PartImage from '$lib/components/PartImage.svelte';
	import PartTile from '$lib/components/PartTile.svelte';
	import Popover from '$lib/components/Popover.svelte';
	import Spinner from '$lib/components/Spinner.svelte';

	let {
		imageUrl,
		own,
		loadCandidates,
		onchange
	}: {
		// The picture the bin shows now.
		imageUrl: string | null;
		// Whether it was chosen for this rule (rather than the best known part).
		own: boolean;
		// The parts to choose a picture from, matching what was typed.
		loadCandidates: (query: string) => Promise<Candidate[]>;
		onchange: (url: string | null) => void;
	} = $props();

	let open = $state(false);
	let query = $state('');
	let candidates = $state.raw<Candidate[]>([]);
	let loading = $state(false);
	let search = $state<HTMLInputElement | undefined>();
	let timer: ReturnType<typeof setTimeout> | undefined;
	let latest = 0;

	async function load() {
		const mine = ++latest;
		loading = true;
		try {
			const found = await loadCandidates(query.trim());
			if (mine === latest) candidates = found.filter((c) => c.imgUrl);
		} catch {
			if (mine === latest) candidates = [];
		}
		if (mine === latest) loading = false;
	}

	$effect(() => {
		if (!open) return;
		query = '';
		candidates = [];
		void load();
		void tick().then(() => search?.focus());
	});

	function onSearch() {
		clearTimeout(timer);
		timer = setTimeout(() => void load(), 250);
	}

	function choose(candidate: Candidate) {
		open = false;
		onchange(candidate.imgUrl);
	}

	let fileInput = $state<HTMLInputElement | undefined>();
	let uploading = $state(false);
	let uploadError = $state<string | null>(null);

	async function upload(event: Event) {
		const input = event.currentTarget as HTMLInputElement;
		const file = input.files?.[0];
		input.value = '';
		if (!file) return;
		uploading = true;
		uploadError = null;
		try {
			const res = await api.uploadProfileImage(file);
			onchange(res.url);
		} catch (e) {
			uploadError = (e as { error?: string })?.error ?? 'The picture could not be uploaded.';
		}
		uploading = false;
	}
</script>

<div class="flex items-start gap-4">
	<PartImage src={imageUrl} class="size-20 shrink-0" />
	<div class="min-w-0 flex-1">
		<div class="text-sm font-medium text-ink">Picture</div>
		<p class="text-sm text-ink-muted">
			{own ? 'A picture chosen for this rule.' : imageUrl ? 'The best known part it takes.' : 'It has no part to show yet.'}
		</p>
		<div class="mt-2 flex flex-wrap items-center gap-2">
			<Popover label="Choose a part's picture" placement="bottom-start" width="26rem" padded={false} bind:open>
				{#snippet trigger(props)}
					<Button {...props} size="sm" icon={ImageIcon}>Choose a part's picture</Button>
				{/snippet}
				<div class="flex max-h-[28rem] flex-col">
					<div class="border-b border-line p-2">
						<Input
							bind:element={search}
							bind:value={query}
							type="search"
							size="sm"
							placeholder="Search the parts it takes"
							aria-label="Search the parts it takes"
							autocomplete="off"
							oninput={onSearch}
						/>
					</div>
					<div class="min-h-0 flex-1 overflow-y-auto p-3">
						{#if loading && candidates.length === 0}
							<p class="flex items-center gap-2 text-ink-muted"><Spinner size={14} />Loading the parts</p>
						{:else if candidates.length === 0}
							<p class="text-ink-muted">
								{query.trim() ? `No part it takes matches "${query.trim()}".` : 'It takes no part with a picture yet.'}
							</p>
						{:else}
							<div class="grid grid-cols-3 gap-x-2 gap-y-3">
								{#each candidates as candidate (candidate.key)}
									<PartTile
										layout="tile"
										name={candidate.name}
										imgUrl={candidate.imgUrl}
										bricklinkId={candidate.bricklinkId}
										partNum={candidate.partNum}
										onclick={() => choose(candidate)}
									/>
								{/each}
							</div>
						{/if}
					</div>
				</div>
			</Popover>
			<Button size="sm" icon={Upload} loading={uploading} onclick={() => fileInput?.click()}>Upload</Button>
			{#if own}
				<Button size="sm" variant="ghost" onclick={() => onchange(null)}>Use the best known part</Button>
			{/if}
		</div>
		{#if uploadError}<p class="mt-2 text-sm text-danger-ink">{uploadError}</p>{/if}
	</div>
</div>
<input bind:this={fileInput} type="file" accept="image/*" class="hidden" onchange={upload} />
