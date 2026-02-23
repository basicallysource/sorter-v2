<script lang="ts">
	import { getMachineContext } from '$lib/machines/context';
	import type { KnownObjectData, ClassificationStatus, PieceStage } from '$lib/api/events';
	import type { components } from '$lib/api/rest';
	import Spinner from './Spinner.svelte';
	import Badge from './Badge.svelte';
	import { CircleHelp, TriangleAlert } from 'lucide-svelte';
	import { settings } from '$lib/stores/settings';

	type BricklinkPartResponse = components['schemas']['BricklinkPartResponse'];
	type BadgeColor = 'gray' | 'yellow' | 'blue' | 'orange' | 'green' | 'red';

	const ctx = getMachineContext();

	const objects = $derived(ctx.machine?.recentObjects ?? []);

	let expanded_id = $state<string | null>(null);
	let bricklink_cache = $state<Map<string, BricklinkPartResponse | null>>(new Map());

	async function fetchBricklinkData(part_id: string) {
		if (bricklink_cache.has(part_id)) return;
		bricklink_cache.set(part_id, null);
		try {
			const res = await fetch(`/bricklink/part/${part_id}`);
			if (res.ok) {
				const data: BricklinkPartResponse = await res.json();
				bricklink_cache = new Map(bricklink_cache).set(part_id, data);
			}
		} catch {
			// ignore errors
		}
	}

	$effect(() => {
		for (const obj of objects) {
			if (obj.part_id && !bricklink_cache.has(obj.part_id)) {
				fetchBricklinkData(obj.part_id);
			}
		}
	});

	function toggleExpand(uuid: string) {
		expanded_id = expanded_id === uuid ? null : uuid;
	}

	function classificationColor(s: ClassificationStatus): BadgeColor {
		switch (s) {
			case 'classifying':
				return 'yellow';
			case 'classified':
				return 'blue';
			case 'unknown':
				return 'gray';
			case 'not_found':
				return 'yellow';
			default:
				return 'gray';
		}
	}

	function stageColor(s: PieceStage): BadgeColor {
		switch (s) {
			case 'distributing':
				return 'orange';
			case 'distributed':
				return 'green';
			default:
				return 'gray';
		}
	}

	function classificationLabel(obj: KnownObjectData): string {
		switch (obj.classification_status) {
			case 'classifying':
				return `classifying`;
			case 'classified':
				return obj.confidence != null ? `${(obj.confidence * 100).toFixed(0)}%` : 'classified';
			case 'unknown':
				return 'unknown';
			case 'not_found':
				return 'not found';
			default:
				return 'pending';
		}
	}

	function formatBin(bin: [unknown, unknown, unknown]): string {
		return `L${bin[0]}:S${bin[1]}:B${bin[2]}`;
	}

	function isMinimized(obj: KnownObjectData): boolean {
		return obj.classification_status === 'unknown' || obj.classification_status === 'not_found';
	}
</script>

<div
	class="dark:border-border-dark dark:bg-surface-dark flex h-full flex-col border border-border bg-surface"
