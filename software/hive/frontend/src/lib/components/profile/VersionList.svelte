<!--
	A profile's versions, newest first, each with when it was saved, who saved
	it (the editor, the editor's chat, an API key, Hive), its change note and
	how many rules it has. The one on the page is tinted, like the chosen item
	of any list; choosing another shows it. On the owner's page a published
	version says so, and the one on the page, when it is not, can be published,
	which is what lets other people's machines use it.
-->
<script lang="ts">
	import type { SortingProfileVersionSummary } from '$lib/api';
	import { plural, savedLine } from '$lib/profile-display';
	import Badge from '$lib/components/Badge.svelte';
	import Button from '$lib/components/Button.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import Globe from '@lucide/svelte/icons/globe';

	let {
		versions,
		shownId,
		isOwner,
		publishingId = null,
		onpick,
		onpublish
	}: {
		// Newest first.
		versions: SortingProfileVersionSummary[];
		shownId: string | null;
		isOwner: boolean;
		publishingId?: string | null;
		onpick: (version: SortingProfileVersionSummary) => void;
		onpublish: (version: SortingProfileVersionSummary) => void;
	} = $props();

	const latestId = $derived(versions[0]?.id ?? null);

	function rules(version: SortingProfileVersionSummary) {
		return version.rules_summary.filter((rule) => !rule.disabled).length;
	}
</script>

<Panel title="Versions" description={plural(versions.length, 'version')} flush>
	<ul class="max-h-[28rem] divide-y divide-line overflow-y-auto">
		{#each versions as version (version.id)}
			{@const on = version.id === shownId}
			<li class="relative isolate {on ? 'bg-primary-soft' : ''}">
				<button
					type="button"
					aria-label="Show version {version.version_number}"
					aria-current={on ? 'true' : undefined}
					onclick={() => onpick(version)}
					class="absolute inset-0 transition-colors hover:bg-hover active:bg-pressed"
				></button>
				<div
					class="pointer-events-none relative flex flex-col gap-1 px-(--pad-panel) py-3 [&_button]:pointer-events-auto"
				>
					<div class="flex flex-wrap items-center gap-x-2 gap-y-1">
						<span class="num text-sm font-medium text-ink">v{version.version_number}</span>
						{#if version.id === latestId}<Badge>Latest</Badge>{/if}
						{#if isOwner && version.is_published}<Badge tone="success">Published</Badge>{/if}
						<span class="num ml-auto text-sm text-ink-muted">
							{rules(version) === 0 ? 'No rules' : plural(rules(version), 'rule')}
						</span>
					</div>
					<div class="text-sm text-ink-muted">{savedLine(version)}</div>
					{#if version.change_note}
						<p class="line-clamp-3 text-sm text-ink">{version.change_note}</p>
					{/if}
					{#if isOwner && on && !version.is_published}
						<div class="mt-1">
							<Button
								size="sm"
								icon={Globe}
								loading={publishingId === version.id}
								onclick={() => onpublish(version)}>Publish v{version.version_number}</Button
							>
						</div>
					{/if}
				</div>
			</li>
		{/each}
	</ul>
</Panel>
