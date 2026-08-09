<script lang="ts">
	import { Button, Alert, Tooltip } from '$lib/components/primitives';
	import Spinner from '$lib/components/Spinner.svelte';
</script>

<svelte:head>
	<title>Style Guide - Hive</title>
</svelte:head>

<div class="space-y-16 pb-20">
	<!-- Header -->
	<div>
		<h1 class="text-3xl font-bold tracking-tight">Style Guide</h1>
		<p class="mt-1 text-sm text-text-muted">Hive Design System — "Precision Play"</p>
	</div>

	<!-- ─── Color Palette ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Color Palette</h2>
		<div class="grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-6">
			<div>
				<div class="h-20 w-full border border-border bg-[#D01012]"></div>
				<p class="mt-2 text-xs font-medium">LEGO Red</p>
				<p class="font-mono text-xs text-text-muted">#D01012</p>
				<p class="text-xs text-text-muted">Primary / CTA</p>
			</div>
			<div>
				<div class="h-20 w-full border border-border bg-[#0055BF]"></div>
				<p class="mt-2 text-xs font-medium">LEGO Blue</p>
				<p class="font-mono text-xs text-text-muted">#0055BF</p>
				<p class="text-xs text-text-muted">Info / Selection</p>
			</div>
			<div>
				<div class="h-20 w-full border border-border bg-[#00852B]"></div>
				<p class="mt-2 text-xs font-medium">LEGO Green</p>
				<p class="font-mono text-xs text-text-muted">#00852B</p>
				<p class="text-xs text-text-muted">Success / Connected</p>
			</div>
			<div>
				<div class="h-20 w-full border border-border bg-[#FFD500]"></div>
				<p class="mt-2 text-xs font-medium">LEGO Yellow</p>
				<p class="font-mono text-xs text-text-muted">#FFD500</p>
				<p class="text-xs text-text-muted">Warning / Highlight</p>
			</div>
			<div>
				<div class="h-20 w-full border border-border bg-[#9B1D20]"></div>
				<p class="mt-2 text-xs font-medium">Dark Red</p>
				<p class="font-mono text-xs text-text-muted">#9B1D20</p>
				<p class="text-xs text-text-muted">Danger / Destructive</p>
			</div>
			<div>
				<div class="h-20 w-full border border-border bg-[#B00E10]"></div>
				<p class="mt-2 text-xs font-medium">Red Hover</p>
				<p class="font-mono text-xs text-text-muted">#B00E10</p>
				<p class="text-xs text-text-muted">Primary hover</p>
			</div>
		</div>
		<div class="grid grid-cols-2 gap-4 sm:grid-cols-5">
			<div>
				<div class="h-16 w-full border border-border bg-[#F7F6F3]"></div>
				<p class="mt-2 text-xs font-medium">Background</p>
				<p class="font-mono text-xs text-text-muted">#F7F6F3</p>
			</div>
			<div>
				<div class="h-16 w-full border border-border bg-[#FFFFFF]"></div>
				<p class="mt-2 text-xs font-medium">Surface</p>
				<p class="font-mono text-xs text-text-muted">#FFFFFF</p>
			</div>
			<div>
				<div class="h-16 w-full border border-border bg-[#E2E0DB]"></div>
				<p class="mt-2 text-xs font-medium">Border</p>
				<p class="font-mono text-xs text-text-muted">#E2E0DB</p>
			</div>
			<div>
				<div class="h-16 w-full border border-border bg-[#1A1A1A]"></div>
				<p class="mt-2 text-xs font-medium text-text">Text</p>
				<p class="font-mono text-xs text-text-muted">#1A1A1A</p>
			</div>
			<div>
				<div class="h-16 w-full border border-border bg-[#7A7770]"></div>
				<p class="mt-2 text-xs font-medium">Text Muted</p>
				<p class="font-mono text-xs text-text-muted">#7A7770</p>
			</div>
		</div>
	</section>

	<!-- ─── Typography ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Typography</h2>
		<div class="space-y-6 border border-border bg-surface p-6">
			<div>
				<p class="text-xs uppercase tracking-wider text-text-muted">IBM Plex Sans</p>
				<p class="mt-2 text-3xl font-bold tracking-tight">Page Title — 3xl Bold</p>
				<p class="mt-2 text-2xl font-bold">Section Header — 2xl Bold</p>
				<p class="mt-2 text-lg font-semibold">Subsection — lg Semibold</p>
				<p class="mt-2 text-sm font-medium">Label / Button — sm Medium</p>
				<p class="mt-2 text-sm">Body text — sm Regular. The quick brown fox jumps over the lazy dog.</p>
				<p class="mt-2 text-xs text-text-muted">Caption / Timestamp — xs Muted</p>
			</div>
			<div class="border-t border-border pt-4">
				<p class="text-xs uppercase tracking-wider text-text-muted">IBM Plex Mono</p>
				<p class="mt-2 font-mono text-2xl font-bold">1,636</p>
				<p class="mt-1 font-mono text-sm">part_num: 3023 | color_id: 15 | qty: 4</p>
				<p class="mt-1 font-mono text-xs text-text-muted">75460-1 · 2026 · 558 parts</p>
			</div>
		</div>
	</section>

	<!-- ─── Buttons ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Buttons</h2>
		<div class="border border-border bg-surface p-6">
			<div class="flex flex-wrap items-center gap-3">
				<button class="bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover">Primary Action</button>
				<button class="border border-border bg-surface px-4 py-2 text-sm font-medium text-text hover:bg-bg">Secondary</button>
				<button class="bg-danger px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover">Danger</button>
				<button class="px-4 py-2 text-sm font-medium text-primary hover:bg-primary-light">Ghost</button>
				<button class="bg-primary px-4 py-2 text-sm font-medium text-white opacity-50" disabled>Disabled</button>
			</div>
			<div class="mt-4 flex flex-wrap items-center gap-3">
				<button class="bg-primary px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-hover">Small Primary</button>
				<button class="border border-border bg-surface px-3 py-1.5 text-xs font-medium text-text hover:bg-bg">Small Secondary</button>
				<button class="text-xs font-medium text-danger hover:text-primary-hover">Small Destructive Text</button>
			</div>
		</div>
	</section>

	<!-- ─── Form Elements ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Form Elements</h2>
		<div class="border border-border bg-surface p-6">
			<div class="grid max-w-lg gap-4">
				<div>
					<label for="sg-text" class="mb-1 block text-sm font-medium">Text Input</label>
					<input id="sg-text" type="text" placeholder="Enter value..." class="w-full border border-border bg-surface px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
				</div>
				<div>
					<label for="sg-search" class="mb-1 block text-sm font-medium">Search</label>
					<div class="flex gap-2">
						<input id="sg-search" type="search" placeholder="Search by name or set number..." class="flex-1 border border-border bg-surface px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
						<button class="border border-border bg-surface px-4 py-2 text-sm font-medium text-text hover:bg-bg">Search</button>
					</div>
				</div>
				<div class="flex items-center gap-2">
					<input id="sg-check" type="checkbox" class="h-4 w-4 accent-primary" />
					<label for="sg-check" class="text-sm">Include spare parts</label>
				</div>
			</div>
		</div>
	</section>

	<!-- ─── Badges ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Badges & Tags</h2>
		<div class="border border-border bg-surface p-6">
			<div class="flex flex-wrap items-center gap-3">
				<span class="border border-success/30 bg-success/10 px-2.5 py-0.5 text-xs font-medium text-success">Published</span>
				<span class="border border-info/30 bg-info/8 px-2.5 py-0.5 text-xs font-medium text-info">In Review</span>
				<span class="border border-warning/30 bg-warning/15 px-2.5 py-0.5 text-xs font-medium text-warning-strong">Warning</span>
				<span class="border border-primary/30 bg-primary/8 px-2.5 py-0.5 text-xs font-medium text-primary">Rejected</span>
				<span class="border border-border bg-bg px-2.5 py-0.5 text-xs font-medium text-text-muted">Draft</span>
				<span class="border border-border bg-surface px-2.5 py-0.5 text-xs font-medium text-text">private</span>
			</div>
		</div>
	</section>

	<!-- ─── Stat Cards ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Stat Cards</h2>
		<p class="text-sm text-text-muted">Colored label + dot indicator. The label text and dot carry the semantic color.</p>
		<div class="grid grid-cols-4 gap-4">
			<div class="border border-border bg-surface p-4">
				<p class="flex items-center gap-2 text-xs font-medium text-info"><span class="inline-block h-2.5 w-2.5 bg-info"></span>In Review</p>
				<p class="font-mono text-2xl font-bold">9</p>
			</div>
			<div class="border border-border bg-surface p-4">
				<p class="flex items-center gap-2 text-xs font-medium text-success"><span class="inline-block h-2.5 w-2.5 bg-success"></span>Accepted</p>
				<p class="font-mono text-2xl font-bold">0</p>
			</div>
			<div class="border border-border bg-surface p-4">
				<p class="flex items-center gap-2 text-xs font-medium text-primary"><span class="inline-block h-2.5 w-2.5 bg-primary"></span>Rejected</p>
				<p class="font-mono text-2xl font-bold">0</p>
			</div>
			<div class="border border-border bg-surface p-4">
				<p class="flex items-center gap-2 text-xs font-medium text-warning-strong"><span class="inline-block h-2.5 w-2.5 bg-warning"></span>Conflict</p>
				<p class="font-mono text-2xl font-bold">0</p>
			</div>
		</div>
		<p class="text-xs text-text-muted">Pattern: 2.5x2.5 color dot + colored label text (font-medium) · Mono 2xl bold value · White card with standard border</p>
	</section>

	<!-- ─── Profile Cards ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Profile Cards</h2>
		<div class="grid grid-cols-3 gap-4">
			<a href="#" class="border border-border bg-surface p-4 transition-colors hover:border-text-muted">
				<p class="font-semibold">My Star Wars Collection</p>
				<p class="text-xs text-text-muted">Set-based profile</p>
				<p class="mt-2 font-mono text-xs text-text-muted">v3 | 617 parts</p>
			</a>
			<a href="#" class="border border-border bg-surface p-4 transition-colors hover:border-text-muted">
				<p class="font-semibold">Presort</p>
				<p class="text-xs text-text-muted">Rule-based profile</p>
				<p class="mt-2 font-mono text-xs text-text-muted">v3 | 0 parts</p>
			</a>
			<a href="#" class="border border-border bg-surface p-4 transition-colors hover:border-text-muted">
				<p class="font-semibold">Basics</p>
				<p class="text-xs text-text-muted">by color and type</p>
				<p class="mt-2 font-mono text-xs text-text-muted">v1 | 0 parts</p>
			</a>
		</div>
	</section>

	<!-- ─── Alert / Message Banners ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Alerts & Messages</h2>
		<div class="space-y-3">
			<div class="bg-primary/8 p-3 text-sm text-primary">Error: Failed to create profile. Please check your input.</div>
			<div class="bg-success/10 p-3 text-sm text-success">Success: Profile published and ready for deployment.</div>
			<div class="bg-warning/15 p-3 text-sm text-warning-strong">Warning: AI assistant requires an OpenRouter API key.</div>
			<div class="bg-info/8 p-3 text-sm text-info">Info: This profile has been forked 3 times.</div>
		</div>
	</section>

	<!-- ─── Version History ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Version History</h2>
		<div class="border border-border bg-surface p-6">
			<div class="space-y-3">
				<div class="border border-border p-4">
					<div class="flex items-center justify-between">
						<div class="flex items-center gap-2">
							<span class="font-mono text-sm font-bold">v3</span>
							<span class="border border-success/30 bg-success/10 px-2 py-0.5 text-xs font-medium text-success">Published</span>
						</div>
						<div class="text-right font-mono text-xs text-text-muted">
							<p>617 parts</p>
							<p>100.0% coverage</p>
						</div>
					</div>
					<p class="mt-1 text-sm">Updated set configuration</p>
					<p class="mt-0.5 text-xs text-text-muted">just now</p>
				</div>
				<div class="border border-border p-4">
					<div class="flex items-center justify-between">
						<div class="flex items-center gap-2">
							<span class="font-mono text-sm font-bold">v2</span>
							<span class="border border-success/30 bg-success/10 px-2 py-0.5 text-xs font-medium text-success">Published</span>
						</div>
						<div class="text-right font-mono text-xs text-text-muted">
							<p>366 parts</p>
							<p>100.0% coverage</p>
						</div>
					</div>
					<p class="mt-1 text-sm">Initial set configuration</p>
					<p class="mt-0.5 text-xs text-text-muted">4h ago</p>
				</div>
				<div class="border border-border p-4">
					<div class="flex items-center justify-between">
						<span class="font-mono text-sm font-bold">v1</span>
						<div class="text-right font-mono text-xs text-text-muted">
							<p>0 parts</p>
							<p>n/a coverage</p>
						</div>
					</div>
					<p class="mt-1 text-sm">Initial version</p>
					<p class="mt-0.5 text-xs text-text-muted">4h ago</p>
				</div>
			</div>
		</div>
	</section>

	<!-- ─── Navigation Tab Styles ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Tab Navigation</h2>
		<div class="border border-border bg-surface p-6">
			<div class="inline-flex border border-border p-1">
				<button class="px-3 py-1.5 text-sm font-medium text-text-muted hover:text-text hover:bg-bg">Discover</button>
				<button class="px-3 py-1.5 text-sm font-medium text-text-muted hover:text-text hover:bg-bg">My Library</button>
				<button class="bg-primary-light px-3 py-1.5 text-sm font-medium text-primary">My Profiles</button>
			</div>
		</div>
	</section>

	<!-- ─── Modal / Dialog ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Modal / Dialog</h2>
		<div class="border border-border bg-surface p-6">
			<div class="relative overflow-hidden border border-border bg-black/50 p-8" style="min-height: 260px">
				<div class="mx-auto w-full max-w-lg bg-surface p-6">
					<div class="mb-4 flex items-center justify-between">
						<h3 class="text-lg font-semibold text-text">Confirm Action</h3>
						<button class="p-1 text-text-muted hover:text-text">
							<svg class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
								<path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
							</svg>
						</button>
					</div>
					<p class="mb-6 text-sm text-text-muted">Are you sure you want to delete this machine? This action cannot be undone.</p>
					<div class="flex justify-end gap-3">
						<button class="border border-border bg-surface px-4 py-2 text-sm font-medium text-text hover:bg-bg">Cancel</button>
						<button class="bg-danger px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover">Delete</button>
					</div>
				</div>
			</div>
			<p class="mt-2 text-xs text-text-muted">Backdrop: bg-black/50 · Content: max-w-lg bg-surface p-6 · Dismissible via ESC and backdrop click</p>
		</div>
	</section>

	<!-- ─── Dropdown Menu ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Dropdown Menu</h2>
		<div class="border border-border bg-surface p-6">
			<div class="flex gap-8">
				<div class="relative">
					<button class="flex items-center gap-2 border border-border px-3 py-1.5 text-sm font-medium text-text hover:bg-bg">
						User Menu
						<svg class="h-4 w-4 text-text-muted" viewBox="0 0 20 20" fill="currentColor">
							<path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd" />
						</svg>
					</button>
					<div class="absolute left-0 z-50 mt-1 w-56 border border-border bg-surface py-1">
						<div class="px-4 py-2 text-xs font-medium uppercase tracking-wider text-text-muted">Account</div>
						<a href="#" class="flex items-center gap-2 px-4 py-2 text-sm text-text hover:bg-bg">Settings</a>
						<a href="#" class="flex items-center gap-2 px-4 py-2 text-sm text-text hover:bg-bg">Profile</a>
						<div class="my-1 border-b border-border"></div>
						<a href="#" class="flex items-center gap-2 px-4 py-2 text-sm text-danger hover:bg-primary-light">Sign out</a>
					</div>
				</div>
				<div class="relative">
					<button class="border border-border p-1.5 text-text-muted hover:bg-bg">
						<svg class="h-4 w-4" fill="currentColor" viewBox="0 0 20 20">
							<path d="M10 6a2 2 0 110-4 2 2 0 010 4zM10 12a2 2 0 110-4 2 2 0 010 4zM10 18a2 2 0 110-4 2 2 0 010 4z" />
						</svg>
					</button>
					<div class="absolute left-0 z-50 mt-1 w-48 border border-border bg-surface py-1">
						<a href="#" class="flex items-center gap-2 px-4 py-2 text-sm text-text hover:bg-bg">Edit</a>
						<a href="#" class="flex items-center gap-2 px-4 py-2 text-sm text-text hover:bg-bg">Duplicate</a>
						<div class="my-1 border-b border-border"></div>
						<a href="#" class="flex items-center gap-2 px-4 py-2 text-sm text-danger hover:bg-primary-light">Delete</a>
					</div>
				</div>
			</div>
			<p class="mt-4 text-xs text-text-muted">Three-dot menu for contextual actions · User menu with section dividers</p>
		</div>
	</section>

	<!-- ─── Icon Buttons ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Icon Buttons</h2>
		<div class="border border-border bg-surface p-6">
			<div class="flex flex-wrap items-center gap-4">
				<div class="flex items-center gap-1">
					<button class="p-1 text-text-muted hover:text-text" title="Move up">
						<svg class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
							<path fill-rule="evenodd" d="M14.707 12.707a1 1 0 01-1.414 0L10 9.414l-3.293 3.293a1 1 0 01-1.414-1.414l4-4a1 1 0 011.414 0l4 4a1 1 0 010 1.414z" clip-rule="evenodd" />
						</svg>
					</button>
					<button class="p-1 text-text-muted hover:text-text" title="Move down">
						<svg class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
							<path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd" />
						</svg>
					</button>
					<button class="p-1 text-text-muted hover:text-primary" title="Delete">
						<svg class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
							<path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd" />
						</svg>
					</button>
				</div>
				<span class="text-xs text-text-muted">Reorder + Delete</span>
				<div class="mx-2 h-6 border-l border-border"></div>
				<button class="p-1 text-text-muted hover:text-text" title="Close">
					<svg class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
						<path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
					</svg>
				</button>
				<span class="text-xs text-text-muted">Close</span>
				<div class="mx-2 h-6 border-l border-border"></div>
				<button class="border border-border p-1.5 text-text-muted hover:bg-bg" title="More">
					<svg class="h-4 w-4" fill="currentColor" viewBox="0 0 20 20">
						<path d="M10 6a2 2 0 110-4 2 2 0 010 4zM10 12a2 2 0 110-4 2 2 0 010 4zM10 18a2 2 0 110-4 2 2 0 010 4z" />
					</svg>
				</button>
				<span class="text-xs text-text-muted">Three-dot menu</span>
			</div>
			<p class="mt-3 text-xs text-text-muted">Ghost: p-1 text-text-muted hover:text-text · Destructive hover: hover:text-primary · Bordered: border + p-1.5</p>
		</div>
	</section>

	<!-- ─── Accordion / Collapsible ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Accordion / Collapsible</h2>
		<div class="border border-border bg-surface">
			<div class="cursor-pointer border-b border-border px-3 py-2 hover:bg-bg bg-primary/8">
				<div class="flex items-center gap-2">
					<svg class="h-3.5 w-3.5 shrink-0 text-text-muted rotate-90 transition-transform" viewBox="0 0 20 20" fill="currentColor">
						<path fill-rule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clip-rule="evenodd" />
					</svg>
					<span class="text-sm font-medium text-text">Expanded Item</span>
					<span class="ml-auto bg-bg px-1.5 py-0.5 text-xs font-medium text-text-muted">128</span>
				</div>
			</div>
			<div class="border-b border-border bg-surface px-3 py-3">
				<p class="text-sm text-text-muted">Expanded content area — form fields, details, actions go here.</p>
			</div>
			<div class="cursor-pointer border-b border-border px-3 py-2 hover:bg-bg">
				<div class="flex items-center gap-2">
					<svg class="h-3.5 w-3.5 shrink-0 text-text-muted transition-transform" viewBox="0 0 20 20" fill="currentColor">
						<path fill-rule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clip-rule="evenodd" />
					</svg>
					<span class="text-sm font-medium text-text">Collapsed Item</span>
					<span class="ml-auto bg-bg px-1.5 py-0.5 text-xs font-medium text-text-muted">64</span>
				</div>
				<div class="ml-5.5 mt-0.5 truncate text-xs text-text-muted">Summary preview text when collapsed</div>
			</div>
			<div class="cursor-pointer border-b border-border px-3 py-2 hover:bg-bg opacity-50">
				<div class="flex items-center gap-2">
					<svg class="h-3.5 w-3.5 shrink-0 text-text-muted transition-transform" viewBox="0 0 20 20" fill="currentColor">
						<path fill-rule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clip-rule="evenodd" />
					</svg>
					<span class="text-sm font-medium text-text-muted line-through">Disabled Item</span>
					<span class="shrink-0 text-[10px] uppercase tracking-wide text-text-muted">off</span>
				</div>
			</div>
		</div>
		<p class="text-xs text-text-muted">Active row: bg-primary/8 · Chevron rotates 90deg when open · Disabled: opacity-50 + line-through</p>
	</section>

	<!-- ─── Set Rule Card ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Set Rule Card</h2>
		<div class="border border-border bg-surface p-6">
			<p class="mb-3 text-xs font-medium uppercase tracking-wider text-text-muted">Collapsed (in rule list)</p>
			<div class="mb-6 flex cursor-pointer items-center gap-2 border-b border-border px-3 py-2 hover:bg-bg">
				<img src="https://cdn.rebrickable.com/media/sets/21242-1/120155.jpg" alt="The End Arena" class="h-16 w-16 shrink-0 object-contain" />
				<div class="min-w-0 flex-1">
					<span class="text-sm font-medium text-text">The End Arena</span>
					<div class="mt-0.5 text-xs text-text-muted">21242-1 · 2023 · 252 parts</div>
				</div>
				<span class="bg-bg px-1.5 py-0.5 text-xs font-medium text-text-muted">252</span>
			</div>
			<p class="mb-3 text-xs font-medium uppercase tracking-wider text-text-muted">Expanded (editor view)</p>
			<div class="border border-border bg-surface px-3 py-3">
				<div class="mb-3 flex gap-4">
					<img src="https://cdn.rebrickable.com/media/sets/21242-1/120155.jpg" alt="The End Arena" class="h-32 w-32 shrink-0 object-contain" />
					<div class="min-w-0 flex-1">
						<input type="text" value="The End Arena" class="mb-1 w-full border border-border px-2 py-1 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
						<div class="mb-2 text-xs text-text-muted">21242-1 · 2023 · 252 parts</div>
						<a href="#" class="inline-flex items-center gap-1 text-xs text-primary hover:underline">
							View on Rebrickable
							<svg class="h-3 w-3" viewBox="0 0 20 20" fill="currentColor">
								<path fill-rule="evenodd" d="M4.25 5.5a.75.75 0 00-.75.75v8.5c0 .414.336.75.75.75h8.5a.75.75 0 00.75-.75v-4a.75.75 0 011.5 0v4A2.25 2.25 0 0112.75 17h-8.5A2.25 2.25 0 012 14.75v-8.5A2.25 2.25 0 014.25 4h5a.75.75 0 010 1.5h-5zm7.25-.75a.75.75 0 01.75-.75h3.5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0V6.31l-5.97 5.97a.75.75 0 01-1.06-1.06l5.97-5.97H12.25a.75.75 0 01-.75-.75z" clip-rule="evenodd" />
							</svg>
						</a>
					</div>
				</div>
				<div class="flex items-center gap-4">
					<label class="flex items-center gap-1.5 text-xs text-text-muted">
						<input type="checkbox" class="h-4 w-4 accent-primary" />
						Include spare parts
					</label>
					<label class="flex items-center gap-1 text-xs text-text-muted">
						<input type="checkbox" class="h-4 w-4 accent-primary" />
						Disabled
					</label>
				</div>
			</div>
		</div>
	</section>

	<!-- ─── Progress Bars ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Progress Bars</h2>
		<div class="border border-border bg-surface p-6">
			<div class="space-y-4">
				<div>
					<div class="mb-1 flex justify-between text-xs text-text-muted">
						<span>Set Progress</span>
						<span>73%</span>
					</div>
					<div class="h-1.5 w-full bg-border">
						<div class="h-full bg-success transition-all" style="width: 73%"></div>
					</div>
				</div>
				<div>
					<div class="mb-1 flex justify-between text-xs text-text-muted">
						<span>Category Coverage</span>
						<span>45%</span>
					</div>
					<div class="h-1.5 w-full bg-border">
						<div class="h-full bg-info transition-all" style="width: 45%"></div>
					</div>
				</div>
				<div>
					<div class="mb-1 flex justify-between text-xs text-text-muted">
						<span>Warning Zone</span>
						<span>12%</span>
					</div>
					<div class="h-1.5 w-full bg-border">
						<div class="h-full bg-warning transition-all" style="width: 12%"></div>
					</div>
				</div>
			</div>
			<p class="mt-3 text-xs text-text-muted">Track: h-1.5 bg-border · Fill: h-full transition-all · Colors: success/info/warning</p>
		</div>
	</section>

	<!-- ─── Spinner / Loading ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Loading States</h2>
		<div class="border border-border bg-surface p-6">
			<p class="mb-4 text-sm text-text-muted">
				<code class="bg-bg px-1">Spinner</code> is the <strong>only</strong> loading animation in Hive — four sharp squares, one lit at a time, snapping clockwise. Import it and pass a
				<code class="bg-bg px-1">size</code> (px); never hand-roll an <code class="bg-bg px-1">animate-spin</code> ring. It inherits its color from
				<code class="bg-bg px-1">currentColor</code>.
			</p>
			<div class="flex items-end gap-8">
				<div class="flex flex-col items-center gap-2">
					<Spinner size={32} class="text-primary" />
					<span class="text-xs text-text-muted">Page — size={32}</span>
				</div>
				<div class="flex flex-col items-center gap-2">
					<Spinner size={16} />
					<span class="text-xs text-text-muted">Inline — size={16}</span>
				</div>
				<div class="flex flex-col items-center gap-2">
					<Spinner size={12} class="text-text-muted" />
					<span class="text-xs text-text-muted">Compact — size={12}</span>
				</div>
				<div class="flex flex-col items-center gap-2">
					<div class="flex items-center gap-1.5 py-4 text-xs text-text-muted"><Spinner size={12} /> Searching...</div>
					<span class="text-xs text-text-muted">Inline with label</span>
				</div>
			</div>
		</div>
	</section>

	<!-- ─── Search with Results ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Search with Inline Results</h2>
		<div class="border border-border bg-surface p-6">
			<div class="max-w-md border border-border bg-surface p-3">
				<div class="mb-2 flex items-center justify-between">
					<h3 class="text-sm font-semibold text-text">Add LEGO Set</h3>
					<button class="p-1 text-text-muted hover:text-text">
						<svg class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
							<path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
						</svg>
					</button>
				</div>
				<input type="text" value="Minecraft" readonly class="mb-2 w-full border border-border px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
				<div class="mb-2 flex items-center gap-2">
					<input type="number" placeholder="From year" class="w-24 border border-border px-2 py-1 text-xs focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
					<span class="text-xs text-text-muted">&ndash;</span>
					<input type="number" placeholder="To year" class="w-24 border border-border px-2 py-1 text-xs focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
				</div>
				<div class="max-h-40 space-y-1 overflow-y-auto">
					<button class="flex w-full items-center gap-3 border border-border p-2 text-left hover:bg-bg">
						<div class="flex h-12 w-12 shrink-0 items-center justify-center bg-bg text-xs text-text-muted">IMG</div>
						<div class="min-w-0 flex-1">
							<div class="truncate text-sm font-medium text-text">The Panda Haven</div>
							<div class="text-xs text-text-muted">21245-1 · 2023 · 553 parts</div>
						</div>
					</button>
					<button class="flex w-full items-center gap-3 border border-border p-2 text-left hover:bg-bg">
						<div class="flex h-12 w-12 shrink-0 items-center justify-center bg-bg text-xs text-text-muted">IMG</div>
						<div class="min-w-0 flex-1">
							<div class="truncate text-sm font-medium text-text">The End Arena</div>
							<div class="text-xs text-text-muted">21242-1 · 2023 · 252 parts</div>
						</div>
					</button>
				</div>
			</div>
			<p class="mt-2 text-xs text-text-muted">Debounced input · Scrollable result list (max-h-64) · Thumbnail 12x12 + metadata · Year filter fields</p>
		</div>
	</section>

	<!-- ─── Data Table ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Data Table</h2>
		<div class="border border-border bg-surface">
			<table class="min-w-full divide-y divide-border">
				<thead class="bg-bg">
					<tr>
						<th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-text-muted">Name</th>
						<th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-text-muted">Role</th>
						<th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-text-muted">Status</th>
						<th class="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-text-muted">Actions</th>
					</tr>
				</thead>
				<tbody class="divide-y divide-border">
					<tr class="hover:bg-bg">
						<td class="whitespace-nowrap px-6 py-4 text-sm font-medium text-text">Marc Neuhaus</td>
						<td class="whitespace-nowrap px-6 py-4 text-sm text-text-muted">Admin</td>
						<td class="whitespace-nowrap px-6 py-4"><span class="border border-success/30 bg-success/10 px-2.5 py-0.5 text-xs font-medium text-success">Active</span></td>
						<td class="whitespace-nowrap px-6 py-4 text-right text-sm text-primary">Edit</td>
					</tr>
					<tr class="opacity-50 hover:bg-bg">
						<td class="whitespace-nowrap px-6 py-4 text-sm font-medium text-text">Guest User</td>
						<td class="whitespace-nowrap px-6 py-4 text-sm text-text-muted">Member</td>
						<td class="whitespace-nowrap px-6 py-4"><span class="border border-border bg-bg px-2.5 py-0.5 text-xs font-medium text-text-muted">Inactive</span></td>
						<td class="whitespace-nowrap px-6 py-4 text-right text-sm text-primary">Edit</td>
					</tr>
				</tbody>
			</table>
		</div>
		<p class="text-xs text-text-muted">Header: bg-bg uppercase · Rows: divide-y hover:bg-bg · Inactive: opacity-50</p>
	</section>

	<!-- ─── Pagination ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Pagination</h2>
		<div class="border border-border bg-surface p-6">
			<div class="flex items-center gap-1">
				<button class="border border-border px-3 py-1.5 text-sm font-medium text-text hover:bg-bg disabled:opacity-50" disabled>Previous</button>
				<button class="border border-border px-3 py-1.5 text-sm font-medium bg-primary text-white">1</button>
				<button class="border border-border px-3 py-1.5 text-sm font-medium text-text hover:bg-bg">2</button>
				<button class="border border-border px-3 py-1.5 text-sm font-medium text-text hover:bg-bg">3</button>
				<span class="px-1 text-text-muted">...</span>
				<button class="border border-border px-3 py-1.5 text-sm font-medium text-text hover:bg-bg">12</button>
				<button class="border border-border px-3 py-1.5 text-sm font-medium text-text hover:bg-bg">Next</button>
			</div>
			<p class="mt-3 text-xs text-text-muted">Active page: bg-primary text-white · Disabled: disabled:opacity-50 · Ellipsis for large page counts</p>
		</div>
	</section>

	<!-- ─── Empty States ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Empty States</h2>
		<div class="border border-border bg-surface p-6">
			<div class="grid gap-4 sm:grid-cols-2">
				<div class="border border-border p-8 text-center">
					<p class="text-sm text-text-muted">No machines yet. Add one to get started.</p>
					<button class="mt-3 bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover">Add Machine</button>
				</div>
				<div class="border border-border p-8 text-center">
					<p class="text-sm text-text-muted">No results found for your search.</p>
					<button class="mt-3 border border-border bg-surface px-4 py-2 text-sm font-medium text-text hover:bg-bg">Clear Filters</button>
				</div>
			</div>
		</div>
	</section>

	<!-- ─── AI Chat Messages ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">AI Chat Messages</h2>
		<div class="border border-border bg-surface p-6">
			<div class="space-y-3">
				<!-- User message -->
				<div class="ml-8">
					<div class="mb-1 text-right text-xs font-medium text-primary">You</div>
					<div class="border border-primary/20 bg-primary-light p-3 text-sm text-text">
						Add all Minecraft sets from 2023
					</div>
				</div>
				<!-- AI message with tool trace -->
				<div class="mr-8">
					<div class="mb-1 text-xs font-medium text-success">AI</div>
					<div class="space-y-1.5">
						<!-- Tool trace -->
						<div class="border border-success/15 bg-success/5 px-3 py-2 text-xs">
							<div class="flex items-center gap-1.5 font-medium text-success">
								<svg class="h-3 w-3 shrink-0 text-success/60" viewBox="0 0 20 20" fill="currentColor">
									<path fill-rule="evenodd" d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.452 4.391l3.328 3.329a.75.75 0 11-1.06 1.06l-3.329-3.328A7 7 0 012 9z" clip-rule="evenodd" />
								</svg>
								Searched sets for "Minecraft"
							</div>
							<div class="mt-0.5 text-success/60">Found 22 sets for "Minecraft": The Panda Haven (21245-1), The End Arena (21242-1), ...</div>
						</div>
						<!-- AI content -->
						<div class="border border-success/10 bg-surface p-3 text-sm text-text">
							I found 22 Minecraft sets from 2023. I'll add them all as set rules.
						</div>
					</div>
				</div>
				<!-- Progress indicator -->
				<div class="mr-8">
					<div class="border border-success/15 bg-success/5 px-3 py-2 text-xs">
						<div class="flex items-center gap-1.5 text-success/60">
							<Spinner size={12} />
							Searching sets for "Minecraft"...
						</div>
					</div>
				</div>
			</div>
			<p class="mt-3 text-xs text-text-muted">User: ml-8 bg-primary-light border-primary/20 · AI: mr-8 bg-surface border-success/10 · Tool trace: bg-success/5 border-success/15</p>
		</div>
	</section>

	<!-- ─── Popover / Positioned Form ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Popover</h2>
		<div class="border border-border bg-surface p-6">
			<div class="relative inline-block">
				<button class="bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover">Save Version</button>
				<div class="absolute left-0 top-full z-50 mt-2 w-72 border border-border bg-surface p-4">
					<h3 class="mb-2 text-sm font-semibold">Save New Version</h3>
					<input type="text" placeholder="Change note (optional)" class="mb-3 w-full border border-border px-2 py-1 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary" />
					<div class="flex justify-end gap-2">
						<button class="border border-border bg-surface px-3 py-1.5 text-xs font-medium text-text hover:bg-bg">Cancel</button>
						<button class="bg-primary px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-hover">Save</button>
					</div>
				</div>
			</div>
			<p class="mt-20 text-xs text-text-muted">Absolute positioned · Backdrop dismiss · Small form layout</p>
		</div>
	</section>

	<!-- ─── Unsaved Changes Bar ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Unsaved Changes Bar</h2>
		<div class="border border-border bg-surface p-6">
			<div class="border-t border-border bg-surface px-4 py-3">
				<div class="flex items-center justify-between">
					<div class="flex items-center gap-2 text-sm text-text-muted">
						<span class="inline-block h-2 w-2 bg-warning"></span>
						Unsaved changes
					</div>
					<div class="flex gap-2">
						<button class="border border-border bg-surface px-3 py-1.5 text-xs font-medium text-text hover:bg-bg">Discard</button>
						<button class="bg-primary px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-hover">Save</button>
					</div>
				</div>
			</div>
			<p class="mt-2 text-xs text-text-muted">Fixed to bottom of viewport · Amber indicator dot · Appears only when dirty state</p>
		</div>
	</section>

	<!-- ─── Select Dropdown ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Select Dropdown</h2>
		<div class="border border-border bg-surface p-6">
			<div class="flex max-w-lg gap-4">
				<div class="flex-1">
					<label class="mb-1 block text-sm font-medium">Machine</label>
					<select class="w-full border border-border px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary">
						<option>All Machines</option>
						<option>Sorter Alpha</option>
						<option>Sorter Beta</option>
					</select>
				</div>
				<div class="flex-1">
					<label class="mb-1 block text-sm font-medium">AI Model</label>
					<select class="w-full border border-border px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary">
						<option>Claude Sonnet 4</option>
						<option>GPT-4o</option>
						<option>Gemini Pro</option>
					</select>
				</div>
			</div>
		</div>
	</section>

	<!-- ─── Card Grid ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Card Grid</h2>
		<div class="grid grid-cols-3 gap-4">
			<div class="border border-border border-t-2 border-t-success bg-surface text-left">
				<div class="aspect-square overflow-hidden bg-bg">
					<div class="flex h-full items-center justify-center text-sm text-text-muted">Image</div>
				</div>
				<div class="p-3">
					<div class="mb-2 flex flex-wrap gap-1">
						<span class="border border-success/30 bg-success/10 px-2 py-0.5 text-xs font-medium text-success">Accepted</span>
					</div>
					<p class="font-mono text-xs text-text-muted">Plate 2x4 · Red</p>
				</div>
			</div>
			<div class="border border-border border-t-2 border-t-info bg-surface text-left">
				<div class="aspect-square overflow-hidden bg-bg">
					<div class="flex h-full items-center justify-center text-sm text-text-muted">Image</div>
				</div>
				<div class="p-3">
					<div class="mb-2 flex flex-wrap gap-1">
						<span class="border border-info/30 bg-info/8 px-2 py-0.5 text-xs font-medium text-info">In Review</span>
					</div>
					<p class="font-mono text-xs text-text-muted">Brick 1x2 · Blue</p>
				</div>
			</div>
			<div class="border border-border border-t-2 border-t-primary bg-surface text-left">
				<div class="aspect-square overflow-hidden bg-bg">
					<div class="flex h-full items-center justify-center text-sm text-text-muted">Image</div>
				</div>
				<div class="p-3">
					<div class="mb-2 flex flex-wrap gap-1">
						<span class="border border-primary/30 bg-primary/8 px-2 py-0.5 text-xs font-medium text-primary">Rejected</span>
					</div>
					<p class="font-mono text-xs text-text-muted">Tile 1x1 · White</p>
				</div>
			</div>
		</div>
		<p class="text-xs text-text-muted">Top border color encodes status · Square image area · Badge + metadata below</p>
	</section>

	<!-- ─── Primitives: Button ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Primitives · Button</h2>
		<div class="space-y-6 border border-border bg-surface p-6">
			<div>
				<p class="mb-2 text-xs uppercase tracking-wider text-text-muted">Variants (md)</p>
				<div class="flex flex-wrap gap-3">
					<Button variant="primary">Primary</Button>
					<Button variant="secondary">Secondary</Button>
					<Button variant="danger">Danger</Button>
					<Button variant="ghost">Ghost</Button>
				</div>
			</div>
			<div>
				<p class="mb-2 text-xs uppercase tracking-wider text-text-muted">Sizes</p>
				<div class="flex flex-wrap items-center gap-3">
					<Button size="sm">Small</Button>
					<Button size="md">Medium</Button>
				</div>
			</div>
			<div>
				<p class="mb-2 text-xs uppercase tracking-wider text-text-muted">States</p>
				<div class="flex flex-wrap gap-3">
					<Button disabled>Disabled</Button>
					<Button loading>Loading</Button>
					<Button variant="secondary" disabled>Secondary disabled</Button>
				</div>
			</div>
		</div>
	</section>

	<!-- ─── Primitives: Alert ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Primitives · Alert</h2>
		<div class="space-y-3 border border-border bg-surface p-6">
			<Alert variant="success" title="Upload complete">
				42 samples synced from the Sorter.
			</Alert>
			<Alert variant="warning" title="Calibration drift detected">
				Recalibrate the classification chamber before the next capture run.
			</Alert>
			<Alert variant="danger" title="Model import failed">
				The uploaded artifact is missing a tokenizer config.
			</Alert>
			<Alert variant="info">
				Review decisions auto-save as you go.
			</Alert>
		</div>
	</section>

	<!-- ─── Primitives: Tooltip ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Primitives · Tooltip</h2>
		<div class="flex flex-wrap gap-8 border border-border bg-surface p-10">
			<Tooltip text="Appears above">
				<Button variant="secondary" size="sm">Hover top</Button>
			</Tooltip>
			<Tooltip text="Appears below" placement="bottom">
				<Button variant="secondary" size="sm">Hover bottom</Button>
			</Tooltip>
			<Tooltip text="Appears right" placement="right">
				<Button variant="secondary" size="sm">Hover right</Button>
			</Tooltip>
		</div>
	</section>

	<!-- ─── Spacing Reference ─── -->
	<section class="space-y-4">
		<h2 class="text-lg font-semibold tracking-tight">Spacing Scale</h2>
		<div class="border border-border bg-surface p-6">
			<div class="space-y-2">
				{#each [1, 2, 3, 4, 6, 8, 12, 16] as size}
					<div class="flex items-center gap-4">
						<span class="w-12 font-mono text-xs text-text-muted">{size * 4}px</span>
						<div class="h-3 bg-primary/20" style="width: {size * 4}px"></div>
						<span class="font-mono text-xs text-text-muted">p-{size}</span>
					</div>
				{/each}
			</div>
		</div>
	</section>
</div>
