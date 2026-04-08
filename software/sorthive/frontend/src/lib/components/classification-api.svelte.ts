export class ClassificationApi {
	isDirty = $state(false);
	saving = $state(false);
	feedback = $state<string | null>(null);
	feedbackTone = $state<'neutral' | 'success' | 'danger'>('neutral');
	hasManualOverride = $state(false);
	partId = $state('');
	itemName = $state('');

	save: () => Promise<boolean> = async () => false;
	reset: () => void = () => {};
	clear: () => void = () => {};
}
