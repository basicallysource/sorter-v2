<!--
	The assistant: describe a change in words and it searches the catalog, makes
	the rules and saves them as a new version, showing each step it takes. It
	works on the saved version, not on the draft, so a draft with unsaved changes
	says so above the box. It keeps its conversation while another tab of the
	editor is showing, so the page renders it always and hides it (`active`).
-->
<script lang="ts">
	import { tick } from 'svelte';
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import Check from '@lucide/svelte/icons/check';
	import Send from '@lucide/svelte/icons/send';
	import Sparkles from '@lucide/svelte/icons/sparkles';
	import {
		api,
		type SortingProfileAiMessage,
		type SortingProfileDetail,
		type SortingProfileVersion
	} from '$lib/api';
	import Alert from '$lib/components/Alert.svelte';
	import Button from '$lib/components/Button.svelte';
	import Input from '$lib/components/Input.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import { renderMarkdown } from '$lib/markdown';
	import { uuid } from '$lib/uuid';
	import {
		aiMessagePerformanceLabel,
		buildAiProgressCards,
		displayAiMessageContent,
		formatDuration,
		getExpandableToolResult,
		getToolResultSummaryLine,
		proposalActionSummaries,
		toolTraceTitle,
		TOOL_RESULT_COLLAPSED_COUNT,
		type AiProgressEvent,
		type ExpandableToolResult,
		type ToolResultListItem
	} from './chat-helpers';

	let {
		profile,
		selectedRuleId,
		hasOpenRouter,
		isNewProfile,
		rulesCount,
		dirty,
		active,
		onbusy,
		onapplied
	}: {
		profile: SortingProfileDetail;
		// The rule being edited, which the assistant is told about.
		selectedRuleId: string | null;
		hasOpenRouter: boolean;
		isNewProfile: boolean;
		rulesCount: number;
		// The draft has changes the assistant cannot see.
		dirty: boolean;
		// Whether this tab is the one showing.
		active: boolean;
		// It is working on a request (and may save a version any moment).
		onbusy: (busy: boolean) => void;
		// The assistant saved a new version.
		onapplied: (version: SortingProfileVersion) => void;
	} = $props();

	let messages = $state<SortingProfileAiMessage[]>([]);
	let draft = $state('');
	let busy = $state(false);
	let progress = $state<AiProgressEvent[]>([]);
	let error = $state<string | null>(null);
	let errorCode = $state<string | null>(null);
	let expandedResults = $state<Set<string>>(new Set());
	let scroller = $state<HTMLDivElement | undefined>();

	// The conversation belongs to the profile's owner.
	$effect(() => {
		if (!profile.is_owner) return;
		const id = profile.id;
		api
			.getSortingProfileAiMessages(id)
			.then((list) => {
				if (id === profile.id) messages = list;
			})
			.catch(() => {});
	});

	const cards = $derived(buildAiProgressCards(progress));
	const visibleCards = $derived.by(() => {
		const done = cards.filter((card) => card.kind === 'tool' && card.status === 'complete');
		const current = [...cards].reverse().find((card) => card.status === 'active');
		const steady =
			done.length <= 5
				? done
				: [...done.slice(0, 2), ...done.slice(-3)].filter(
						(card, index, all) => all.findIndex((entry) => entry.id === card.id) === index
					);
		return current ? [...steady, current] : steady;
	});

	// Follow the conversation down as it grows, and when this tab comes back.
	$effect(() => {
		void messages.length;
		void busy;
		void progress.length;
		void active;
		if (!active) return;
		void tick().then(() => scroller?.scrollTo({ top: scroller.scrollHeight }));
	});

	async function send() {
		const text = draft.trim();
		if (!text || busy) return;
		draft = '';
		const asked: SortingProfileAiMessage = {
			id: uuid(),
			role: 'user',
			content: text,
			model: null,
			version_id: profile.current_version?.id ?? null,
			applied_version_id: null,
			selected_rule_id: selectedRuleId,
			usage: null,
			proposal: null,
			tool_trace: [],
			applied_at: null,
			created_at: new Date().toISOString()
		};
		messages = [...messages, asked];
		busy = true;
		onbusy(true);
		progress = [{ type: 'thinking' }];
		error = null;
		errorCode = null;
		const request = {
			message: text,
			version_id: profile.current_version?.id ?? null,
			selected_rule_id: selectedRuleId
		};
		try {
			let response: SortingProfileAiMessage;
			try {
				response = await api.streamSortingProfileAiMessage(profile.id, request, (event) => {
					progress = [...progress, event as AiProgressEvent];
				});
			} catch (e) {
				// The fallback is for a backend without the streaming route. Any other
				// failure already cost a model call; making it again would only double
				// the bill and the wait.
				if ((e as { status?: number })?.status !== 404) throw e;
				progress = [{ type: 'thinking' }];
				response = await api.createSortingProfileAiMessage(profile.id, request);
			}
			messages = [...messages, response];

			// A reply with changes in it is saved at once.
			const proposals =
				response.proposal && Array.isArray((response.proposal as { proposals?: unknown }).proposals)
					? ((response.proposal as { proposals: unknown[] }).proposals as unknown[])
					: [];
			if (proposals.length > 0) {
				progress = [...progress, { type: 'applying' }];
				const version = await api.applySortingProfileAiMessage(profile.id, response.id, {});
				messages = messages.map((m) => (m.id === response.id ? { ...m, applied_at: new Date().toISOString() } : m));
				onapplied(version);
			}
		} catch (e) {
			const failure = e as { error?: string; message?: string; code?: string };
			error = failure.error || failure.message || 'The request did not work.';
			errorCode = typeof failure.code === 'string' ? failure.code : null;
		} finally {
			busy = false;
			onbusy(false);
			progress = [];
		}
	}

	function toggleResult(key: string) {
		const next = new Set(expandedResults);
		if (next.has(key)) next.delete(key);
		else next.add(key);
		expandedResults = next;
	}

	function visibleItems(result: ExpandableToolResult, key: string): ToolResultListItem[] {
		return expandedResults.has(key) ? result.items : result.items.slice(0, TOOL_RESULT_COLLAPSED_COUNT);
	}
