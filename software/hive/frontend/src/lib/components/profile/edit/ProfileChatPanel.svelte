<script lang="ts">
	import { renderMarkdown } from '$lib/markdown';
	import Spinner from '$lib/components/Spinner.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Button from '$lib/components/Button.svelte';
	import Input from '$lib/components/Input.svelte';
	import Tabs from '$lib/components/Tabs.svelte';
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import Check from '@lucide/svelte/icons/check';
	import GitFork from '@lucide/svelte/icons/git-fork';
	import Send from '@lucide/svelte/icons/send';
	import Sparkles from '@lucide/svelte/icons/sparkles';
	import type { SortingProfileAiMessage, SortingProfileDetail, SortingProfileVersion, AiToolTraceItem } from '$lib/api';

	type ToolResultListItem = {
		id: string;
		primary: string;
		secondary: string | null;
		imageUrl?: string | null;
	};

	type ExpandableToolResult = {
		layout: 'list' | 'media-grid';
		total: number;
		availableCount: number;
		singularLabel: string;
		pluralLabel: string;
		emptyMessage: string;
		items: ToolResultListItem[];
	};

	type AiProgressCard = {
		id: string;
		kind: 'analysis' | 'tool' | 'writing' | 'applying';
		status: 'active' | 'complete';
		title: string;
		detail: string | null;
		tool?: string;
		output?: Record<string, unknown> | null;
		durationMs?: number | null;
	};

	interface Props {
		profile: SortingProfileDetail;
		rightTab: 'chat' | 'versions';
		onRightTabChange: (tab: 'chat' | 'versions') => void;
		hasOpenRouter: boolean;
		aiMessages: SortingProfileAiMessage[];
		aiMessage: string;
		onAiMessageChange: (value: string) => void;
		aiBusy: boolean;
		aiError: string | null;
		aiErrorCode: string | null;
		isNewProfile: boolean;
		workingRulesLength: number;
		visibleAiProgressCards: AiProgressCard[];
		chatContainerRef?: (el: HTMLDivElement | undefined) => void;
		onSendAiMessage: () => void;
		onViewVersion: (id: string) => void;
		onRestoreVersion: (id: string) => void;
		onForkFromVersion: (id: string) => void;
		onExitPreview: () => void;
		restoringVersionId: string | null;
		previewLoading: boolean;
		formatDate: (iso: string) => string;
		formatDuration: (ms: number | null | undefined) => string | null;
		displayAiMessageContent: (content: string) => string;
		aiMessagePerformanceLabel: (message: SortingProfileAiMessage) => string | null;
		proposalActionSummaries: (proposal: Record<string, unknown> | null) => string[];
		toolTraceTitle: (item: AiToolTraceItem) => string;
		getExpandableToolResult: (tool: string | undefined, output: Record<string, unknown> | null | undefined) => ExpandableToolResult | null;
		getToolResultSummaryLine: (result: ExpandableToolResult) => string;
		visibleToolResultItems: (result: ExpandableToolResult, key: string) => ToolResultListItem[];
		canExpandToolResult: (result: ExpandableToolResult) => boolean;
		isToolResultExpanded: (key: string) => boolean;
		onToggleToolResult: (key: string) => void;
	}

	let {
		profile,
		rightTab,
		onRightTabChange,
		hasOpenRouter,
		aiMessages,
		aiMessage,
		onAiMessageChange,
		aiBusy,
		aiError,
		aiErrorCode,
		isNewProfile,
		workingRulesLength,
		visibleAiProgressCards,
		chatContainerRef,
		onSendAiMessage,
		onViewVersion,
		onRestoreVersion,
		onForkFromVersion,
		onExitPreview,
		restoringVersionId,
		previewLoading,
		formatDate,
		formatDuration,
		displayAiMessageContent,
		aiMessagePerformanceLabel,
		proposalActionSummaries,
		toolTraceTitle,
		getExpandableToolResult,
		getToolResultSummaryLine,
		visibleToolResultItems,
		canExpandToolResult,
		isToolResultExpanded,
		onToggleToolResult
	}: Props = $props();

	let chatContainer: HTMLDivElement | undefined = $state(undefined);

	$effect(() => {
		chatContainerRef?.(chatContainer);
	});
</script>

