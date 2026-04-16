<script lang="ts">
	import { renderMarkdown } from '$lib/markdown';
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

<div class="flex min-h-0 min-w-0 flex-col overflow-hidden border border-border bg-white">
	<div class="flex border-b border-border">
		<button onclick={() => onRightTabChange('chat')}
			class="flex-1 px-4 py-2 text-center text-sm font-medium transition-colors
				{rightTab === 'chat' ? 'border-b-2 border-b-primary text-primary' : 'text-text-muted hover:text-text'}">
			Chat
		</button>
		<button onclick={() => onRightTabChange('versions')}
			class="flex-1 px-4 py-2 text-center text-sm font-medium transition-colors
				{rightTab === 'versions' ? 'border-b-2 border-b-primary text-primary' : 'text-text-muted hover:text-text'}">
			Versions
			<span class="ml-1 text-xs font-normal text-text-muted">· {profile.versions.length}</span>
		</button>
	</div>

	{#if rightTab === 'versions'}
		<div class="flex-1 overflow-y-auto">
			{#if profile.versions.length === 0}
				<div class="p-6 text-center text-sm text-text-muted">No versions yet.</div>
			{:else}
				<div class="divide-y divide-border">
					{#each [...profile.versions].reverse() as version (version.id)}
						{@const isCurrent = version.id === profile.current_version?.id}
						<div class="px-4 py-3 {isCurrent ? 'bg-primary/8' : ''}">
							<div class="flex items-center justify-between">
								<div class="flex items-center gap-2">
									{#if isCurrent}
										<span class="inline-block h-2.5 w-2.5 shrink-0 bg-primary"></span>
									{/if}
									<span class="text-sm font-semibold {isCurrent ? 'text-primary' : 'text-text'}">v{version.version_number}</span>
									{#if isCurrent}
										<span class="bg-primary/8 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-primary">current</span>
									{/if}
									{#if version.is_published}
										<span class="bg-success/10 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-success">published</span>
									{/if}
								</div>
								<span class="text-xs text-text-muted">{formatDate(version.created_at)}</span>
							</div>
							{#if version.change_note}
								<p class="mt-1 text-xs text-text-muted">{version.change_note}</p>
							{/if}
							<div class="mt-1 flex items-center gap-3 text-xs text-text-muted">
								<span>{version.compiled_part_count} parts</span>
								{#if version.label}
									<span>{version.label}</span>
								{/if}
							</div>
							<div class="mt-2 flex gap-2">
								<button onclick={() => { if (isCurrent) onExitPreview(); else onViewVersion(version.id); }}
									disabled={previewLoading}
									class="border border-border px-2 py-1 text-xs font-medium text-text-muted hover:bg-bg disabled:opacity-50">
									View
								</button>
								{#if !isCurrent}
									<button onclick={() => onRestoreVersion(version.id)}
										disabled={restoringVersionId !== null}
										class="border border-border px-2 py-1 text-xs font-medium text-text-muted hover:bg-bg disabled:opacity-50">
										{restoringVersionId === version.id ? 'Restoring...' : 'Restore'}
									</button>
								{/if}
								<button onclick={() => onForkFromVersion(version.id)}
									class="border border-border px-2 py-1 text-xs font-medium text-text-muted hover:bg-bg">
									Fork
								</button>
							</div>
						</div>
					{/each}
				</div>
			{/if}
		</div>
	{:else if !hasOpenRouter}
		<div class="flex flex-1 flex-col items-center justify-center p-6 text-center">
			<svg class="mb-3 h-8 w-8 text-text-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
				<path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
			</svg>
			<p class="mb-2 text-sm text-text-muted">OpenRouter API key required for chat</p>
			<a href="/settings" class="text-sm font-medium text-primary hover:text-primary-hover">Configure in Settings</a>
		</div>
	{:else}
		<div bind:this={chatContainer} class="flex-1 overflow-y-auto p-4">
			{#if aiMessages.length === 0}
				<div class="flex h-full flex-col items-center justify-center text-center">
					<svg class="mb-3 h-8 w-8 text-text-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
						<path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
					</svg>
					<p class="mb-1 text-sm font-medium text-text">Describe what you want to sort</p>
					<p class="text-xs text-text-muted">Use chat to create categories, add rules, and refine your sorting logic.</p>
				</div>
			{:else}
				<div class="space-y-4 min-w-0">
					{#each aiMessages as msg (msg.id)}
						<div class="{msg.role === 'user' ? 'ml-8' : 'mr-8'} min-w-0">
							{#if msg.role === 'assistant'}
								{#if msg.tool_trace?.length}
									<div class="mb-3 space-y-2">
										{#each msg.tool_trace as trace, traceIndex}
											{@const resultView = getExpandableToolResult(trace.tool, trace.output)}
											{@const resultKey = `${msg.id}-trace-${traceIndex}`}
											<div class="min-w-0 overflow-hidden border border-success/15 bg-success/5 px-3 py-2.5 text-xs">
												<div class="flex items-start gap-2">
													<div class="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center text-success">
														<svg class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
															<path fill-rule="evenodd" d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z" clip-rule="evenodd" />
														</svg>
													</div>
													<div class="min-w-0">
														<div class="flex items-center justify-between gap-2">
															<div class="font-medium text-success">{toolTraceTitle(trace)}</div>
															{#if formatDuration(trace.duration_ms ?? null)}
																<div class="shrink-0 text-[11px] font-medium text-success/60">{formatDuration(trace.duration_ms ?? null)}</div>
															{/if}
														</div>
														{#if resultView}
															<div class="mt-1 text-success/70">
																<div class="text-[11px] font-medium uppercase tracking-[0.08em] text-success/60">
																	{getToolResultSummaryLine(resultView)}
																</div>
																{#if resultView.items.length > 0}
																	{#if resultView.layout === 'media-grid'}
																		<div class="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
																			{#each visibleToolResultItems(resultView, resultKey) as item (item.id)}
																				<div class="overflow-hidden border border-success/15 bg-white/80">
																					<div class="relative aspect-[4/3] border-b border-success/10 bg-success/5">
																						{#if item.imageUrl}
																							<img src={item.imageUrl} alt={item.primary} class="h-full w-full object-contain p-2" loading="lazy" />
																						{:else}
																							<div class="flex h-full items-center justify-center text-[11px] font-medium uppercase tracking-[0.12em] text-success/40">No image</div>
																						{/if}
																					</div>
																					<div class="px-2.5 py-2">
																						<div class="line-clamp-2 font-medium text-success">{item.primary}</div>
																						{#if item.secondary}
																							<div class="mt-1 line-clamp-2 text-success/60">{item.secondary}</div>
																						{/if}
																					</div>
																				</div>
																			{/each}
																		</div>
																	{:else}
																		<div class="mt-2 space-y-1.5">
																			{#each visibleToolResultItems(resultView, resultKey) as item (item.id)}
																				<div class="flex items-start gap-2 border border-success/15 bg-white/70 px-2 py-1.5">
																					<div class="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-[#2F6B42]"></div>
																					<div class="min-w-0">
																						<div class="truncate font-medium text-success">{item.primary}</div>
																						{#if item.secondary}
																							<div class="truncate text-success/60">{item.secondary}</div>
																						{/if}
																					</div>
																				</div>
																			{/each}
																		</div>
																	{/if}
																	{#if canExpandToolResult(resultView)}
																		<button onclick={() => onToggleToolResult(resultKey)}
																			class="mt-2 text-[11px] font-medium text-success hover:underline">
																			{#if isToolResultExpanded(resultKey)}
																				Show less
																			{:else}
																				Show all {resultView.availableCount} {resultView.availableCount === 1 ? resultView.singularLabel : resultView.pluralLabel}
																			{/if}
																		</button>
																	{/if}
																{/if}
															</div>
														{:else}
															<div class="markdown-body markdown-compact mt-0.5 text-success/70">
																{@html renderMarkdown(trace.output_summary)}
															</div>
														{/if}
													</div>
												</div>
											</div>
										{/each}
									</div>
								{/if}
								<div class="chat-message-assistant min-w-0 overflow-hidden p-3 text-sm">
									<div class="markdown-body overflow-x-auto">
										{@html renderMarkdown(displayAiMessageContent(msg.content))}
									</div>
									{#if aiMessagePerformanceLabel(msg)}
										<div class="mt-2 text-[11px] text-text-muted">
											{aiMessagePerformanceLabel(msg)}
										</div>
									{/if}
									{#if msg.applied_at && msg.proposal}
										{@const actions = proposalActionSummaries(msg.proposal)}
										{#if actions.length}
											<div class="mt-2 space-y-0.5 border-t border-border pt-2">
												{#each actions as action}
													<div class="flex items-center gap-1.5 text-xs text-success">
														<svg class="h-3 w-3 shrink-0" viewBox="0 0 20 20" fill="currentColor">
															<path fill-rule="evenodd" d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z" clip-rule="evenodd" />
														</svg>
														{action}
													</div>
												{/each}
											</div>
										{/if}
									{/if}
								</div>
							{:else}
								<div class="chat-message-user min-w-0 overflow-hidden p-3 text-sm">
									<div class="whitespace-pre-wrap">{msg.content}</div>
								</div>
							{/if}
						</div>
					{/each}
					{#if aiBusy}
						<div class="mr-8">
							<div class="mb-2 space-y-2" aria-live="polite">
								{#each visibleAiProgressCards as card (card.id)}
									{@const resultView = getExpandableToolResult(card.tool, card.output)}
									<div class="px-3 py-2.5 text-xs {card.status === 'active' ? 'border border-[#E7D7AA] bg-[#FFF9E8]' : 'border border-[#CDE5D5] bg-[#F2FAF5]'}">
										<div class="flex items-start gap-2">
											<div class="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center {card.status === 'active' ? 'text-[#8A6D1F]' : 'text-success'}">
												{#if card.status === 'active'}
													<svg class="h-3.5 w-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
														<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
														<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"></path>
													</svg>
												{:else}
													<svg class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
														<path fill-rule="evenodd" d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z" clip-rule="evenodd" />
													</svg>
												{/if}
											</div>
											<div class="min-w-0 flex-1">
												<div class="flex items-center justify-between gap-2">
													<div class="font-medium {card.status === 'active' ? 'text-[#6B571C]' : 'text-success'}">{card.title}</div>
													{#if formatDuration(card.durationMs ?? null)}
														<div class="shrink-0 text-[11px] font-medium {card.status === 'active' ? 'text-[#8A6D1F]/70' : 'text-success/60'}">{formatDuration(card.durationMs ?? null)}</div>
													{/if}
												</div>
												{#if resultView}
													<div class="mt-1 {card.status === 'active' ? 'text-[#7D6C3B]' : 'text-success/70'}">
														<div class="text-[11px] font-medium uppercase tracking-[0.08em] {card.status === 'active' ? 'text-[#8A6D1F]' : 'text-success/60'}">
															{getToolResultSummaryLine(resultView)}
														</div>
														{#if resultView.items.length > 0}
															{#if resultView.layout === 'media-grid'}
																<div class="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
																	{#each visibleToolResultItems(resultView, card.id) as item (item.id)}
																		<div class="overflow-hidden border {card.status === 'active' ? 'border-[#E7D7AA] bg-white/70' : 'border-success/15 bg-white/80'}">
																			<div class="relative aspect-[4/3] border-b {card.status === 'active' ? 'border-[#F0E2BD] bg-[#FFFDF5]' : 'border-success/10 bg-success/5'}">
																				{#if item.imageUrl}
																					<img src={item.imageUrl} alt={item.primary} class="h-full w-full object-contain p-2" loading="lazy" />
																				{:else}
																					<div class="flex h-full items-center justify-center text-[11px] font-medium uppercase tracking-[0.12em] {card.status === 'active' ? 'text-[#CCBC8C]' : 'text-success/40'}">No image</div>
																				{/if}
																			</div>
																			<div class="px-2.5 py-2">
																				<div class="line-clamp-2 font-medium {card.status === 'active' ? 'text-[#6B571C]' : 'text-success'}">{item.primary}</div>
																				{#if item.secondary}
																					<div class="mt-1 line-clamp-2 {card.status === 'active' ? 'text-[#7D6C3B]' : 'text-success/60'}">{item.secondary}</div>
																				{/if}
																			</div>
																		</div>
																	{/each}
																</div>
															{:else}
																<div class="mt-2 space-y-1.5">
																	{#each visibleToolResultItems(resultView, card.id) as item (item.id)}
																		<div class="flex items-start gap-2 border px-2 py-1.5 {card.status === 'active' ? 'border-[#E7D7AA] bg-white/60' : 'border-success/15 bg-white/70'}">
																			<div class="mt-1 h-1.5 w-1.5 shrink-0 rounded-full {card.status === 'active' ? 'bg-[#8A6D1F]' : 'bg-[#2F6B42]'}"></div>
																			<div class="min-w-0">
																				<div class="truncate font-medium {card.status === 'active' ? 'text-[#6B571C]' : 'text-success'}">{item.primary}</div>
																				{#if item.secondary}
																					<div class="truncate {card.status === 'active' ? 'text-[#7D6C3B]' : 'text-success/60'}">{item.secondary}</div>
																				{/if}
																			</div>
																		</div>
																	{/each}
																</div>
															{/if}
															{#if canExpandToolResult(resultView)}
																<button onclick={() => onToggleToolResult(card.id)}
																	class="mt-2 text-[11px] font-medium {card.status === 'active' ? 'text-[#8A6D1F]' : 'text-success'} hover:underline">
																	{#if isToolResultExpanded(card.id)}
																		Show less
																	{:else}
																		Show all {resultView.availableCount} {resultView.availableCount === 1 ? resultView.singularLabel : resultView.pluralLabel}
																	{/if}
																</button>
															{/if}
														{/if}
													</div>
												{:else if card.detail}
													<div class="markdown-body markdown-compact mt-0.5 {card.status === 'active' ? 'text-[#7D6C3B]' : 'text-success/70'}">
														{@html renderMarkdown(card.detail)}
													</div>
												{/if}
											</div>
										</div>
									</div>
								{/each}
							</div>
						</div>
					{/if}
				</div>
			{/if}
		</div>

		<div class="border-t border-border p-3">
			<div class="flex gap-2">
				<input type="text" value={aiMessage}
					oninput={(e) => onAiMessageChange((e.currentTarget as HTMLInputElement).value)}
					placeholder={isNewProfile && workingRulesLength === 0
						? 'e.g. Sort Technic parts by function: gears, beams, connectors...'
						: 'Describe a change...'}
					class="min-w-0 flex-1 border border-border px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
					onkeydown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onSendAiMessage(); } }}
					disabled={aiBusy} />
				<button onclick={onSendAiMessage} disabled={aiBusy || !aiMessage.trim()}
					class="bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">
					{aiBusy ? '...' : 'Send'}
				</button>
			</div>
		</div>
	{/if}
</div>
