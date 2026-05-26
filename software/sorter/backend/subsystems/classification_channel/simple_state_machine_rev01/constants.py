LOG_TAG = "[C4-REV01]"

# How often the rotation state grabs a frame for the multi-image submission.
CAPTURE_CADENCE_S = 0.2

# Brickognize multi-image cap. Matches MAX_MULTI_RECOGNIZE_CROPS in recognition.py.
MAX_CAPTURES = 8

# Microsteps/second for the rotation during capture and discharge. The
# carousel/c4 stepper typically runs at a few thousand µsteps/s for eject;
# we go gentle for image capture so motion blur is bounded.
ROTATE_SPEED_USTEPS_PER_S = 2000
DISCHARGE_SPEED_USTEPS_PER_S = 3000

# Safety caps — if we don't reach the expected condition in this long, give up
# rather than spinning forever.
ROTATE_TIMEOUT_S = 30.0
DISCHARGE_TIMEOUT_S = 15.0
CLASSIFY_TIMEOUT_S = 30.0

# Raw YOLO flickers — a single empty/occupied frame should not start or stop
# rotation. Require a short streak of consistent detections before acting so
# the platter only moves while a piece is genuinely present.
PRESENCE_STREAK_TO_START = 2
EMPTY_STREAK_TO_ABORT = 3
