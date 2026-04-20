<script lang="ts">
	import { getMachineContext } from '$lib/machines/context';
	import type { KnownObjectData, ClassificationStatus, PieceStage } from '$lib/api/events';
import Spinner from './Spinner.svelte';
	import Badge from './Badge.svelte';
	import { CircleHelp, TriangleAlert } from 'lucide-svelte';
	import { sortingProfileStore } from '$lib/stores/sortingProfile.svelte';

	type BadgeColor = 'gray' | 'yellow' | 'blue' | 'orange' | 'green' | 'red';

	const ctx = getMachineContext();

	const objects = $derived(ctx.machine?.recentObjects ?? []);

	sortingProfileStore.load();

	let expanded_id = $state<string | null>(null);

	function toggleExpand(uuid: string) {
		expanded_id = expanded_id === uuid ? null : uuid;
	}

	function classificationColor(s: ClassificationStatus): BadgeColor {
		switch (s) {
			case 'classifying':
				return 'yellow';
			case 'classified':
				return 'blue';
			case 'multi_drop_fail':
				return 'red';
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
				return 'classified';
			case 'multi_drop_fail':
				return 'multi drop fail';
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
	class="setup-card-shell flex h-full flex-col border"
>
	<div
		class="setup-card-header px-3 py-2 text-sm font-medium text-text"
	>
		Recent Pieces
	</div>
	<div class="flex-1 overflow-y-auto">
		{#if objects.length === 0}
			<div class="p-3 text-center text-sm text-text-muted">
				No pieces yet
			</div>
		{:else}
			<div class="flex flex-col gap-1 p-1">
				{#each objects as obj (obj.uuid)}
					{@const is_expanded = expanded_id === obj.uuid}
					{@const minimized = isMinimized(obj)}
					{@const preview_url = obj.brickognize_preview_url ?? null}
					{@const category_name = obj.category_id ? sortingProfileStore.getCategoryName(obj.category_id) : null}
					{#if minimized}
						<button
							type="button"
							onclick={() => toggleExpand(obj.uuid)}
							class="flex w-full items-center gap-2 border border-border bg-bg px-2 py-1 text-left text-xs transition-colors hover:bg-surface"
						>
							{#if obj.classification_status === 'not_found' || obj.classification_status === 'multi_drop_fail'}
								<TriangleAlert
									size={14}
									class={`flex-shrink-0 ${
										obj.classification_status === 'multi_drop_fail'
											? 'text-danger dark:text-red-400'
											: 'text-yellow-500'
									}`}
								/>
							{:else}
								<CircleHelp
									size={14}
									class="flex-shrink-0 text-text-muted"
								/>
							{/if}
							<span class="truncate text-text-muted">
								{obj.classification_status === 'not_found'
									? 'Not found'
									: obj.classification_status === 'multi_drop_fail'
										? 'Multi drop fail'
										: 'Unknown'}
							</span>
							<span class="truncate font-mono text-text">
								{obj.uuid.slice(0, 8)}
							</span>
							{#if obj.stage === 'distributing' || obj.stage === 'distributed'}
								<Badge color={stageColor(obj.stage)}>{obj.stage}</Badge>
							{/if}
						</button>
					{:else}
						<button
							type="button"
							onclick={() => toggleExpand(obj.uuid)}
							class="w-full border border-border bg-bg p-2 text-left transition-colors hover:bg-surface"
						>
							<div class="flex gap-2">
								{#if preview_url}
									<img
										src={preview_url}
										alt="Brickognize preview"
										class="h-12 w-12 flex-shrink-0 bg-white object-contain"
									/>
								{:else if obj.thumbnail}
									<img
										src={`data:image/jpeg;base64,${obj.thumbnail}`}
										alt="piece"
										class="h-12 w-12 flex-shrink-0 bg-white object-contain"
									/>
								{:else}
									<div
										class="flex h-12 w-12 flex-shrink-0 items-center justify-center bg-surface"
									>
										<Spinner />
									</div>
								{/if}
								<div class="flex min-w-0 flex-1 flex-col gap-1 text-xs">
									<span class="truncate font-mono text-text">
										{obj.part_id ?? obj.uuid.slice(0, 8)}
									</span>
									{#if obj.color_name && obj.color_name !== 'Any Color'}
										<div class="truncate text-text-muted">
											{obj.color_name}
										</div>
									{/if}
									{#if category_name}
										<div class="truncate text-text-muted">
											{category_name}
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

							{#if is_expanded && (obj.thumbnail || preview_url)}
								<div class="mt-2 grid gap-2 border-t border-border pt-2 sm:grid-cols-2">
									{#if obj.thumbnail}
										<div>
											<div class="mb-1 text-xs text-text-muted">
												Local Crop{#if obj.brickognize_source_view} ({obj.brickognize_source_view}){/if}
											</div>
											<img
												src={`data:image/jpeg;base64,${obj.thumbnail}`}
												alt="classification crop"
												class="w-full bg-white object-contain"
											/>
										</div>
									{/if}
									{#if preview_url}
										<div>
											<div class="mb-1 text-xs text-text-muted">
												Brickognize Match
											</div>
											<img
												src={preview_url}
												alt="Brickognize preview"
												class="w-full bg-white object-contain"
											/>
										</div>
									{/if}
								</div>
							{/if}

							{#if is_expanded && (obj.top_image || obj.bottom_image)}
								<div class="mt-2 flex gap-2 border-t border-border pt-2">
									{#if obj.top_image}
										<div class="flex-1">
											<div class="mb-1 text-xs text-text-muted">Top</div>
											<img
												src={`data:image/jpeg;base64,${obj.top_image}`}
												alt="top view"
												class="w-full"
											/>
										</div>
									{/if}
									{#if obj.bottom_image}
										<div class="flex-1">
											<div class="mb-1 text-xs text-text-muted">
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
