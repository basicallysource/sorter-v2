import sys
import os
import cv2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blob_manager import (
    getCameraSetup,
    setCameraSetup,
    getExcludedCameraIndices,
    setExcludedCameraIndices,
)
from hardware.camera_resolver import enumerateCameras, cameraIdentityForIndex


def _setupIndex(value) -> int:
    """A setup entry is either a legacy int index or an identity dict."""
    return value if isinstance(value, int) else value.get("index")

MAX_INDEX = 10
WARMUP_FRAMES = 5


def _captureBackend() -> int:
    """OpenCV capture backend for the current platform.

    Target hardware (OrangePi/Linux) uses V4L2, but that backend doesn't exist
    on macOS — VideoCapture(i, CAP_V4L2) fails to open and every index reports
    "no cameras found". Use AVFoundation on macOS so local Mac dev works.
    """
    if sys.platform == "darwin":
        return cv2.CAP_AVFOUNDATION
    if sys.platform.startswith("linux"):
        return cv2.CAP_V4L2
    return cv2.CAP_ANY

ROLES = {
    ord("f"): "feeder",
    ord("F"): "feeder",
    ord("b"): "classification_bottom",
    ord("B"): "classification_bottom",
    ord("t"): "classification_top",
    ord("T"): "classification_top",
    ord("2"): "c_channel_2",
    ord("3"): "c_channel_3",
    ord("c"): "carousel",
    ord("C"): "carousel",
}

MENU_LINES = [
    "F - feeder",
    "B - classification bottom",
    "T - classification top",
    "2 - c_channel_2 (split feeder)",
    "3 - c_channel_3 (split feeder)",
    "C - carousel (dedicated)",
    "N - next camera",
    "X - exclude this camera (skip on future runs)",
    "Q - quit & save",
]

REQUIRED_ROLES = ["feeder", "classification_bottom", "classification_top"]


def main():
    excluded = set(getExcludedCameraIndices())

    caps = []
    starved = []
    stderr_fd = sys.stderr.fileno()
    for i in range(MAX_INDEX):
        if i in excluded:
            print(f"index {i}: excluded, skipping")
            continue
        old_stderr = os.dup(stderr_fd)
        os.dup2(os.open(os.devnull, os.O_WRONLY), stderr_fd)
        cap = cv2.VideoCapture(i, _captureBackend())
        os.dup2(old_stderr, stderr_fd)
        os.close(old_stderr)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            ret = False
            for _ in range(WARMUP_FRAMES):
                ret, _ = cap.read()
                if ret:
                    break
            if ret:
                caps.append((i, cap))
                continue
            print(f"index {i}: opened but never returned a frame, skipping")
            starved.append(i)
        cap.release()

    if starved:
        print(
            f"\n*** {len(starved)} camera(s) opened but never delivered a frame "
            f"(indices {starved}). ***\n"
            "    This usually means the USB bus is out of bandwidth — too many\n"
            "    cameras sharing one controller/port. To fix:\n"
            "      - Unplug any unused cameras and re-run this script, or\n"
            "      - Move cameras to a different USB port / powered USB hub /\n"
            "        USB adapter so they don't share the same bus.\n"
        )

    if not caps:
        print("no cameras found")
        sys.exit(1)

    print(f"found {len(caps)} camera(s): {[i for i, _ in caps]}")

    # Identities (name + stable USB location) so roles resolve to the right
    # camera after a power-cycle reorder, not a fixed index.
    cam_infos = enumerateCameras()

    setup = getCameraSetup() or {}

    window = "Camera Setup"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window, 800, 600)

    for index, cap in caps:
        roles_this_camera: list[str] = [
            role for role, val in setup.items() if _setupIndex(val) == index
        ]
        while True:
            ret, frame = cap.read()
            if ret:
                roles_str = ", ".join(roles_this_camera) if roles_this_camera else ""
                header = f"Camera {index}" + (f"  [{roles_str}]" if roles_str else "")
                cv2.putText(
                    frame, header, (20, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 4
                )
                cv2.putText(
                    frame,
                    header,
                    (20, 45),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1.0,
                    (0, 255, 0),
                    2,
                )
                for i, line in enumerate(MENU_LINES):
                    y = 85 + i * 34
                    cv2.putText(
                        frame,
                        line,
                        (20, y),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        (0, 0, 0),
                        3,
                    )
                    cv2.putText(
                        frame,
                        line,
                        (20, y),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        (255, 255, 255),
                        1,
                    )
                cv2.imshow(window, frame)

            key = cv2.waitKey(1) & 0xFF

            if key in ROLES:
                role = ROLES[key]
                # Store the stable identity (name+location) so this role
                # re-resolves to the right camera after a reorder; fall back to
                # the bare index if identity lookup fails.
                setup[role] = cameraIdentityForIndex(index, cam_infos) or index
                if role not in roles_this_camera:
                    roles_this_camera.append(role)
                ident = setup[role]
                label = ident.get("name") if isinstance(ident, dict) else ident
                print(f"camera {index} -> {role}  ({label})")
            elif key in (ord("n"), ord("N")):
                if roles_this_camera:
                    print(f"camera {index} -> {', '.join(roles_this_camera)}")
                else:
                    print(f"camera {index} -> skipped")
                break
            elif key in (ord("x"), ord("X")):
                excluded.add(index)
                setExcludedCameraIndices(list(excluded))
                for role, val in list(setup.items()):
                    if _setupIndex(val) == index:
                        del setup[role]
                print(f"camera {index} -> excluded (will be skipped on future runs)")
                break
            elif key in (ord("q"), ord("Q")):
                for _, c in caps:
                    c.release()
                cv2.destroyAllWindows()
                setCameraSetup(setup)
                printSummary(setup)
                return

        cap.release()

    cv2.destroyAllWindows()
    setCameraSetup(setup)
    printSummary(setup)


def printSummary(setup):
    print("\nsaved:")
    for role, val in setup.items():
        if isinstance(val, dict):
            print(f"  {role}: index={val.get('index')} name={val.get('name')!r} "
                  f"location={val.get('location')!r}")
        else:
            print(f"  {role}: {val} (legacy index; re-run to record identity)")
    missing = [r for r in REQUIRED_ROLES if r not in setup]
    if missing:
        print(f"not assigned: {', '.join(missing)}")
    excluded = getExcludedCameraIndices()
    if excluded:
        print(f"excluded indices: {excluded}")


if __name__ == "__main__":
    main()