</script>

<!-- What a tool found, the same whether the step is done (a trace on a reply) or still running. -->
{#snippet toolResult(result: ExpandableToolResult, key: string)}
	<div class="mt-1 text-sm text-ink-muted">
		<div>{getToolResultSummaryLine(result)}</div>
		{#if result.items.length > 0}
			{#if result.layout === 'media-grid'}
				<div class="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
					{#each visibleItems(result, key) as item (item.id)}
						<figure class="overflow-hidden rounded-control bg-well">
							<div class="aspect-[4/3]">
								{#if item.imageUrl}
									<img src={item.imageUrl} alt={item.primary} class="size-full object-contain p-2" loading="lazy" />
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
					{#each visibleItems(result, key) as item (item.id)}
						<li class="flex min-w-0 items-baseline gap-2">
							<span class="size-1.5 shrink-0 translate-y-[-1px] rounded-full bg-ink-faint"></span>
							<span class="truncate text-ink">{item.primary}</span>
							{#if item.secondary}<span class="truncate">{item.secondary}</span>{/if}
						</li>
					{/each}
				</ul>
			{/if}
			{#if result.items.length > TOOL_RESULT_COLLAPSED_COUNT}
				<Button variant="ghost" size="sm" class="mt-1 -ml-2.5" onclick={() => toggleResult(key)}>
					{expandedResults.has(key)
						? 'Show less'
						: `Show all ${result.availableCount} ${result.availableCount === 1 ? result.singularLabel : result.pluralLabel}`}
				</Button>
			{/if}
		{/if}
	</div>
{/snippet}

{#snippet step(done: boolean, title: string, durationMs: number | null, result: ExpandableToolResult | null, key: string, detail: string | null)}
	<div class="flex items-start gap-2 text-sm">
		<span class="mt-0.5 flex size-4 shrink-0 items-center justify-center">
			{#if done}<Check size={14} class="text-success-ink" />{:else}<Spinner size={12} class="text-ink-muted" />{/if}
		</span>
		<div class="min-w-0 flex-1">
			<div class="flex items-center justify-between gap-2">
				<span class="text-ink">{title}</span>
				{#if formatDuration(durationMs)}<span class="num shrink-0 text-ink-faint">{formatDuration(durationMs)}</span>{/if}
			</div>
			{#if result}
				{@render toolResult(result, key)}
			{:else if detail}
				<div class="markdown-body markdown-compact mt-0.5 text-ink-muted">{@html renderMarkdown(detail)}</div>
			{/if}
		</div>
	</div>
{/snippet}

<div class="flex min-h-0 flex-1 flex-col {active ? '' : 'hidden'}">
	{#if !hasOpenRouter}
		<div class="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
			<Sparkles size={24} class="text-ink-faint" />
			<p class="text-sm text-ink-muted">The assistant needs an OpenRouter key.</p>
			<Button href="/settings" size="sm" icon={ArrowRight}>Add one in settings</Button>
		</div>
	{:else}
		<div bind:this={scroller} class="min-h-0 flex-1 overflow-y-auto p-4">
			{#if messages.length === 0}
				<div class="flex h-full flex-col items-center justify-center gap-1 text-center">
					<Sparkles size={24} class="mb-2 text-ink-faint" />
					<p class="text-sm font-medium text-ink">Describe what you want to sort</p>
					<p class="text-sm text-ink-muted">The assistant makes the rules, changes them, and saves a version.</p>
				</div>
			{:else}
				<div class="flex min-w-0 flex-col gap-4">
					{#each messages as msg (msg.id)}
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
					{#if error}
						<div class="mr-8">
							<Alert tone="danger" title={error}>
								{#if errorCode?.startsWith('OPENROUTER_')}The OpenRouter key in your settings needs fixing.{/if}
								{#snippet actions()}
									{#if errorCode?.startsWith('OPENROUTER_')}
										<Button href="/settings" size="sm">Settings</Button>
									{/if}
								{/snippet}
							</Alert>
						</div>
					{/if}
					{#if busy}
						<div class="mr-8 flex flex-col gap-2" aria-live="polite">
							{#each visibleCards as card (card.id)}
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

		{#if dirty}
			<div class="border-t border-line px-3 pt-3">
				<Alert tone="warning">
					The assistant works on the saved version. Save your changes first, or they are replaced when it saves.
				</Alert>
			</div>
		{/if}
		<form
			class="flex gap-2 border-t border-line p-3 {dirty ? 'border-t-0' : ''}"
			onsubmit={(e) => {
				e.preventDefault();
				void send();
			}}
		>
			<Input
				class="min-w-0 flex-1"
				aria-label="Tell the assistant what to change"
				bind:value={draft}
				disabled={busy}
				autocomplete="off"
				placeholder={isNewProfile && rulesCount === 0
					? 'For example: sort Technic parts by what they do, gears, beams, connectors'
					: 'Describe a change'}
			/>
			<Button type="submit" variant="primary" icon={Send} loading={busy} disabled={!draft.trim()}>Send</Button>
		</form>
	{/if}
</div>
