<script lang="ts">
	import CameraFeed from '$lib/components/CameraFeed.svelte';
	import type { CameraRole } from '$lib/settings/stations';

	let changingCamera = $state(false);

	type CameraChoice = {
		key: string;
		label: string;
		source: number | string | null;
	};

	let {
		role,
		label,
		description,
		required = false,
		selectedKey = '__none__',
		selectedLabel = 'No camera selected',
		choices = [],
		onSelect,
		zoneReviewed = false,
		pictureTuned = false,
		onOpenPictureSettings,
		onOpenZoneEditor
	}: {
		role: CameraRole;
		label: string;
		description: string;
		required?: boolean;
		selectedKey?: string;
		selectedLabel?: string;
		choices?: CameraChoice[];
		zoneReviewed?: boolean;
		pictureTuned?: boolean;
		onSelect?: (role: string, key: string) => void;
		onOpenPictureSettings?: (role: string) => void;
		onOpenZoneEditor?: (role: string) => void;
	} = $props();

	const selectedSource = $derived(
		selectedKey === '__none__'
			? null
			: choices.find((choice) => choice.key === selectedKey)?.source ?? null
	);
</script>

<div class="setup-panel overflow-hidden p-4">
	<div class="flex flex-wrap items-start justify-between gap-3">
		<div class="min-w-0 flex-1">
			<div class="flex flex-wrap items-center gap-2">
				<div class="text-sm font-semibold text-text">{label}</div>
				<div class:text-[#D01012]={required} class:text-text-muted={!required} class="text-xs">
					{required ? 'Required' : 'Optional'}
				</div>
			</div>
			<div class="mt-1 text-sm text-text-muted">{description}</div>
		</div>
	</div>

	<div class="mt-4 flex flex-wrap items-center gap-2 text-xs">
		<button
			onclick={() => selectedSource !== null && (changingCamera = !changingCamera)}
			disabled={selectedSource === null}
			class={`inline-flex items-center gap-2 border px-2.5 py-1.5 font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${selectedSource === null ? 'border-border bg-bg text-text-muted' : 'border-[#0055BF]/30 bg-[#0055BF]/10 text-[#0055BF] hover:bg-[#0055BF]/15'}`}
		>
			<span class={`flex h-4 w-4 items-center justify-center rounded-full text-[10px] leading-none ${selectedSource === null ? 'bg-border text-text-muted' : 'bg-[#0055BF] text-white'}`}>
				{selectedSource === null ? '1' : '✓'}
			</span>
			<span>{selectedSource === null ? 'Choose camera' : 'Camera selected'}</span>
		</button>
		<span class="text-text-muted">—</span>
		<button
			onclick={() => onOpenZoneEditor?.(role)}
			disabled={selectedSource === null}
			class={`inline-flex items-center gap-2 border px-2.5 py-1.5 font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${zoneReviewed ? 'border-[#00852B]/30 bg-[#00852B]/10 text-[#00852B] hover:bg-[#00852B]/15' : 'border-border bg-bg text-text-muted hover:border-border/80 hover:bg-surface'}`}
		>
			<span class={`flex h-4 w-4 items-center justify-center rounded-full text-[10px] leading-none ${zoneReviewed ? 'bg-[#00852B] text-white' : 'bg-border text-text-muted'}`}>
				{zoneReviewed ? '✓' : '2'}
			</span>
			<span>{zoneReviewed ? 'Zone reviewed' : 'Review zone'}</span>
		</button>
		<span class="text-text-muted">—</span>
		<button
			onclick={() => onOpenPictureSettings?.(role)}
			disabled={selectedSource === null}
			class={`inline-flex items-center gap-2 border px-2.5 py-1.5 font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${pictureTuned ? 'border-[#00852B]/30 bg-[#00852B]/10 text-[#00852B] hover:bg-[#00852B]/15' : 'border-border bg-bg text-text-muted hover:border-border/80 hover:bg-surface'}`}
		>
			<span class={`flex h-4 w-4 items-center justify-center rounded-full text-[10px] leading-none ${pictureTuned ? 'bg-[#00852B] text-white' : 'bg-border text-text-muted'}`}>
				{pictureTuned ? '✓' : '3'}
			</span>
			<span>{pictureTuned ? 'Picture tuned' : 'Picture tuning'}</span>
		</button>
	</div>

	<div class="mt-3 overflow-hidden border border-border bg-bg">
		<div class="aspect-[4/3] bg-surface">
			{#if selectedSource !== null}
				<CameraFeed camera={role} label={selectedLabel} />
			{:else if choices.filter((choice) => choice.key !== '__none__').length > 0}
				<div class="grid h-full grid-cols-2 gap-2 p-2">
					{#each choices.filter((choice) => choice.key !== '__none__') as choice}
						<button
							onclick={() => onSelect?.(role, choice.key)}
							class="flex min-h-0 flex-col overflow-hidden border border-border bg-surface text-left transition-colors hover:border-[#0055BF] hover:bg-[#0055BF]/5"
						>
							<div class="min-h-0 flex-1">
								<CameraFeed camera={role} label={choice.label} />
							</div>
							<div class="border-t border-border px-2 py-1 text-xs text-text">{choice.label}</div>
						</button>
					{/each}
				</div>
			{:else}
				<div class="flex h-full flex-col items-center justify-center px-6 text-center text-sm text-text-muted">
					<div class="font-medium text-text">No camera selected yet</div>
					<div class="mt-2">Refresh sources to discover cameras, then choose one here.</div>
				</div>
			{/if}
		</div>
	</div>

	{#if changingCamera && selectedSource !== null}
		<div
			class="fixed inset-0 z-40 flex items-center justify-center bg-black/50 px-4"
			onclick={(event) => event.target === event.currentTarget && (changingCamera = false)}
			onkeydown={(event) => event.key === 'Escape' && (changingCamera = false)}
			role="dialog"
			tabindex="0"
		>
			<div class="max-h-[85vh] w-full max-w-5xl overflow-auto border border-border bg-bg shadow-lg">
				<div class="sticky top-0 flex items-center justify-between border-b border-border bg-surface px-4 py-3">
					<div>
						<div class="text-sm font-semibold text-text">Change camera</div>
						<div class="mt-1 text-xs text-text-muted">Pick a different live source for {label}.</div>
					</div>
					<button
						onclick={() => (changingCamera = false)}
						class="setup-button-secondary px-3 py-1.5 text-sm text-text"
					>
						Close
					</button>
				</div>
				<div class="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-3">
					{#each choices.filter((choice) => choice.key !== '__none__') as choice}
						<button
							onclick={() => {
								onSelect?.(role, choice.key);
								changingCamera = false;
							}}
							class={`overflow-hidden border bg-surface text-left transition-colors ${choice.key === selectedKey ? 'border-[#0055BF] ring-1 ring-[#0055BF]/30' : 'border-border hover:border-[#0055BF] hover:bg-[#0055BF]/5'}`}
						>
							<div class="aspect-[4/3] min-h-0 bg-surface">
								<CameraFeed camera={role} label={choice.label} />
							</div>
							<div class="border-t border-border px-3 py-2 text-sm font-medium text-text">{choice.label}</div>
						</button>
					{/each}
				</div>
				<div class="flex items-center justify-end border-t border-border px-4 py-3">
					<button
						onclick={() => {
							onSelect?.(role, '__none__');
							changingCamera = false;
						}}
						class="rounded border border-border bg-surface px-3 py-2 text-sm text-text transition-colors hover:border-[#D01012] hover:bg-[#D01012]/5 hover:text-[#D01012]"
					>
						Clear camera
					</button>
				</div>
			</div>
		</div>
	{/if}

</div>
