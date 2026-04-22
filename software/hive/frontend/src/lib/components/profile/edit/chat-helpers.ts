import type { AiToolTraceItem, SortingProfileAiMessage } from '$lib/api';

export type ToolResultListItem = {
	id: string;
	primary: string;
	secondary: string | null;
	imageUrl?: string | null;
};

export type ExpandableToolResult = {
	layout: 'list' | 'media-grid';
	total: number;
	availableCount: number;
	singularLabel: string;
	pluralLabel: string;
	emptyMessage: string;
	items: ToolResultListItem[];
};

export type AiProgressEvent = {
	type: string;
	tool?: string;
	input?: Record<string, unknown>;
	output_summary?: string;
	output?: Record<string, unknown> | null;
	duration_ms?: number;
};

export type AiProgressCard = {
	id: string;
	kind: 'analysis' | 'tool' | 'writing' | 'applying';
	status: 'active' | 'complete';
	title: string;
	detail: string | null;
	tool?: string;
	output?: Record<string, unknown> | null;
	durationMs?: number | null;
};

export const TOOL_RESULT_COLLAPSED_COUNT = 5;

export function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null;
}

export function asNumber(value: unknown): number | null {
	return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function asString(value: unknown): string | null {
	return typeof value === 'string' && value.trim() ? value.trim() : null;
}

export function searchScopeSuffix(input: Record<string, unknown> | undefined): string {
	if (!input) return '';
	const minYear = typeof input.min_year === 'number' ? input.min_year : null;
	const maxYear = typeof input.max_year === 'number' ? input.max_year : null;
	if (minYear && maxYear && minYear === maxYear) return ` from ${minYear}`;
	if (minYear && maxYear) return ` from ${minYear} to ${maxYear}`;
	if (minYear) return ` from ${minYear} or newer`;
	if (maxYear) return ` up to ${maxYear}`;
	return '';
}

export function toolSearchSubject(tool: string | undefined, input: Record<string, unknown> | undefined): string {
	const query = typeof input?.query === 'string' && input.query.trim() ? input.query.trim() : 'your query';
	if (tool === 'search_sets') return `LEGO sets matching "${query}"${searchScopeSuffix(input)}`;
	if (tool === 'search_parts') return `LEGO parts matching "${query}"`;
	if (tool === 'get_set_inventory') {
		const setNum = typeof input?.set_num === 'string' && input.set_num.trim() ? input.set_num.trim() : 'that set';
		return `pieces in LEGO set "${setNum}"`;
	}
	return 'catalog data';
}

export function toolStageTitle(
	tool: string | undefined,
	input: Record<string, unknown> | undefined,
	status: 'active' | 'complete'
): string {
	const prefix = status === 'active' ? 'Checking' : 'Checked';
	return `${prefix} ${toolSearchSubject(tool, input)}`;
}

export function toolActiveDetail(tool: string | undefined, input: Record<string, unknown> | undefined): string {
	if (tool === 'search_sets') {
		const scope = searchScopeSuffix(input);
		return scope
			? `I am looking through the set catalog${scope} now.`
			: 'I am looking through the set catalog now.';
	}
	if (tool === 'search_parts') {
		return 'I am checking the parts catalog for matching pieces.';
	}
	if (tool === 'get_set_inventory') {
		return 'I am looking through the set inventory and piece list.';
	}
	return 'I am gathering the information I need.';
}

export function toolTraceTitle(item: AiToolTraceItem): string {
	return toolStageTitle(item.tool, item.input, 'complete');
}

export function formatDuration(ms: number | null | undefined): string | null {
	if (typeof ms !== 'number' || !Number.isFinite(ms) || ms < 0) return null;
	if (ms >= 60000) return `${(ms / 60000).toFixed(1)} min`;
	if (ms >= 10000) return `${Math.round(ms / 1000)} s`;
	if (ms >= 1000) return `${(ms / 1000).toFixed(1)} s`;
	return `${Math.round(ms)} ms`;
}

function aiMessagePerformance(message: SortingProfileAiMessage): {
	totalMs: number | null;
	llmMs: number | null;
	toolMs: number | null;
	roundCount: number | null;
	toolCallCount: number | null;
} | null {
	const performance = message.usage?.performance;
	if (!isRecord(performance)) return null;
	const totalMs = asNumber(performance.total_ms);
	const llmMs = asNumber(performance.llm_ms);
	const toolMs = asNumber(performance.tool_ms);
	const roundCount = asNumber(performance.round_count);
	const toolCallCount = asNumber(performance.tool_call_count);
	if (totalMs === null && llmMs === null && toolMs === null) return null;
	return { totalMs, llmMs, toolMs, roundCount, toolCallCount };
}

export function aiMessagePerformanceLabel(message: SortingProfileAiMessage): string | null {
	const perf = aiMessagePerformance(message);
	if (!perf) return null;
	const parts: string[] = [];
	const total = formatDuration(perf.totalMs);
	const llm = formatDuration(perf.llmMs);
	const tool = formatDuration(perf.toolMs);
	if (total) parts.push(`Total ${total}`);
	if (llm) parts.push(`Model ${llm}`);
	if (tool && perf.toolMs && perf.toolMs > 0) parts.push(`Tools ${tool}`);
	if (typeof perf.roundCount === 'number' && perf.roundCount > 1) parts.push(`${perf.roundCount} rounds`);
	if (typeof perf.toolCallCount === 'number' && perf.toolCallCount > 0) parts.push(`${perf.toolCallCount} tool calls`);
	return parts.length > 0 ? parts.join(' · ') : null;
}

function formatToolResultCount(result: ExpandableToolResult): string {
	const label = result.total === 1 ? result.singularLabel : result.pluralLabel;
	return `${result.total} ${label}`;
}

export function getToolResultSummaryLine(result: ExpandableToolResult): string {
	if (result.total === 0) return result.emptyMessage;
	if (result.availableCount < result.total) {
		return `Showing ${result.availableCount} of ${formatToolResultCount(result)} returned by the search.`;
	}
	return `Found ${formatToolResultCount(result)}.`;
}

function buildSetToolResult(output: Record<string, unknown>): ExpandableToolResult | null {
	const rawSets = Array.isArray(output.sets) ? output.sets.filter(isRecord) : [];
	const items = rawSets.map((legoSet, index) => {
		const name = asString(legoSet.name) ?? 'Unnamed set';
		const partCount = asNumber(legoSet.num_parts);
		const badges = [
			asString(legoSet.set_num),
			asNumber(legoSet.year)?.toString() ?? null,
			partCount !== null ? `${partCount} parts` : null
		].filter((value): value is string => Boolean(value));
		return {
			id: asString(legoSet.set_num) ?? `set-${index}`,
			primary: name,
			secondary: badges.length > 0 ? badges.join(' · ') : null,
			imageUrl: asString(legoSet.img_url) ?? asString(legoSet.set_img_url)
		};
	});
	const total = asNumber(output.total) ?? items.length;
	return {
		layout: 'media-grid',
		total,
		availableCount: items.length,
		singularLabel: 'set',
		pluralLabel: 'sets',
		emptyMessage: 'No sets found.',
		items
	};
}

function buildPartToolResult(output: Record<string, unknown>): ExpandableToolResult | null {
	const rawParts = Array.isArray(output.parts) ? output.parts.filter(isRecord) : [];
	const items = rawParts.map((part, index) => {
		const name = asString(part.name) ?? 'Unnamed part';
		const bits = [
			asString(part.part_num),
			asString(part.category),
			asString(part.years)
		].filter(Boolean);
		return {
			id: asString(part.part_num) ?? `part-${index}`,
			primary: name,
			secondary: bits.length > 0 ? bits.join(' · ') : null
		};
	});
	const total = asNumber(output.total) ?? items.length;
	return {
		layout: 'list',
		total,
		availableCount: items.length,
		singularLabel: 'part',
		pluralLabel: 'parts',
		emptyMessage: 'No parts found.',
		items
	};
}

function buildSetInventoryToolResult(output: Record<string, unknown>): ExpandableToolResult | null {
	const rawInventory = Array.isArray(output.inventory) ? output.inventory.filter(isRecord) : [];
	const items = rawInventory.map((part, index) => {
		const name = asString(part.part_name) ?? asString(part.part_num) ?? 'Unnamed part';
		const bits = [
			asString(part.part_num),
			asString(part.color_name) ?? (asNumber(part.color_id)?.toString() ?? null),
			asNumber(part.quantity) !== null ? `qty ${asNumber(part.quantity)}` : null,
			part.is_spare ? 'spare' : null
		].filter(Boolean);
		return {
			id: `${asString(part.part_num) ?? 'part'}-${asString(part.color_name) ?? asNumber(part.color_id) ?? index}-${index}`,
			primary: name,
			secondary: bits.length > 0 ? bits.join(' · ') : null,
			imageUrl: asString(part.img_url)
		};
	});
	const total = asNumber(output.total) ?? items.length;
	return {
		layout: 'media-grid',
		total,
		availableCount: items.length,
		singularLabel: 'inventory entry',
		pluralLabel: 'inventory entries',
		emptyMessage: 'No inventory entries found.',
		items
	};
}

export function getExpandableToolResult(
	tool: string | undefined,
	output: Record<string, unknown> | null | undefined
): ExpandableToolResult | null {
	if (!output) return null;
	if (tool === 'search_sets') return buildSetToolResult(output);
	if (tool === 'search_parts') return buildPartToolResult(output);
	if (tool === 'get_set_inventory') return buildSetInventoryToolResult(output);
	return null;
}

export function parseEmbeddedProposal(content: string): Record<string, unknown> | null {
	const trimmed = content.trim();
	if (!trimmed) return null;

	const candidates: string[] = [trimmed];
	const fencedMatches = trimmed.matchAll(/```(?:json)?\s*([\s\S]*?)```/gi);
	for (const match of fencedMatches) {
		const candidate = match[1]?.trim();
		if (candidate) candidates.push(candidate);
	}

	const unterminatedFence = trimmed.match(/```(?:json)?\s*([\s\S]*)$/i);
	if (unterminatedFence?.[1]?.trim()) {
		candidates.push(unterminatedFence[1].trim());
	}

	for (const candidate of candidates) {
		try {
			const parsed = JSON.parse(candidate);
			if (parsed && typeof parsed === 'object') {
				return parsed as Record<string, unknown>;
			}
		} catch {
			// ignore candidate
		}
	}

	return null;
}

export function displayAiMessageContent(content: string): string {
	const parsed = parseEmbeddedProposal(content);
	const summary = typeof parsed?.summary === 'string' ? parsed.summary.trim() : '';
	const contentWithoutJsonFence = content
		.replace(/```(?:json)?\s*[\s\S]*?```/gi, '')
		.replace(/```(?:json)?\s*[\s\S]*$/gi, '')
		.trim();

	if (summary && (!contentWithoutJsonFence || content.trim().startsWith('{'))) {
		return summary;
	}

	if (contentWithoutJsonFence) {
		return contentWithoutJsonFence;
	}

	return summary || content;
}

export function buildAiProgressCards(events: AiProgressEvent[]): AiProgressCard[] {
	const cards: AiProgressCard[] = [];
	let counter = 0;

	function completeActiveAnalysis(nextTitle: string) {
		const card = [...cards].reverse().find((entry) => entry.kind === 'analysis' && entry.status === 'active');
		if (!card) return;
		card.status = 'complete';
		card.title = nextTitle;
	}

	for (const event of events) {
		if (event.type === 'thinking') {
			const hasCompletedTool = cards.some((card) => card.kind === 'tool' && card.status === 'complete');
			const activeAnalysis = [...cards].reverse().find(
				(card) => card.kind === 'analysis' && card.status === 'active'
			);
			const title = hasCompletedTool ? 'Reviewing the matches' : 'Understanding your request';
			const detail = hasCompletedTool
				? 'I am deciding which results fit what you asked for.'
				: 'I am figuring out what should be added or changed.';
			if (activeAnalysis) {
				activeAnalysis.title = title;
				activeAnalysis.detail = detail;
			} else {
				cards.push({
					id: `analysis-${counter++}`,
					kind: 'analysis',
					status: 'active',
					title,
					detail
				});
			}
			continue;
		}

		if (event.type === 'tool_call') {
			completeActiveAnalysis('Request understood');
			cards.push({
				id: `tool-${counter++}`,
				kind: 'tool',
				status: 'active',
				title: toolStageTitle(event.tool, event.input, 'active'),
				detail: toolActiveDetail(event.tool, event.input),
				tool: event.tool,
				output: null,
				durationMs: null
			});
			continue;
		}

		if (event.type === 'tool_result') {
			const activeTool = cards.find(
				(card) => card.kind === 'tool' && card.status === 'active' && card.tool === event.tool
			);
			if (activeTool) {
				activeTool.status = 'complete';
				activeTool.title = toolStageTitle(event.tool, event.input, 'complete');
				activeTool.detail = event.output_summary ?? 'Done.';
				activeTool.output = event.output ?? null;
				activeTool.durationMs = event.duration_ms ?? null;
			} else {
				cards.push({
					id: `tool-${counter++}`,
					kind: 'tool',
					status: 'complete',
					title: toolStageTitle(event.tool, event.input, 'complete'),
					detail: event.output_summary ?? 'Done.',
					tool: event.tool,
					output: event.output ?? null,
					durationMs: event.duration_ms ?? null
				});
			}
			continue;
		}

		if (event.type === 'generating') {
			completeActiveAnalysis('Results reviewed');
			const activeWriting = [...cards].reverse().find(
				(card) => card.kind === 'writing' && card.status === 'active'
			);
			if (!activeWriting) {
				cards.push({
					id: `writing-${counter++}`,
					kind: 'writing',
					status: 'active',
					title: 'Preparing the update',
					detail: 'I am turning that into clear rule changes.'
				});
			}
			continue;
		}

		if (event.type === 'applying') {
			const activeWriting = [...cards].reverse().find(
				(card) => card.kind === 'writing' && card.status === 'active'
			);
			if (activeWriting) {
				activeWriting.status = 'complete';
				activeWriting.title = 'Update prepared';
			}
			const activeApplying = [...cards].reverse().find(
				(card) => card.kind === 'applying' && card.status === 'active'
			);
			if (!activeApplying) {
				cards.push({
					id: `applying-${counter++}`,
					kind: 'applying',
					status: 'active',
					title: 'Saving the changes',
					detail: 'I am updating the profile now.'
				});
			}
		}
	}

	return cards;
}

export function proposalActionSummaries(proposal: Record<string, unknown> | null): string[] {
	if (!proposal) return [];
	const proposals = proposal.proposals;
	if (!Array.isArray(proposals)) return [];
	return proposals.map((p: Record<string, unknown>) => {
		const action = p.action as string;
		const name = (p.name as string) || 'rule';
		if (action === 'create') return `Created "${name}"`;
		if (action === 'create_set') return `Added set "${name}"`;
		if (action === 'edit') return `Edited "${name}"`;
		if (action === 'move') return `Moved "${name}"`;
		if (action === 'delete') return `Deleted "${name}"`;
		return `${action} "${name}"`;
	});
}
