<!-- Virtual passthrough "bin" — pieces without a matching rule fall through all
     layer doors to the discard bucket below the machine. Represented so the
     operator knows the output exists; not interactive, no real physical slot. -->
<div class="mt-4 flex flex-col border-2 border-dashed border-warning/50 bg-warning/[0.05]">
	<div class="flex items-center justify-between border-b border-warning/30 bg-warning/10 px-3 py-2">
		<span class="text-sm font-semibold uppercase tracking-wider text-warning-dark">
			Discard Bin · Misc Passthrough
		</span>
		<span class="text-xs text-text-muted">virtual</span>
	</div>
	<div class="p-3 text-sm text-text-muted">
		Pieces that don't match any sorting rule (or whose category has no assigned
		bin) fall through all layer doors into the discard bucket below the machine.
		Empty it manually when it fills up.
	</div>
</div>
