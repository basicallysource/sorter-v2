import sys
import os
import cv2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blob_manager import getCameraSetup, setCameraSetup
from irl.camera.camera_id import getAllDeviceNames

MAX_CAMERAS_TO_PROBE = 100

ROLES = {
    ord("f"): "feeder",
    ord("F"): "feeder",
    ord("b"): "classification_bottom",
    ord("B"): "classification_bottom",
    ord("t"): "classification_top",
    ord("T"): "classification_top",
}

MENU_LINES = [
    "F - Feeder",
    "B - Classification Bottom",
    "T - Classification Top",
    "N - Skip",
    "Q - Quit and save",
]


def enumerateCameras() -> list[tuple[int, cv2.VideoCapture]]:
    found = []
    consecutive_failures = 0
    for i in range(MAX_CAMERAS_TO_PROBE):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            ret, _ = cap.read()
            if ret:
                found.append((i, cap))
                consecutive_failures = 0
                continue
        cap.release()
        consecutive_failures += 1
        if i > 0 and consecutive_failures >= 3:
            break
    return found


def overlayMenu(frame, index: int, assigned: dict[int, str], device_name: str):
    out = frame.copy()
    x, y_start, line_h = 20, 40, 36

    role = assigned.get(index, "")
    header = f"Camera {index}: {device_name}" + (f"  [{role}]" if role else "")
    cv2.putText(out, header, (x, y_start), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4)
    cv2.putText(
        out, header, (x, y_start), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2
    )

    for i, line in enumerate(MENU_LINES):
        y = y_start + line_h * (i + 1) + 10
        cv2.putText(out, line, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 3)
        cv2.putText(
            out, line, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1
        )

    return out


def main() -> None:
    print("Camera Setup — scanning for cameras...")

    cameras = enumerateCameras()
    if not cameras:
        print("No cameras found.")
        sys.exit(1)

    print(
        f"Found {len(cameras)} camera(s). Press keys in the camera window to assign roles."
    )

    device_names = getAllDeviceNames()
    setup = getCameraSetup() or {}
    assigned: dict[int, str] = {}  # index -> role for this session

    window_name = "Camera Setup"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 800, 600)

    for index, cap in cameras:
        name = device_names.get(index, str(index))

        while True:
            ret, frame = cap.read()
            if ret:
                cv2.imshow(window_name, overlayMenu(frame, index, assigned, name))

            key = cv2.waitKey(1) & 0xFF

            if key in ROLES:
                role = ROLES[key]
                assigned = {i: r for i, r in assigned.items() if r != role}
                assigned[index] = role
                setup = {k: v for k, v in setup.items() if k != role}
                setup[role] = {"name": name}
                print(f"Camera {index} ({name}) -> {role}")
                break

            elif key == ord("n") or key == ord("N"):
                print(f"Camera {index} ({name}) -> skipped")
                break

            elif key == ord("q") or key == ord("Q"):
                cap.release()
                for _, c in cameras:
                    c.release()
                cv2.destroyAllWindows()
                setCameraSetup(setup)
                printSummary(setup)
                return

        cap.release()

    cv2.destroyAllWindows()
    setCameraSetup(setup)
    printSummary(setup)


def printSummary(setup: dict) -> None:
    print("\nSaved:")
    for role, info in setup.items():
        print(f"  {role}: {info['name']}")
    missing = [
        r
        for r in ["feeder", "classification_bottom", "classification_top"]
        if r not in setup
    ]
    if missing:
        print(f"Not assigned: {', '.join(missing)}")


if __name__ == "__main__":
    main()
