<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { backendHttpBaseUrl } from '$lib/backend';

	type DossierRow = {
		piece_uuid: string;
		global_id: number | null;
		angle_deg: number | null;
		exit_delta_deg: number | null;
		classify_delta_deg: number | null;
		intake_age_s: number | null;
		last_seen_age_s: number | null;
		classified_age_s: number | null;
		result_part_id?: string | null;
		result_category?: string | null;
		handoff_requested: boolean;
		distributor_ready: boolean;
		eject_enqueued: boolean;
		eject_committed: boolean;
		classify_future_pending: boolean;
		reject_reason: string | null;
		extras?: Record<string, unknown>;
	};

	type ClaimRow = { global_id: number; deadline_age_s: number; retry_count: number };

	type SlotInspect = {
		capacity: number;
		taken: number;
		available: number;
		claims: { deadline_age_s: number | null; no_expiry: boolean }[];
	};

	type RuntimeInspect = Record<string, unknown>;

	type Inspect = {
		paused?: boolean;
		tick_count?: number;
		tick_period_s?: number;
		now_mono?: number;
		runtime_health?: Record<string, { state: string; blocked_reason: string | null; last_tick_ms: number }>;
		runtime_debug?: Record<string, RuntimeInspect>;
		runtime_inspect?: Record<string, RuntimeInspect>;
		slot_debug?: Record<string, { capacity: number; taken: number; available: number }>;
		slot_inspect?: Record<string, SlotInspect>;
	};

	let inspect: Inspect | null = null;
	let error: string | null = null;
	let loading = false;
	let stepN = 1;
	let lastStepTicks: number | null = null;
	let pollHandle: ReturnType<typeof setInterval> | null = null;
	let pollWhileRunning = true;

	const RT_BASE = `${backendHttpBaseUrl}/api/rt`;

	async function fetchInspect() {
		loading = true;
		try {
			const res = await fetch(`${RT_BASE}/debug/inspect`);
			if (!res.ok) throw new Error(`inspect failed (${res.status})`);
			const json = await res.json();
			inspect = json.inspect ?? null;
			error = null;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	async function postAction(path: string, body?: unknown) {
		loading = true;
		try {
			const res = await fetch(`${RT_BASE}${path}`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: body != null ? JSON.stringify(body) : undefined
			});
			if (!res.ok) {
				const text = await res.text();
				throw new Error(`${path} failed (${res.status}): ${text}`);
			}
			const json = await res.json();
			if (json.inspect) inspect = json.inspect;
			if (json.step?.ticks_executed != null) lastStepTicks = json.step.ticks_executed;
			error = null;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	async function pause() {
		await postAction('/debug/pause');
		await fetchInspect();
	}
	async function resume() {
		await postAction('/debug/resume');
		await fetchInspect();
	}
	async function step(n: number) {
		await postAction('/debug/step', { n });
	}

	function fmt(value: number | null | undefined, digits = 1): string {
		if (value == null || Number.isNaN(value)) return '-';
		return value.toFixed(digits);
	}

	function fmtAge(value: number | null | undefined): string {
		if (value == null) return '-';
		if (value < 0.001 && value > -0.001) return '0';
		return `${value.toFixed(2)}s`;
	}

	function dossierRows(rt: RuntimeInspect | undefined): DossierRow[] {
		if (!rt) return [];
		const list = (rt as { dossiers?: DossierRow[] }).dossiers;
		return Array.isArray(list) ? list : [];
	}

	function claimRows(rt: RuntimeInspect | undefined): ClaimRow[] {
		if (!rt) return [];
		const list = (rt as { pending_downstream_claims?: ClaimRow[] }).pending_downstream_claims;
		return Array.isArray(list) ? list : [];
	}

	function rtField(rt: RuntimeInspect | undefined, key: string): unknown {
		if (!rt) return undefined;
		return (rt as Record<string, unknown>)[key];
	}

	function setupPolling() {
		teardownPolling();
		pollHandle = setInterval(() => {
			if (!inspect) return;
			if (inspect.paused) return; // no auto-poll while paused; we drive manually
			if (!pollWhileRunning) return;
			fetchInspect();
		}, 750);
	}

	function teardownPolling() {
		if (pollHandle) {
			clearInterval(pollHandle);
			pollHandle = null;
		}
	}

	onMount(() => {
		fetchInspect();
		setupPolling();
	});

	onDestroy(() => {
		teardownPolling();
	});
</script>

<svelte:head>
	<title>Step Debugger</title>
</svelte:head>

<main class="page">
	<header class="page-header">
		<h1>Step Debugger</h1>
		<p class="muted">
			Pause the orchestrator, then step one tick at a time and inspect every dossier, claim and
			slot. Polls every 750 ms while running, frozen while paused.
		</p>
	</header>

	<section class="controls">
		<div class="control-row">
			<button class="primary" disabled={loading} on:click={pause}>Pause</button>
			<button class="primary" disabled={loading} on:click={resume}>Resume</button>
			<span class="separator">|</span>
			<button disabled={loading || !inspect?.paused} on:click={() => step(1)}>Step 1</button>
			<button disabled={loading || !inspect?.paused} on:click={() => step(5)}>Step 5</button>
			<button disabled={loading || !inspect?.paused} on:click={() => step(20)}>Step 20</button>
			<input type="number" bind:value={stepN} min="1" max="100" />
			<button disabled={loading || !inspect?.paused} on:click={() => step(stepN)}>Step n</button>
			<span class="separator">|</span>
			<button disabled={loading} on:click={fetchInspect}>Refresh</button>
			<label class="poll-toggle">
				<input type="checkbox" bind:checked={pollWhileRunning} /> auto-poll while running
			</label>
		</div>
		<div class="control-status">
			<span>tick: <strong>{inspect?.tick_count ?? '-'}</strong></span>
			<span>state: <strong class="state-{inspect?.paused ? 'paused' : 'running'}">{inspect?.paused ? 'PAUSED' : 'running'}</strong></span>
			{#if lastStepTicks != null}
				<span class="muted">last step: {lastStepTicks} ticks</span>
			{/if}
			{#if error}
				<span class="err">error: {error}</span>
			{/if}
		</div>
	</section>

	{#if inspect}
		<section class="grid">
			<!-- Slots -->
			<div class="card">
				<h2>Slots</h2>
				<table>
					<thead>
						<tr><th>edge</th><th>taken</th><th>capacity</th><th>claims (deadline_in_s)</th></tr>
					</thead>
					<tbody>
						{#each Object.entries(inspect.slot_inspect ?? {}) as [edge, slot]}
							<tr>
								<td><code>{edge}</code></td>
								<td>{slot.taken}</td>
								<td>{slot.capacity}</td>
								<td class="mono">
									{#each slot.claims as claim}
										<span class="badge {claim.deadline_age_s != null && claim.deadline_age_s < 0 ? 'expired' : ''}">
											{claim.no_expiry ? '∞' : fmtAge(claim.deadline_age_s)}
										</span>
									{/each}
									{#if slot.claims.length === 0}
										<span class="muted">(none)</span>
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>

			<!-- Distributor -->
			<div class="card">
				<h2>Distributor</h2>
				<dl class="kv">
					<dt>fsm</dt><dd>{rtField(inspect.runtime_inspect?.distributor, 'fsm_state') ?? '-'}</dd>
					<dt>blocked</dt><dd>{rtField(inspect.runtime_debug?.distributor, 'blocked_reason') ?? '-'}</dd>
					<dt>upstream slot taken</dt><dd>{rtField(inspect.runtime_inspect?.distributor, 'upstream_slot_taken') ?? '-'}</dd>
					<dt>available slots</dt><dd>{rtField(inspect.runtime_inspect?.distributor, 'available_slots') ?? '-'}</dd>
				</dl>
				{#if rtField(inspect.runtime_inspect?.distributor, 'pending')}
					{@const pending = rtField(inspect.runtime_inspect?.distributor, 'pending') as Record<string, unknown>}
					<h3>pending</h3>
					<dl class="kv">
						<dt>piece_uuid</dt><dd class="mono">{(pending.piece_uuid as string)?.slice(0, 12) ?? '-'}</dd>
						<dt>target_bin</dt><dd>{(pending.target_bin_id as string) ?? '-'}</dd>
						<dt>requested_age</dt><dd>{fmtAge(pending.requested_age_s as number)}</dd>
						<dt>positioned_age</dt><dd>{fmtAge(pending.positioned_age_s as number)}</dd>
						<dt>ready_age</dt><dd>{fmtAge(pending.ready_age_s as number)}</dd>
						<dt>eject_age</dt><dd>{fmtAge(pending.eject_age_s as number)}</dd>
						<dt>commit_due_in</dt><dd>{fmtAge(pending.commit_due_in_s as number)}</dd>
					</dl>
				{:else}
					<p class="muted">no pending piece</p>
				{/if}
			</div>

			<!-- C4 dossiers -->
			<div class="card wide">
				<h2>C4 dossiers ({rtField(inspect.runtime_inspect?.c4, 'dossier_count') ?? 0})</h2>
				{#if dossierRows(inspect.runtime_inspect?.c4).length === 0}
					<p class="muted">empty</p>
				{:else}
					<table>
						<thead>
							<tr>
								<th>uuid</th>
								<th>gid</th>
								<th>angle</th>
								<th>exit Δ</th>
								<th>classify Δ</th>
								<th>part</th>
								<th>state</th>
								<th>seen</th>
								<th>extras</th>
							</tr>
						</thead>
						<tbody>
							{#each dossierRows(inspect.runtime_inspect?.c4) as d}
								<tr>
									<td class="mono">{d.piece_uuid?.slice(0, 8)}</td>
									<td>{d.global_id ?? '-'}</td>
									<td>{fmt(d.angle_deg)}</td>
									<td>{fmt(d.exit_delta_deg)}</td>
									<td>{fmt(d.classify_delta_deg)}</td>
									<td class="mono">{d.result_part_id ?? '-'}</td>
									<td class="state-cell">
										{#if d.handoff_requested}<span class="badge">HOREQ</span>{/if}
										{#if d.distributor_ready}<span class="badge ready">READY</span>{/if}
										{#if d.eject_enqueued}<span class="badge">EJ-Q</span>{/if}
										{#if d.eject_committed}<span class="badge ok">EJ-C</span>{/if}
										{#if d.classify_future_pending}<span class="badge">CLF-WAIT</span>{/if}
										{#if d.reject_reason}<span class="badge err">{d.reject_reason}</span>{/if}
									</td>
									<td>{fmtAge(d.last_seen_age_s)}</td>
									<td class="mono">
										{#if d.extras && Object.keys(d.extras).length > 0}
											{JSON.stringify(d.extras)}
										{/if}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				{/if}
			</div>

			<!-- C2/C3 claims -->
			<div class="card">
				<h2>C2 pending claims</h2>
				{#if claimRows(inspect.runtime_inspect?.c2).length === 0}
					<p class="muted">none</p>
				{:else}
					<table>
						<thead><tr><th>gid</th><th>deadline_in</th><th>retries</th></tr></thead>
						<tbody>
							{#each claimRows(inspect.runtime_inspect?.c2) as c}
								<tr><td>{c.global_id}</td><td>{fmtAge(c.deadline_age_s)}</td><td>{c.retry_count}</td></tr>
							{/each}
						</tbody>
					</table>
				{/if}
				<dl class="kv">
					<dt>piece_count</dt><dd>{rtField(inspect.runtime_inspect?.c2, 'piece_count') ?? '-'}</dd>
					<dt>visible_tracks</dt><dd>{rtField(inspect.runtime_inspect?.c2, 'visible_track_count') ?? '-'}</dd>
					<dt>next_pulse_in</dt><dd>{fmtAge(rtField(inspect.runtime_inspect?.c2, 'next_pulse_in_s') as number)}</dd>
					<dt>next_handoff_in</dt><dd>{fmtAge(rtField(inspect.runtime_inspect?.c2, 'next_exit_handoff_in_s') as number)}</dd>
					<dt>blocked</dt><dd>{rtField(inspect.runtime_debug?.c2, 'blocked_reason') ?? '-'}</dd>
				</dl>
			</div>

			<div class="card">
				<h2>C3 pending claims</h2>
				{#if claimRows(inspect.runtime_inspect?.c3).length === 0}
					<p class="muted">none</p>
				{:else}
					<table>
						<thead><tr><th>gid</th><th>deadline_in</th><th>retries</th></tr></thead>
						<tbody>
							{#each claimRows(inspect.runtime_inspect?.c3) as c}
								<tr><td>{c.global_id}</td><td>{fmtAge(c.deadline_age_s)}</td><td>{c.retry_count}</td></tr>
							{/each}
						</tbody>
					</table>
				{/if}
				<dl class="kv">
					<dt>piece_count</dt><dd>{rtField(inspect.runtime_inspect?.c3, 'piece_count') ?? '-'}</dd>
					<dt>visible_tracks</dt><dd>{rtField(inspect.runtime_inspect?.c3, 'visible_track_count') ?? '-'}</dd>
					<dt>next_pulse_in</dt><dd>{fmtAge(rtField(inspect.runtime_inspect?.c3, 'next_pulse_in_s') as number)}</dd>
					<dt>next_handoff_in</dt><dd>{fmtAge(rtField(inspect.runtime_inspect?.c3, 'next_exit_handoff_in_s') as number)}</dd>
					<dt>holdover_active</dt><dd>{rtField(inspect.runtime_inspect?.c3, 'holdover_active') ? 'yes' : 'no'}</dd>
					<dt>blocked</dt><dd>{rtField(inspect.runtime_debug?.c3, 'blocked_reason') ?? '-'}</dd>
				</dl>
			</div>

			<!-- Health -->
			<div class="card">
				<h2>Health</h2>
				<table>
					<thead><tr><th>runtime</th><th>state</th><th>blocked</th><th>tick (ms)</th></tr></thead>
					<tbody>
						{#each Object.entries(inspect.runtime_health ?? {}) as [name, h]}
							<tr>
								<td>{name}</td>
								<td>{h.state}</td>
								<td>{h.blocked_reason ?? '-'}</td>
								<td>{fmt(h.last_tick_ms, 3)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</section>
	{:else}
		<p class="muted">no inspect data yet — is the runtime started?</p>
	{/if}
</main>

<style>
	.page {
		padding: 16px;
		font-family: ui-sans-serif, system-ui, sans-serif;
		color: #e6e6e6;
		background: #0e0f12;
		min-height: 100vh;
	}
	.page-header h1 {
		margin: 0 0 4px;
		font-size: 22px;
	}
	.muted {
		color: #888;
	}
	.controls {
		margin: 12px 0 16px;
	}
	.control-row {
		display: flex;
		gap: 8px;
		flex-wrap: wrap;
		align-items: center;
	}
	.control-row input[type='number'] {
		width: 64px;
		background: #1a1c20;
		color: #e6e6e6;
		border: 1px solid #303338;
		padding: 4px 8px;
	}
	button {
		background: #1a1c20;
		color: #e6e6e6;
		border: 1px solid #303338;
		padding: 4px 12px;
		cursor: pointer;
	}
	button:hover:not(:disabled) {
		background: #25272d;
	}
	button:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}
	button.primary {
		background: #2b3a55;
		border-color: #3c5680;
	}
	.separator {
		color: #555;
	}
	.poll-toggle {
		margin-left: auto;
		font-size: 13px;
		color: #aaa;
	}
	.control-status {
		margin-top: 8px;
		display: flex;
		gap: 16px;
		font-size: 14px;
		flex-wrap: wrap;
	}
	.state-paused {
		color: #ffa657;
	}
	.state-running {
		color: #3fb950;
	}
	.err {
		color: #f85149;
	}
	.grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 12px;
	}
	.card {
		background: #16181d;
		border: 1px solid #2a2d33;
		padding: 12px;
	}
	.card.wide {
		grid-column: span 2;
	}
	.card h2 {
		margin: 0 0 8px;
		font-size: 15px;
		font-weight: 600;
	}
	.card h3 {
		margin: 8px 0 4px;
		font-size: 13px;
		color: #aaa;
		font-weight: 600;
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 12px;
	}
	th,
	td {
		text-align: left;
		padding: 4px 6px;
		border-bottom: 1px solid #25272c;
	}
	th {
		color: #aaa;
		font-weight: 500;
	}
	.mono {
		font-family: ui-monospace, SFMono-Regular, monospace;
	}
	dl.kv {
		display: grid;
		grid-template-columns: 140px 1fr;
		row-gap: 2px;
		column-gap: 8px;
		font-size: 12px;
		margin: 6px 0 0;
	}
	dl.kv dt {
		color: #888;
	}
	dl.kv dd {
		margin: 0;
		font-family: ui-monospace, SFMono-Regular, monospace;
	}
	.badge {
		display: inline-block;
		font-size: 10px;
		padding: 1px 6px;
		background: #2c3038;
		color: #ccc;
		margin-right: 3px;
		font-family: ui-monospace, SFMono-Regular, monospace;
	}
	.badge.ready {
		background: #3a4a30;
		color: #b6e3a1;
	}
	.badge.ok {
		background: #2d4a55;
		color: #a3e2f5;
	}
	.badge.err {
		background: #4a2d2d;
		color: #f5a3a3;
	}
	.badge.expired {
		background: #4a2d2d;
		color: #f5a3a3;
	}
	.state-cell {
		min-width: 220px;
	}
</style>
