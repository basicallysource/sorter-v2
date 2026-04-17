<script lang="ts">
	import AppHeader from '$lib/components/AppHeader.svelte';
	import SectionCard from '$lib/components/settings/SectionCard.svelte';
	import StatusBanner from '$lib/components/StatusBanner.svelte';
	import { Alert, Button, Input, Tooltip } from '$lib/components/primitives';
	import { Check, CheckCircle2, ChevronRight, HelpCircle, Loader2, RefreshCcw } from 'lucide-svelte';

	let primitiveInputText = $state('');
	let primitiveInputNumber = $state(0);
	let primitiveInputPassword = $state('');

	type Swatch = { name: string; value: string; usage: string };

	const brandColors: Swatch[] = [
		{
			name: 'Primary (live)',
			value: 'var(--color-primary)',
			usage: 'Primary actions, focus rings — live theme color, picked by the user in setup'
		},
		{ name: 'LEGO Green', value: '#00852B', usage: 'Success, completion, confirm' },
		{ name: 'LEGO Yellow', value: '#F2A900', usage: 'Warnings, calibration ok' },
		{ name: 'LEGO Red', value: '#D01012', usage: 'Errors, destructive actions' }
	];

	const darkContrastColors: Swatch[] = [
		{
			name: 'Primary dark (live)',
			value: 'var(--color-primary-dark)',
			usage: 'Notification labels on tinted primary background — live theme color'
		},
		{
			name: 'Green (dark)',
			value: '#003D14',
			usage: 'Notification labels on tinted green background'
		},
		{
			name: 'Yellow (dark)',
			value: '#4A3300',
			usage: 'Notification labels on tinted yellow background'
		},
		{
			name: 'Red (dark)',
			value: '#5C0708',
			usage: 'Notification labels on tinted red background'
		}
	];

	const neutralColors: Swatch[] = [
		{ name: 'bg', value: 'var(--color-bg)', usage: 'Page background' },
		{ name: 'surface', value: 'var(--color-surface)', usage: 'Card / panel background' },
		{
			name: 'setup-card-header',
			value: '#ECECEA',
			usage: 'Neutral dashboard / settings card header, distinct from the warm page background'
		},
		{ name: 'border', value: 'var(--color-border)', usage: 'Divider lines, card outlines' },
		{ name: 'text', value: 'var(--color-text)', usage: 'Primary copy' },
		{ name: 'text-muted', value: 'var(--color-text-muted)', usage: 'Secondary copy, labels' }
	];

	const codeStatLabel = `<div class="text-xs font-semibold tracking-wider
            text-text-muted uppercase">
  Match avg
</div>
<div class="text-sm font-semibold tabular-nums text-text">
  98.4
</div>`;

	const codePanel = `<div class="setup-panel px-4 py-3">
  ... content ...
</div>`;

	const codeDashboardCard = `<div class="setup-card-shell border">
	  <div class="setup-card-header px-3 py-2 text-sm font-medium text-text">
    Classification
  </div>
  <div class="setup-card-body p-3 text-sm text-text">
    Camera feed, stats, or other live dashboard content.
  </div>
</div>`;

	const codeButtonPrimary = `<button class="setup-button-primary inline-flex
              items-center gap-2 px-4 py-2 text-sm
              font-medium transition-colors">
  Continue
  <ChevronRight size={14} />
</button>`;

	const codeButtonSecondary = `<button class="setup-button-secondary inline-flex
              items-center gap-2 px-3 py-2 text-sm
              text-text transition-colors">
  <RefreshCcw size={14} />
  Rescan
</button>`;

	const codeBrandConfirm = `<button class="inline-flex items-center gap-2
              border border-[#00852B] bg-[#00852B]
              px-4 py-2 text-sm font-medium text-white
              transition-colors hover:bg-[#00852B]/90
              disabled:cursor-not-allowed disabled:opacity-60">
  <CheckCircle2 size={14} />
  Connect to Hive
</button>`;

	const codeInput = `<input
  type="text"
  class="setup-control w-full px-3 py-2 text-sm text-text"
  placeholder="e.g. Sorting Bench A"
/>`;

	const codeHero = `<div class="setup-panel relative overflow-hidden
            border-[#00852B]/40
            bg-gradient-to-br from-[#EAF7EE] via-[#F3FBF5] to-white
            px-8 py-10 text-center">
  <div class="mx-auto flex max-w-xl flex-col items-center gap-4">
    <div class="flex h-20 w-20 items-center justify-center
                rounded-full bg-[#00852B] text-white
                shadow-[0_8px_24px_-6px_rgba(0,133,43,0.55)]">
      <Check size={44} strokeWidth={3} />
    </div>
    <div class="text-2xl font-bold text-text">Setup Complete!</div>
    <div class="text-sm text-text-muted">...</div>
  </div>
</div>`;
</script>