>
	<div
		class="dark:bg-surface-dark dark:text-text-dark dark:border-border-dark border-b border-border px-2 py-1 text-sm font-medium text-text"
	>
		Recent Pieces
	</div>
	<div class="flex-1 overflow-y-auto">
		{#if objects.length === 0}
			<div class="dark:text-text-muted-dark p-3 text-center text-sm text-text-muted">
				No pieces yet
			</div>
		{:else}
			<div class="flex flex-col gap-1 p-1">
				{#each objects as obj (obj.uuid)}
					{@const is_expanded = expanded_id === obj.uuid}
					{@const minimized = isMinimized(obj)}
					{@const bl_data = obj.part_id ? bricklink_cache.get(obj.part_id) : null}
					{@const bl_thumb = bl_data?.thumbnail_url ? `https:${bl_data.thumbnail_url}` : null}
					{#if minimized}
						<button
							type="button"
							onclick={() => toggleExpand(obj.uuid)}
							class="dark:border-border-dark dark:bg-bg-dark dark:hover:bg-surface-dark flex w-full items-center gap-2 border border-border bg-bg px-2 py-1 text-left text-xs transition-colors hover:bg-surface"
						>
							{#if obj.classification_status === 'not_found'}
								<TriangleAlert size={14} class="flex-shrink-0 text-yellow-500" />
							{:else}
								<CircleHelp
									size={14}
									class="dark:text-text-muted-dark flex-shrink-0 text-text-muted"
								/>
							{/if}
							<span class="dark:text-text-muted-dark truncate text-text-muted">
								{obj.classification_status === 'not_found' ? 'Not found' : 'Unknown'}
							</span>
							<span class="dark:text-text-dark truncate font-mono text-text">
								{obj.uuid.slice(0, 8)}
							</span>
							{#if $settings.debug >= 2}
								<span class="dark:text-text-muted-dark truncate font-mono text-[10px] text-text-muted">
									id:{obj.uuid}
								</span>
							{/if}
							{#if obj.stage === 'distributing' || obj.stage === 'distributed'}
								<Badge color={stageColor(obj.stage)}>{obj.stage}</Badge>
							{/if}
						</button>
					{:else}
						<button
							type="button"
							onclick={() => toggleExpand(obj.uuid)}
							class="dark:border-border-dark dark:bg-bg-dark dark:hover:bg-surface-dark w-full border border-border bg-bg p-2 text-left transition-colors hover:bg-surface"
						>
							<div class="flex gap-2">
								{#if bl_thumb}
									<img
										src={bl_thumb}
										alt="piece"
										class="h-12 w-12 flex-shrink-0 bg-white object-contain"
									/>
								{:else if obj.thumbnail}
									<img
										src={`data:image/jpeg;base64,${obj.thumbnail}`}
										alt="piece"
										class="h-12 w-12 flex-shrink-0 object-cover"
									/>
								{:else}
									<div
										class="dark:bg-surface-dark dark:text-text-muted-dark flex h-12 w-12 flex-shrink-0 items-center justify-center bg-surface"
									>
										<Spinner />
									</div>
								{/if}
								<div class="flex min-w-0 flex-1 flex-col gap-1 text-xs">
									<span class="dark:text-text-dark truncate font-mono text-text">
										{obj.part_id ?? obj.uuid.slice(0, 8)}
									</span>
									{#if bl_data?.name}
										<div class="dark:text-text-muted-dark truncate text-text-muted">
											{bl_data.name}
										</div>
									{/if}
									{#if $settings.debug >= 2}
										<div class="dark:text-text-muted-dark truncate font-mono text-[10px] text-text-muted">
											id: {obj.uuid}
										</div>
									{/if}
									<div class="flex flex-wrap gap-1">
										{#if obj.classification_status !== 'pending'}
											<Badge color={classificationColor(obj.classification_status)}>
												{classificationLabel(obj)}
											</Badge>
										{/if}
										{#if obj.stage !== 'created'}
											<Badge color={stageColor(obj.stage)}>{obj.stage}</Badge>
										{/if}
										{#if obj.destination_bin}
											<Badge>{formatBin(obj.destination_bin)}</Badge>
										{/if}
									</div>
								</div>
							</div>

							{#if is_expanded && (obj.top_image || obj.bottom_image)}
								<div class="dark:border-border-dark mt-2 flex gap-2 border-t border-border pt-2">
									{#if obj.top_image}
										<div class="flex-1">
											<div class="dark:text-text-muted-dark mb-1 text-xs text-text-muted">Top</div>
											<img
												src={`data:image/jpeg;base64,${obj.top_image}`}
												alt="top view"
												class="w-full"
											/>
										</div>
									{/if}
									{#if obj.bottom_image}
										<div class="flex-1">
											<div class="dark:text-text-muted-dark mb-1 text-xs text-text-muted">
												Bottom
											</div>
											<img
												src={`data:image/jpeg;base64,${obj.bottom_image}`}
												alt="bottom view"
												class="w-full"
											/>
										</div>
									{/if}
								</div>
							{/if}
						</button>
					{/if}
				{/each}
			</div>
		{/if}
	</div>
</div>
