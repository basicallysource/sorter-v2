// The setup flow's steps, in the order a builder does them, and what each
// needs to count as done. A step that does not apply to this machine is left
// out of the list (a discard bin, on a chute that drops those pieces into a
// tray). "Done" comes from what the machine reports where it knows it, and
// from the person's own marks (wizard-storage.ts) only where it cannot: that
// a motor turned the right way is seen, not measured.

import type { SetupSummary } from '$lib/api/setup';
import { sharingStepDescription, sharingStepTitle } from '$lib/components/setup/steps/SharingStep.svelte';
import type { SetupMarks } from './wizard-storage';

export type StepId =
	| 'identity'
	| 'theme'
	| 'boards'
	| 'chute'
	| 'motors'
	| 'home'
	| 'bins'
	| 'discard'
	| 'doors'
	| 'cameras'
	| 'sharing'
	| 'hive'
	| 'done';

export type StepContext = {
	summary: SetupSummary;
	marks: SetupMarks;
	sharingAgreed: boolean | null;
	hiveConnected: boolean;
};

export type StepStatus = {
	done: boolean;
	// Why Continue cannot go on yet; a step without one can be left for later.
	blocker?: string | null;
};

export type StepDefinition = {
	id: StepId;
	title: string;
	// Its name in the row of steps, when the title is too long for it.
	short?: string;
	description: string;
	applies?: (ctx: StepContext) => boolean;
	status: (ctx: StepContext) => StepStatus;
	// The step has its own button that goes on (it records an agreement), so
	// the footer shows no Continue.
	ownContinue?: boolean;
};

const STEPS: StepDefinition[] = [
	{
		id: 'identity',
		title: 'Name',
		description: 'Give the machine a name, so it can be told apart from others without its ID.',
		status: ({ summary }) => ({ done: summary.readiness.machine_named })
	},
	{
		id: 'theme',
		title: 'Your color',
		description:
			'Pick the LEGO color the rest of the screens use. Buttons, focus and the current page change to it, and Settings changes it again later.',
		status: () => ({ done: true })
	},
	{
		id: 'boards',
		title: 'Control boards',
		description: 'The boards that drive the motors, and what each one carries.',
		status: ({ summary }) => ({
			done: summary.readiness.boards_detected,
			blocker: summary.readiness.boards_detected
				? null
				: summary.discovery.boards.length
					? 'Some motors are on no board yet.'
					: 'No control board has answered yet.'
		})
	},
	{
		id: 'chute',
		title: 'Chute',
		description: 'Which kind of chute this machine has. How it homes and where pieces go follow from it.',
		status: ({ summary }) => ({
			done: summary.config.chute.variant_saved,
			blocker: summary.config.chute.variant_saved ? null : 'Choose which chute this machine has.'
		})
	},
	{
		id: 'motors',
		title: 'Motors',
		description:
			'Turn each motor a little and say which way it went, looking down from above. A motor that turns the wrong way is reversed.',
		status: ({ summary, marks }) => {
			const motors = summary.config.stepper_directions;
			const checked = motors.filter((motor) => marks.motors?.[motor.name]).length;
			return { done: motors.length > 0 && checked === motors.length };
		}
	},
	{
		id: 'home',
		title: 'Chute home',
		description: 'Check the chute finds its home, then tell it where the bins are round it.',
		status: ({ summary, marks }) => ({
			done: summary.readiness.chute_homed || marks.chuteHome === summary.config.chute.variant
		})
	},
	{
		id: 'bins',
		title: 'Bins',
		description: 'How many layers of bins the machine has, and how many bins each layer holds.',
		status: ({ summary }) => ({ done: summary.config.doors.layer_count > 0 })
	},
	{
		id: 'discard',
		title: 'Discard bin',
		description: 'The bin for the pieces no other bin takes.',
		applies: ({ summary }) => !summary.config.chute.falls_through,
		status: ({ summary }) => ({ done: summary.readiness.discard_ready })
	},
	{
		id: 'doors',
		title: 'Doors',
		description:
			'Each layer has a door in the chute: shut, it catches a piece on its layer; open, it lets the piece fall past. Set up the servo that turns each one.',
		status: ({ summary }) => ({ done: summary.readiness.servo_configured })
	},
	{
		id: 'cameras',
		title: 'Cameras',
		description:
			'Choose a camera for each part of the machine that needs one. One camera can look at several.',
		status: ({ summary }) => ({
			done: summary.readiness.cameras_assigned,
			blocker: summary.readiness.cameras_assigned ? null : 'Save a camera for every part of the machine.'
		})
	},
	{
		id: 'sharing',
		title: sharingStepTitle,
		short: 'Sharing',
		description: sharingStepDescription,
		status: ({ sharingAgreed }) => ({ done: sharingAgreed === true }),
		ownContinue: true
	},
	{
		id: 'hive',
		title: 'Hive',
		description:
			'Connect this sorter to Hive, the community platform, so its samples and progress sync. You can skip this and do it later in Settings.',
		status: ({ marks, hiveConnected }) => {
			const done = hiveConnected || marks.hiveSkipped === true;
			return { done, blocker: done ? null : 'Connect to Hive, or skip it for now.' };
		}
	},
	{
		id: 'done',
		title: 'Done',
		description: 'What is set up, what is left, and the way to the first run.',
		status: ({ marks }) => ({ done: marks.finished === true })
	}
];

export function stepsFor(ctx: StepContext | null): StepDefinition[] {
	if (!ctx) return STEPS.filter((step) => !step.applies);
	return STEPS.filter((step) => !step.applies || step.applies(ctx));
}

export function isStepId(value: string | null): value is StepId {
	return STEPS.some((step) => step.id === value);
}
