/**
 * Reactive API bridge between SampleAnnotator (canvas) and
 * the parent page (sidebar controls). All $state fields are
 * written by the annotator and read by the parent template.
 */
export class AnnotatorApi {
	// ── Reactive state (annotator → parent) ──
	isDirty = $state(false);
	saving = $state(false);
	totalAnnotations = $state(0);
	seededCount = $state(0);
	manualCount = $state(0);
	rectangleCount = $state(0);
	polygonCount = $state(0);
	selectedCount = $state(0);
	feedback = $state<string | null>(null);
	feedbackTone = $state<'neutral' | 'success' | 'danger'>('neutral');
	hasSavedBaseline = $state(false);
	hasSeedBoxes = $state(false);

	// ── Reactive state (parent → annotator) ──
	activeTool = $state<'rectangle' | 'polygon'>('rectangle');

	// ── Actions (set by annotator, called by parent) ──
	save: () => void = () => {};
	deleteSelected: () => void = () => {};
	undo: () => void = () => {};
	redo: () => void = () => {};
	revert: () => void = () => {};
	loadSorterBoxes: () => void = () => {};
	clearAll: () => void = () => {};
}
