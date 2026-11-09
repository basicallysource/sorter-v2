// What the setup flow says about the control boards it found: their names in
// words, the firmware file each takes, and which board drives which motor.
// Everything here comes from what a board reported; nothing assumes how many
// boards a machine has.

import type { FoundBoard, SetupSummary } from '$lib/api/setup';

// The socket each motor is wired to by default, by the name the setup flow
// shows it by (backend hardware_settings/motors.py).
const MOTOR_SOCKETS: Record<string, string> = {
	c_channel_1: 'c_channel_1_rotor',
	c_channel_2: 'c_channel_2_rotor',
	c_channel_3: 'c_channel_3_rotor',
	c_channel_4: 'carousel',
	carousel: 'carousel',
	chute: 'chute_stepper'
};

const SOCKET_LABELS: Record<string, string> = {
	c_channel_1_rotor: 'C-Channel 1',
	c_channel_2_rotor: 'C-Channel 2',
	c_channel_3_rotor: 'C-Channel 3',
	carousel: 'C-Channel 4',
	chute_stepper: 'Chute'
};

export function motorSocket(motorName: string): string {
	return MOTOR_SOCKETS[motorName] ?? motorName;
}

// A motor socket's name in words.
export function socketLabel(socket: string): string {
	return SOCKET_LABELS[socket] ?? socket.replaceAll('_', ' ');
}

// The board that drives a motor, if one was found.
export function boardForMotor(summary: SetupSummary, motorName: string): FoundBoard | null {
	const socket = motorSocket(motorName);
	return summary.discovery.boards.find((board) => board.logical_steppers.includes(socket)) ?? null;
}

const ROLE_WORDS: Record<string, string> = { feeder: 'feeder', distribution: 'distribution' };

export function boardName(board: FoundBoard): string {
	switch (board.hw_id) {
		case 'basically_v1_5':
			return 'Basically control board v1.5';
		case 'basically_v1_2':
			return 'Basically control board v1.2';
		case 'basically_v1_1':
			return `Basically ${ROLE_WORDS[board.role] ?? ''} board v1.1`.replace('  ', ' ');
		case 'skr_pico':
			return `SKR Pico ${ROLE_WORDS[board.role] ?? ''} board`.replace('  ', ' ');
		default:
			return board.device_name || 'Control board';
	}
}

// The start of the name of the firmware file a board takes, as the firmware
// releases name them, or null when no release carries one for it.
export function firmwareFile(board: FoundBoard): string | null {
	switch (board.hw_id) {
		case 'basically_v1_1':
			return board.role === 'feeder'
				? 'basically-v1-1-feeder'
				: board.role === 'distribution'
					? 'basically-v1-1-distribution'
					: null;
		case 'basically_v1_2':
			return 'basically-v1-2-distribution';
		case 'skr_pico':
			return board.role === 'feeder'
				? 'feeder-skr'
				: board.role === 'distribution'
					? 'distribution-skr'
					: null;
		default:
			return null;
	}
}

// A board that turns the doors with serial servos but whose firmware does not
// watch them is too old to move any.
export function needsNewerFirmware(board: FoundBoard): boolean {
	return board.servo_bus && !board.servo_guard;
}
