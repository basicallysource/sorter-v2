<!--
	How far each of the owner's machines is with a profile's kits: per machine,
	the version it wants and runs and how much of all its kits it has
	collected, then each kit as a bin with its own found / needed. Asks Hive
	every ten seconds while it is on the page, since machines report as they
	sort. Only for a profile that has kits.
-->
<script lang="ts">
	import { api, type SortingProfileSetProgressResponse } from '$lib/api';
	import { relativeTime } from '$lib/time';
	import Alert from '$lib/components/Alert.svelte';
	import Button from '$lib/components/Button.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import ProfileBin, { type Bin } from '$lib/components/ProfileBin.svelte';
	import ProgressBar from '$lib/components/ProgressBar.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import ArrowRight from '@lucide/svelte/icons/arrow-right';

	let { profileId, bins }: { profileId: string; bins: Record<string, Bin & { kit?: { set_num?: string | null } }> } =
		$props();

	let progress = $state<SortingProfileSetProgressResponse | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);

	$effect(() => {
		const id = profileId;
		let stopped = false;
		async function load() {
			try {
				const res = await api.getSortingProfileSetProgress(id);
				if (!stopped) {
					progress = res;
					error = null;
				}
			} catch (e: any) {
				if (!stopped) error = e.error || 'Could not load the kits\' progress.';
			} finally {
				if (!stopped) loading = false;
			}
		}
		void load();
		const timer = setInterval(() => {
			if (document.visibilityState === 'visible') void load();
		}, 10000);
		return () => {
			stopped = true;
			clearInterval(timer);
		};
	});

	// The kit bin a machine's progress line is for, so it shows the kit's
	// picture. The line is named by the kit's set, or by the kit rule's own ID
	// when the kit is not from a set; a kit the page's version no longer has
	// shows by its name.
	function binFor(set: { set_num: string; name: string }): Bin {
		const byRule = bins[set.set_num];
		if (byRule?.kind === 'kit') return byRule;
		const known = Object.values(bins).find(
			(bin) => bin.kind === 'kit' && (bin.kit?.set_num === set.set_num || bin.name === set.name)
		);
		return known ?? { name: set.name, kind: 'kit' };
	}

	const machines = $derived(progress?.machines ?? []);
</script>

<Panel title="Kit progress" description="What your machines have collected for this profile's kits." flush>
	{#snippet actions()}
		<Button href="/machines" size="sm" variant="ghost" icon={ArrowRight}>Machines</Button>
	{/snippet}
	{#if error}
		<div class="px-(--pad-panel) pb-(--pad-panel)"><Alert tone="danger">{error}</Alert></div>
	{:else if loading && !progress}
		<p class="flex items-center justify-center gap-2 px-(--pad-panel) pb-(--pad-panel) text-sm text-ink-muted">
			<Spinner size={16} />Loading progress
		</p>
	{:else if machines.length === 0}
		<div class="px-(--pad-panel) pb-(--pad-panel)">
			<EmptyState title="No progress yet">
				None of your machines is sorting with this profile and reporting progress.
			</EmptyState>
		</div>
	{:else}
		<ul class="divide-y divide-line">
			{#each machines as machine (machine.machine_id)}
				<li class="flex flex-col gap-3 pt-3">
					<div class="flex flex-col gap-1.5 px-(--pad-panel)">
						<div class="flex items-baseline justify-between gap-3">
							<span class="min-w-0 truncate text-sm font-medium text-ink">{machine.machine_name}</span>
							<span class="num shrink-0 text-sm text-ink">
								{machine.overall_found.toLocaleString('en-US')}
								<span class="text-ink-muted">of {machine.overall_needed.toLocaleString('en-US')}</span>
							</span>
						</div>
						<ProgressBar
							label="{machine.machine_name} progress"
							value={Math.min(machine.overall_pct, 100)}
							tone={machine.overall_pct >= 100 ? 'success' : 'primary'}
						/>
						<p class="text-sm text-ink-muted">
							Wants v{machine.desired_version_number ?? '?'}, {machine.active_version_number
								? `running v${machine.active_version_number}`
								: 'waiting to switch'}{#if machine.updated_at}. Updated {relativeTime(machine.updated_at)}.{/if}
						</p>
					</div>
					{#if machine.sets.length > 0}
						<ul class="divide-y divide-line border-t border-line">
							{#each machine.sets as set (set.set_num)}
								<li>
									<ProfileBin
										layout="row"
										bin={binFor(set)}
										progress={{ found: set.total_found, needed: set.total_needed }}
									/>
								</li>
							{/each}
						</ul>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}
</Panel>