<!-- What a tool found, the same whether the step is done (a trace on a reply) or still running. -->
{#snippet toolResult(resultView: ExpandableToolResult, key: string)}
	<div class="mt-1 text-sm text-ink-muted">
		<div>{getToolResultSummaryLine(resultView)}</div>
		{#if resultView.items.length > 0}
			{#if resultView.layout === 'media-grid'}
				<div class="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
					{#each visibleToolResultItems(resultView, key) as item (item.id)}
						<figure class="overflow-hidden rounded-control bg-well">
							<div class="aspect-[4/3]">
								{#if item.imageUrl}
									<img src={item.imageUrl} alt={item.primary} class="size-full object-contain p-2" loading="lazy" />
								{:else}
									<div class="flex h-full items-center justify-center text-sm text-ink-faint">No picture</div>
								{/if}
							</div>
							<figcaption class="px-2.5 py-2">
								<div class="line-clamp-2 text-ink">{item.primary}</div>
								{#if item.secondary}<div class="mt-0.5 line-clamp-2">{item.secondary}</div>{/if}
							</figcaption>
						</figure>
					{/each}
				</div>
			{:else}
				<ul class="mt-1.5 flex flex-col gap-1">
					{#each visibleToolResultItems(resultView, key) as item (item.id)}
						<li class="flex min-w-0 items-baseline gap-2">
							<span class="size-1.5 shrink-0 translate-y-[-1px] rounded-full bg-ink-faint"></span>
							<span class="truncate text-ink">{item.primary}</span>
							{#if item.secondary}<span class="truncate">{item.secondary}</span>{/if}
						</li>
					{/each}
				</ul>
			{/if}
			{#if canExpandToolResult(resultView)}
				<Button variant="ghost" size="sm" class="mt-1 -ml-2.5" onclick={() => onToggleToolResult(key)}>
					{isToolResultExpanded(key)
						? 'Show less'
						: `Show all ${resultView.availableCount} ${resultView.availableCount === 1 ? resultView.singularLabel : resultView.pluralLabel}`}
				</Button>
			{/if}
		{/if}
	</div>
{/snippet}

{#snippet step(done: boolean, title: string, durationMs: number | null, resultView: ExpandableToolResult | null, key: string, detail: string | null)}
	<div class="flex items-start gap-2 text-sm">
		<span class="mt-0.5 flex size-4 shrink-0 items-center justify-center">
			{#if done}<Check size={14} class="text-success-ink" />{:else}<Spinner size={12} class="text-ink-muted" />{/if}
		</span>
		<div class="min-w-0 flex-1">
			<div class="flex items-center justify-between gap-2">
				<span class="text-ink">{title}</span>
				{#if formatDuration(durationMs)}<span class="num shrink-0 text-ink-faint">{formatDuration(durationMs)}</span>{/if}
			</div>
			{#if resultView}
				{@render toolResult(resultView, key)}
			{:else if detail}
				<div class="markdown-body markdown-compact mt-0.5 text-ink-muted">{@html renderMarkdown(detail)}</div>
			{/if}
		</div>
	</div>
{/snippet}

<div class="flex min-h-0 min-w-0 flex-col overflow-hidden rounded-panel bg-surface">
	<Tabs
		label="Assistant and versions"
		inset
		value={rightTab}
		onchange={onRightTabChange}
		items={[
			{ value: 'chat', label: 'Chat' },
			{ value: 'versions', label: 'Versions', count: profile.versions.length }
		]}
	/>

	{#if rightTab === 'versions'}
		<div class="flex-1 overflow-y-auto">
			{#if profile.versions.length === 0}
				<p class="p-6 text-center text-sm text-ink-muted">No versions yet.</p>
			{:else}
				<ul class="divide-y divide-line">
					{#each [...profile.versions].reverse() as version (version.id)}
						{@const isCurrent = version.id === profile.current_version?.id}
						<li class="flex flex-col gap-1 px-(--pad-panel) py-3 {isCurrent ? 'bg-primary-soft' : ''}">
							<div class="flex items-center justify-between gap-2">
								<div class="flex items-center gap-2">
									<span class="num font-medium {isCurrent ? 'text-primary-ink' : 'text-ink'}">v{version.version_number}</span>
									{#if isCurrent}<Badge tone="primary">Current</Badge>{/if}
									{#if version.is_published}<Badge tone="success">Published</Badge>{/if}
									{#if version.label}<Badge>{version.label}</Badge>{/if}
								</div>
								<span class="text-sm text-ink-muted">{formatDate(version.created_at)}</span>
							</div>
							{#if version.change_note}<p class="text-sm text-ink-muted">{version.change_note}</p>{/if}
							<p class="num text-sm text-ink-muted">{version.compiled_part_count} parts</p>
							<div class="mt-1 flex gap-2">
								<Button
									size="sm"
									disabled={previewLoading}
									onclick={() => {
										if (isCurrent) onExitPreview();
										else onViewVersion(version.id);
									}}>View</Button
								>
								{#if !isCurrent}
									<Button
										size="sm"
										loading={restoringVersionId === version.id}
										disabled={restoringVersionId !== null}
										onclick={() => onRestoreVersion(version.id)}>Restore</Button
									>
								{/if}
								<Button size="sm" variant="ghost" icon={GitFork} onclick={() => onForkFromVersion(version.id)}
									>Fork</Button
								>
							</div>
						</li>
					{/each}
				</ul>
			{/if}
		</div>
	{:else if !hasOpenRouter}
		<div class="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
			<Sparkles size={24} class="text-ink-faint" />
			<p class="text-sm text-ink-muted">The assistant needs an OpenRouter key.</p>
			<Button href="/settings" size="sm" icon={ArrowRight}>Add one in settings</Button>
		</div>
	{:else}
		<div bind:this={chatContainer} class="flex-1 overflow-y-auto p-4">
			{#if aiMessages.length === 0}
				<div class="flex h-full flex-col items-center justify-center gap-1 text-center">
					<Sparkles size={24} class="mb-2 text-ink-faint" />
					<p class="text-sm font-medium text-ink">Describe what you want to sort</p>
					<p class="text-sm text-ink-muted">The assistant creates categories, adds rules and refines them with you.</p>
				</div>
			{:else}
				<div class="flex min-w-0 flex-col gap-4">
					{#each aiMessages as msg (msg.id)}
						<div class="min-w-0 {msg.role === 'user' ? 'ml-8' : 'mr-8'}">
							{#if msg.role === 'assistant'}
								{#if msg.tool_trace?.length}
									<div class="mb-3 flex flex-col gap-2">
										{#each msg.tool_trace as trace, traceIndex (traceIndex)}
											{@render step(
												true,
												toolTraceTitle(trace),
												trace.duration_ms ?? null,
												getExpandableToolResult(trace.tool, trace.output),
												`${msg.id}-trace-${traceIndex}`,
												trace.output_summary
											)}
										{/each}
									</div>
								{/if}
								<div class="min-w-0 overflow-hidden rounded-control bg-well p-3 text-sm text-ink">
									<div class="markdown-body overflow-x-auto">
										{@html renderMarkdown(displayAiMessageContent(msg.content))}
									</div>
									{#if aiMessagePerformanceLabel(msg)}
										<div class="mt-2 text-sm text-ink-muted">{aiMessagePerformanceLabel(msg)}</div>
									{/if}
									{#if msg.applied_at && msg.proposal}
										{@const actions = proposalActionSummaries(msg.proposal)}
										{#if actions.length}
											<ul class="mt-2 flex flex-col gap-0.5 border-t border-line pt-2">
												{#each actions as action, i (i)}
													<li class="flex items-center gap-1.5 text-sm text-success-ink">
														<Check size={14} class="shrink-0" />{action}
													</li>
												{/each}
											</ul>
										{/if}
									{/if}
								</div>
							{:else}
								<div class="min-w-0 overflow-hidden rounded-control bg-primary-soft p-3 text-sm whitespace-pre-wrap text-ink">
									{msg.content}
								</div>
							{/if}
						</div>
					{/each}
					{#if aiError}
						<div class="mr-8">
							<Alert tone="danger" title={aiError}>
								{#if aiErrorCode?.startsWith('OPENROUTER_')}The OpenRouter key in your settings needs fixing.{/if}
								{#snippet actions()}
									{#if aiErrorCode?.startsWith('OPENROUTER_')}
										<Button href="/settings" size="sm">Settings</Button>
									{/if}
								{/snippet}
							</Alert>
						</div>
					{/if}
					{#if aiBusy}
						<div class="mr-8 flex flex-col gap-2" aria-live="polite">
							{#each visibleAiProgressCards as card (card.id)}
								{@render step(
									card.status !== 'active',
									card.title,
									card.durationMs ?? null,
									getExpandableToolResult(card.tool, card.output),
									card.id,
									card.detail
								)}
							{/each}
						</div>
					{/if}
				</div>
			{/if}
		</div>

		<form
			class="flex gap-2 border-t border-line p-3"
			onsubmit={(e) => {
				e.preventDefault();
				if (!aiBusy && aiMessage.trim()) onSendAiMessage();
			}}
		>
			<Input
				class="min-w-0 flex-1"
				value={aiMessage}
				disabled={aiBusy}
				placeholder={isNewProfile && workingRulesLength === 0
					? 'For example: sort Technic parts by what they do, gears, beams, connectors'
					: 'Describe a change'}
				oninput={(e) => onAiMessageChange((e.currentTarget as HTMLInputElement).value)}
			/>
			<Button type="submit" variant="primary" icon={Send} loading={aiBusy} disabled={!aiMessage.trim()}>Send</Button>
		</form>
	{/if}
</div>
