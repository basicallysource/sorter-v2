<script lang="ts">
	import { onMount } from 'svelte';
	import RecordsStats, {
		type Lifetime,
		type Overview,
		type ValueStats
	} from '$lib/components/records/RecordsStats.svelte';
	import RecordsCharts from '$lib/components/records/RecordsCharts.svelte';
	import DailyTable from '$lib/components/records/DailyTable.svelte';
	import { recordsBase } from '$lib/records/base';

	const base = recordsBase();

	let overview = $state<Overview | null>(null);
	let lifetime = $state<Lifetime | null>(null);
	let value = $state<ValueStats | null>(null);

	async function load<T>(path: string): Promise<T | null> {
		try {
			const res = await fetch(`${base()}${path}`);
			return res.ok ? ((await res.json()) as T) : null;
		} catch {
			return null;
		}
	}

	onMount(async () => {
		void load<Overview>('/api/pieces/overview').then((v) => (overview = v ?? overview));
		void load<Lifetime>('/api/pieces/lifetime?daily_days=365').then(
			(v) => (lifetime = v ?? lifetime)
		);
		void load<ValueStats>('/api/pieces/value').then((v) => (value = v ?? value));
	});
</script>

<svelte:head>
	<title>Overview - Records - Sorter</title>
</svelte:head>

<RecordsStats {overview} {lifetime} {value} />

<RecordsCharts endpointBase={base()} />

<DailyTable daily={lifetime?.daily ?? []} exportUrl={`${base()}/api/pieces/lifetime/export.csv`} />