<svelte:head>
	<title>Style Guide · Sorter</title>
</svelte:head>

<div class="min-h-screen bg-bg text-text">
	<AppHeader />

	<main class="mx-auto flex max-w-5xl flex-col gap-6 px-4 py-6 sm:px-6">
		<header class="flex flex-col gap-2">
			<div class="text-xs font-semibold tracking-wider text-text-muted uppercase">
				Internal reference
			</div>
			<h1 class="text-2xl font-bold text-text">Sorter UI Style Guide</h1>
			<p class="max-w-2xl text-sm text-text-muted">
				The shared visual language used by the local sorter monitoring tool. Use this page as
				the source of truth when adding new screens or components — every pattern below is in
				active use somewhere in the app.
			</p>
		</header>

		<SectionCard
			title="Design principles"
			description="Five rules that shape every screen in this app."
		>
			<ol class="flex flex-col gap-3 text-sm text-text">
				<li class="flex gap-3">
					<span class="text-xs font-semibold tracking-wider text-text-muted">01</span>
					<div>
						<div class="font-semibold">No rounded corners.</div>
						<div class="text-text-muted">
							Sharp 0px edges everywhere. The local monitoring tool is intentionally
							industrial — rounded corners belong to consumer surfaces.
						</div>
					</div>
				</li>
				<li class="flex gap-3">
					<span class="text-xs font-semibold tracking-wider text-text-muted">02</span>
					<div>
						<div class="font-semibold">No colored left-accent borders.</div>
						<div class="text-text-muted">
							Notifications use a flat 1px border at 40% opacity on
							<em>all four sides</em> — never <code>border-l-2</code> stripes.
						</div>
					</div>
				</li>
				<li class="flex gap-3">
					<span class="text-xs font-semibold tracking-wider text-text-muted">03</span>
					<div>
						<div class="font-semibold">One unified notification template.</div>
						<div class="text-text-muted">
							Info / success / warning / error all share the same shape and rhythm — only
							the brand color tone changes.
						</div>
					</div>
				</li>
				<li class="flex gap-3">
					<span class="text-xs font-semibold tracking-wider text-text-muted">04</span>
					<div>
						<div class="font-semibold">11px uppercase labels.</div>
						<div class="text-text-muted">
							Section labels and micro-headings use <code>text-xs</code>,
							<code>uppercase</code>, <code>tracking-wider</code>,
							<code>font-semibold</code>. Body copy stays at 12px.
						</div>
					</div>
				</li>
				<li class="flex gap-3">
					<span class="text-xs font-semibold tracking-wider text-text-muted">05</span>
					<div>
						<div class="font-semibold">Darker tones on tinted backgrounds.</div>
						<div class="text-text-muted">
							The standard LEGO palette is too light against the 6% tinted notification
							backgrounds. Use the darker contrast tones below for any text on a tinted
							surface.
						</div>
					</div>
				</li>
			</ol>
		</SectionCard>

		<SectionCard
			title="Brand colors"
			description="The LEGO palette is used for accents, status, and primary actions."
		>
			<div class="flex flex-col gap-4">
				<div>
					<div class="mb-2 text-xs font-semibold tracking-wider text-text-muted uppercase">
						Primary palette
					</div>
					<div class="grid gap-2 sm:grid-cols-2">
						{#each brandColors as swatch}
							<div class="setup-panel flex items-center gap-3 px-3 py-2">
								<div
									class="h-9 w-9 border border-border"
									style={`background:${swatch.value}`}
								></div>
								<div class="min-w-0 flex-1">
									<div class="flex items-center justify-between gap-2 text-xs">
										<span class="font-semibold text-text">{swatch.name}</span>
										<span class="font-mono text-text-muted">{swatch.value}</span>
									</div>
									<div class="text-xs text-text-muted">{swatch.usage}</div>
								</div>
							</div>
						{/each}
					</div>
				</div>

				<div>
					<div class="mb-2 text-xs font-semibold tracking-wider text-text-muted uppercase">
						Dark contrast tones
					</div>
					<div class="grid gap-2 sm:grid-cols-2">
						{#each darkContrastColors as swatch}
							<div class="setup-panel flex items-center gap-3 px-3 py-2">
								<div
									class="h-9 w-9 border border-border"
									style={`background:${swatch.value}`}
								></div>
								<div class="min-w-0 flex-1">
									<div class="flex items-center justify-between gap-2 text-xs">
										<span class="font-semibold text-text">{swatch.name}</span>
										<span class="font-mono text-text-muted">{swatch.value}</span>
									</div>
									<div class="text-xs text-text-muted">{swatch.usage}</div>
								</div>
							</div>
						{/each}
					</div>
				</div>

				<div>
					<div class="mb-2 text-xs font-semibold tracking-wider text-text-muted uppercase">
						Neutral tokens
					</div>
					<div class="grid gap-2 sm:grid-cols-2">
						{#each neutralColors as swatch}
							<div class="setup-panel flex items-center gap-3 px-3 py-2">
								<div
									class="h-9 w-9 border border-border"
									style={`background:${swatch.value}`}
								></div>
								<div class="min-w-0 flex-1">
									<div class="flex items-center justify-between gap-2 text-xs">
										<span class="font-semibold text-text">{swatch.name}</span>
										<span class="font-mono text-text-muted">{swatch.value}</span>
									</div>
									<div class="text-xs text-text-muted">{swatch.usage}</div>
								</div>
							</div>
						{/each}
					</div>
				</div>
			</div>
		</SectionCard>

		<SectionCard title="Typography" description="Hierarchy used across the app.">
			<div class="flex flex-col gap-3">
				<div class="setup-panel px-4 py-3">
					<div class="text-2xl font-bold text-text">Setup Complete!</div>
					<div class="mt-1 text-sm text-text-muted font-mono">
						text-2xl · font-bold · text-text — page hero headline
					</div>
				</div>
				<div class="setup-panel px-4 py-3">
					<div class="text-base font-semibold text-text">Section Card title</div>
					<div class="mt-1 text-sm text-text-muted font-mono">
						text-base · font-semibold · text-text — card headers
					</div>
				</div>
				<div class="setup-panel px-4 py-3">
					<div class="text-sm text-text-muted">
						Description copy explaining what a section does and why the operator might
						care.
					</div>
					<div class="mt-1 text-sm text-text-muted font-mono">
						text-sm · text-text-muted — section descriptions, body copy
					</div>
				</div>
				<div class="setup-panel px-4 py-3">
					<div class="text-sm leading-relaxed text-text">
						Notification body and inline help text. Uses the muted leading-relaxed reading
						rhythm.
					</div>
					<div class="mt-1 text-sm text-text-muted font-mono">
						text-xs · leading-relaxed · text-text — notification bodies
					</div>
				</div>
				<div class="setup-panel px-4 py-3">
					<div class="text-xs font-semibold tracking-wider text-text-muted uppercase">
						Section label
					</div>
					<div class="mt-1 text-sm text-text-muted font-mono">
						text-xs · font-semibold · tracking-wider · uppercase — labels above values
					</div>
				</div>
				<div class="setup-panel px-4 py-3">
					<div class="font-mono text-sm text-text">192.168.1.42:8000</div>
					<div class="mt-1 text-sm text-text-muted font-mono">
						font-mono · text-sm — IDs, URLs, hex values, port numbers
					</div>
				</div>
			</div>
		</SectionCard>

		<SectionCard
			title="Notifications"
			description="The unified info / success / warning / error template. Always use the Alert primitive — no hand-rolled boxes."
		>
			<div class="flex flex-col gap-4">
				<Alert variant="info">
					<div class="text-xs font-semibold tracking-wider text-primary-dark uppercase dark:text-sky-200">
						Calibration hint
					</div>
					<div class="mt-1 text-sm leading-relaxed text-text">
						Hold a flat reference card under the camera and click Capture.
					</div>
				</Alert>

				<Alert variant="success">
					<div class="text-xs font-semibold tracking-wider text-success-dark uppercase dark:text-emerald-200">
						Calibration is usable
					</div>
					<div class="mt-1 text-sm leading-relaxed text-text">
						White balance and exposure are within tolerance. You can move on.
					</div>
				</Alert>

				<Alert variant="warning">
					<div class="text-xs font-semibold tracking-wider text-warning-dark uppercase dark:text-amber-200">
						Calibration weak
					</div>
					<div class="mt-1 text-sm leading-relaxed text-text">
						Reference patches drifted by 8.3 ΔE. Re-shoot the calibration card.
					</div>
				</Alert>

				<Alert variant="danger">
					<div class="text-xs font-semibold tracking-wider text-danger-dark uppercase dark:text-rose-200">
						Connection failed
					</div>
					<div class="mt-1 text-sm leading-relaxed text-text">
						Could not reach the Hive server. Check your credentials and try again.
					</div>
				</Alert>

				<pre
					class="setup-panel overflow-x-auto px-3 py-2 text-xs font-mono leading-relaxed text-text">{`<Alert variant="info">…</Alert>
<Alert variant="success">…</Alert>
<Alert variant="warning">…</Alert>
<Alert variant="danger">…</Alert>`}</pre>
			</div>
		</SectionCard>

		<SectionCard
			title="StatusBanner component"
			description="One-line transient feedback for save / move / refresh actions."
		>
			<div class="flex flex-col gap-3">
				<StatusBanner message="Moved to 8.25°" variant="success" />
				<StatusBanner message="Saved with 2 fields skipped." variant="warning" />
				<StatusBanner message="Failed to load layout — backend offline." variant="error" />
				<pre
					class="setup-panel overflow-x-auto px-3 py-2 text-xs font-mono leading-relaxed text-text">{`<StatusBanner message="Moved to 8.25°" variant="success" />
<StatusBanner message="Saved with 2 fields skipped." variant="warning" />
<StatusBanner message="Failed to load layout" variant="error" />`}</pre>
			</div>
		</SectionCard>

		<SectionCard
			title="Stat cells"
			description="Tiny labeled values for inline metrics (used in PictureSettingsSidebar)."
		>
			<div class="flex flex-col gap-3">
				<div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
					<div class="setup-panel px-3 py-2">
						<div
							class="text-xs font-semibold tracking-wider text-text-muted uppercase"
						>
							Match avg
						</div>
						<div class="text-sm font-semibold tabular-nums text-text">98.4</div>
					</div>
					<div class="setup-panel px-3 py-2">
						<div
							class="text-xs font-semibold tracking-wider text-text-muted uppercase"
						>
							Ref error
						</div>
						<div class="text-sm font-semibold tabular-nums text-text">1.2</div>
					</div>
					<div class="setup-panel px-3 py-2">
						<div
							class="text-xs font-semibold tracking-wider text-text-muted uppercase"
						>
							White / black
						</div>
						<div class="text-sm font-semibold tabular-nums text-text">242 / 18</div>
					</div>
					<div class="setup-panel px-3 py-2">
						<div
							class="text-xs font-semibold tracking-wider text-text-muted uppercase"
						>
							WB cast
						</div>
						<div class="text-sm font-semibold tabular-nums text-text">+0.04</div>
					</div>
				</div>
				<pre
					class="setup-panel overflow-x-auto px-3 py-2 text-xs font-mono leading-relaxed text-text">{codeStatLabel}</pre>
			</div>
		</SectionCard>

		<SectionCard
			title="Panels & cards"
			description="The setup-panel utility is the base surface used everywhere outside the navigation chrome."
		>
			<div class="flex flex-col gap-3">
				<div class="setup-panel px-4 py-3 text-sm text-text">
					This is a <code>.setup-panel</code> — a 1px bordered surface with a subtle inner
					highlight. Use it for grouped content, stat cells, and inline forms.
				</div>
				<pre
					class="setup-panel overflow-x-auto px-3 py-2 text-xs font-mono leading-relaxed text-text">{codePanel}</pre>

				<div class="setup-card-shell border">
					<div class="setup-card-header px-3 py-2 text-sm font-medium text-text">
						Dashboard card header
					</div>
					<div class="setup-card-body px-4 py-3 text-sm text-text">
						Use <code>.setup-card-shell</code>, <code>.setup-card-header</code>, and
						<code>.setup-card-body</code> for live dashboard cards with headers. The header
						must stay neutral gray, not warm beige and not blue.
					</div>
				</div>
				<pre
					class="setup-panel overflow-x-auto px-3 py-2 text-xs font-mono leading-relaxed text-text">{codeDashboardCard}</pre>
			</div>
		</SectionCard>

		<SectionCard
			title="Hero panel"
			description="Used for the Setup Complete screen and other moments worth celebrating."
		>
			<div class="flex flex-col gap-3">
				<div
					class="setup-panel relative overflow-hidden border-[#00852B]/40 bg-gradient-to-br from-[#EAF7EE] via-[#F3FBF5] to-white px-8 py-10 text-center dark:from-[#0F2B18] dark:via-[#0B1F12] dark:to-bg"
				>
					<div class="mx-auto flex max-w-xl flex-col items-center gap-4">
						<div
							class="flex h-20 w-20 items-center justify-center rounded-full bg-[#00852B] text-white shadow-[0_8px_24px_-6px_rgba(0,133,43,0.55)]"
						>
							<Check size={44} strokeWidth={3} />
						</div>
						<div class="flex flex-col gap-2">
							<div class="text-2xl font-bold text-text">Setup Complete!</div>
							<div class="text-sm text-text-muted">
								Your sorter is configured and ready to go. Open the dashboard, home the
								machine if it's still in standby, and give it a first run.
							</div>
						</div>
					</div>
				</div>
				<pre
					class="setup-panel overflow-x-auto px-3 py-2 text-xs font-mono leading-relaxed text-text">{codeHero}</pre>
				<div class="text-xs text-text-muted">
					The circular check is the <em>only</em> place where rounded corners are allowed.
					Treat it as a deliberate exception, not a precedent.
				</div>
			</div>
		</SectionCard>

		<SectionCard title="Buttons" description="Primary, secondary, and brand confirm.">
			<div class="flex flex-col gap-4">
				<div class="flex flex-wrap items-center gap-2">
					<button
						type="button"
						class="setup-button-primary inline-flex items-center gap-2 px-4 py-2 text-sm font-medium transition-colors"
					>
						Continue
						<ChevronRight size={14} />
					</button>
					<span class="text-xs text-text-muted font-mono">.setup-button-primary</span>
				</div>
				<pre
					class="setup-panel overflow-x-auto px-3 py-2 text-xs font-mono leading-relaxed text-text">{codeButtonPrimary}</pre>

				<div class="flex flex-wrap items-center gap-2">
					<button
						type="button"
						class="setup-button-secondary inline-flex items-center gap-2 px-3 py-2 text-sm text-text transition-colors"
					>
						<RefreshCcw size={14} />
						Rescan
					</button>
					<span class="text-xs text-text-muted font-mono">.setup-button-secondary</span>
				</div>
				<pre
					class="setup-panel overflow-x-auto px-3 py-2 text-xs font-mono leading-relaxed text-text">{codeButtonSecondary}</pre>

				<div class="flex flex-wrap items-center gap-2">
					<button
						type="button"
						class="inline-flex items-center gap-2 border border-[#00852B] bg-[#00852B] px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-[#00852B]/90 disabled:cursor-not-allowed disabled:opacity-60"
					>
						<CheckCircle2 size={14} />
						Connect to Hive
					</button>
					<span class="text-xs text-text-muted font-mono">brand confirm (inline)</span>
				</div>
				<pre
					class="setup-panel overflow-x-auto px-3 py-2 text-xs font-mono leading-relaxed text-text">{codeBrandConfirm}</pre>
			</div>
		</SectionCard>

		<SectionCard
			title="Form controls"
			description="The setup-control class gives every input the same focus ring and surface."
		>
			<div class="flex flex-col gap-3">
				<input
					type="text"
					class="setup-control w-full px-3 py-2 text-sm text-text"
					placeholder="e.g. Sorting Bench A"
				/>
				<pre
					class="setup-panel overflow-x-auto px-3 py-2 text-xs font-mono leading-relaxed text-text">{codeInput}</pre>
			</div>
		</SectionCard>

		<SectionCard
			title="Loading states"
			description="Spinner row used when fetching async data inside a step or panel."
		>
			<div class="flex flex-col gap-3">
				<div
					class="setup-panel flex items-center gap-2 px-4 py-3 text-sm text-text-muted"
				>
					<Loader2 size={14} class="animate-spin" />
					Checking current Hive configuration…
				</div>
				<pre
					class="setup-panel overflow-x-auto px-3 py-2 text-xs font-mono leading-relaxed text-text">{`<div class="setup-panel flex items-center gap-2
            px-4 py-3 text-sm text-text-muted">
  <Loader2 size={14} class="animate-spin" />
  Checking current Hive configuration…
</div>`}</pre>
			</div>
		</SectionCard>

		<SectionCard
			title="Button primitive"
			description="Variants primary / secondary / danger / ghost in sizes sm and md. Sharp edges, callback-prop based. Loading state renders the shared Spinner."
		>
			<div class="flex flex-col gap-6">
				<div class="flex flex-col gap-3">
					<div class="text-xs font-semibold uppercase tracking-wider text-text-muted">Variants (md)</div>
					<div class="flex flex-wrap items-center gap-2">
						<Button variant="primary">Primary</Button>
						<Button variant="secondary">Secondary</Button>
						<Button variant="danger">Danger</Button>
						<Button variant="ghost">Ghost</Button>
					</div>
				</div>
				<div class="flex flex-col gap-3">
					<div class="text-xs font-semibold uppercase tracking-wider text-text-muted">Size sm</div>
					<div class="flex flex-wrap items-center gap-2">
						<Button variant="primary" size="sm">Primary</Button>
						<Button variant="secondary" size="sm">Secondary</Button>
						<Button variant="danger" size="sm">Danger</Button>
						<Button variant="ghost" size="sm">Ghost</Button>
					</div>
				</div>
				<div class="flex flex-col gap-3">
					<div class="text-xs font-semibold uppercase tracking-wider text-text-muted">Disabled / loading</div>
					<div class="flex flex-wrap items-center gap-2">
						<Button variant="primary" disabled>Disabled</Button>
						<Button variant="primary" loading>Saving…</Button>
						<Button variant="secondary" loading>Loading</Button>
						<Button variant="danger" loading>Deleting</Button>
					</div>
				</div>
				<pre
					class="setup-panel overflow-x-auto px-3 py-2 text-xs font-mono leading-relaxed text-text">{`import { Button } from '$lib/components/primitives';

<Button variant="primary" onclick={save}>Save</Button>
<Button variant="danger" loading={pending}>Delete</Button>`}</pre>
			</div>
		</SectionCard>

		<SectionCard
			title="Input primitive"
			description="Wraps the .setup-control class so inputs share the focus ring and surface. Supports text, number, password, email, search."
		>
			<div class="flex flex-col gap-3">
				<Input placeholder="Sorting Bench A" bind:value={primitiveInputText} />
				<Input type="number" bind:value={primitiveInputNumber} />
				<Input type="password" placeholder="API token" bind:value={primitiveInputPassword} />
				<pre
					class="setup-panel overflow-x-auto px-3 py-2 text-xs font-mono leading-relaxed text-text">{`import { Input } from '$lib/components/primitives';

<Input placeholder="Sorting Bench A" bind:value={name} />
<Input type="number" bind:value={count} />
<Input type="password" bind:value={token} />`}</pre>
			</div>
		</SectionCard>

		<SectionCard
			title="Alert primitive"
			description="Replaces inline notification boxes. Four variants mapped to the danger / success / warning / info tokens. No left-border accent."
		>
			<div class="flex flex-col gap-3">
				<Alert variant="success">Sorting profile saved. Ready to run.</Alert>
				<Alert variant="warning">Servo calibration is older than 30 days.</Alert>
				<Alert variant="danger">Could not reach machine — check the network cable.</Alert>
				<Alert variant="info">Homing in progress. This usually takes ~12 seconds.</Alert>
				<pre
					class="setup-panel overflow-x-auto px-3 py-2 text-xs font-mono leading-relaxed text-text">{`import { Alert } from '$lib/components/primitives';

<Alert variant="success">Saved.</Alert>
<Alert variant="danger">Could not reach machine.</Alert>`}</pre>
			</div>
		</SectionCard>

		<SectionCard
			title="Tooltip primitive"
			description="Simple hover / focus tooltip, no portal. Pass the label via the text prop and the trigger as default children."
		>
			<div class="flex flex-col gap-3">
				<div class="flex items-center gap-4">
					<Tooltip text="Recalibrate the bed height">
						<Button variant="secondary" size="sm">
							<RefreshCcw size={14} />
							Recalibrate
						</Button>
					</Tooltip>
					<Tooltip text="Opens the full hardware homing flow">
						<span class="inline-flex items-center gap-1 text-sm text-text-muted">
							<HelpCircle size={14} />
							What is homing?
						</span>
					</Tooltip>
				</div>
				<pre
					class="setup-panel overflow-x-auto px-3 py-2 text-xs font-mono leading-relaxed text-text">{`import { Tooltip } from '$lib/components/primitives';

<Tooltip text="Recalibrate the bed height">
  <Button variant="secondary" size="sm">Recalibrate</Button>
</Tooltip>`}</pre>
			</div>
		</SectionCard>
	</main>
</div>
