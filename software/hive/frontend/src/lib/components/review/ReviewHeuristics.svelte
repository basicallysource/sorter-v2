<div class="bg-warning/12 p-4">
	<h2 class="text-sm font-semibold text-[#A16207]">What Counts As Good Training Data</h2>
	<div class="mt-3 space-y-3 text-sm text-[#A16207]">
		<p>
			Accept only images where every visible LEGO part is covered by a box or corrected annotation.
		</p>
		<div class="border border-success/20 bg-white px-3 py-3">
			<div class="text-xs font-semibold tracking-wide text-success uppercase">Accept</div>
			<p class="mt-1 text-sm text-text">
				All visible parts are fully accounted for, and the boxes match the actual objects well enough for training.
			</p>
		</div>
		<div class="border border-info/20 bg-white px-3 py-3">
			<div class="text-xs font-semibold tracking-wide text-info uppercase">Annotate First</div>
			<p class="mt-1 text-sm text-text">
				If parts are missing, split incorrectly, or boxed poorly, fix the annotations before accepting.
			</p>
		</div>
		<div class="border border-primary/20 bg-white px-3 py-3">
			<div class="text-xs font-semibold tracking-wide text-primary uppercase">Reject</div>
			<p class="mt-1 text-sm text-text">
				Reject images that stay incomplete or unreliable, for example when visible parts cannot be marked cleanly enough for training.
			</p>
		</div>
	</div>
</div>
