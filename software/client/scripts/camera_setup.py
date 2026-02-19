import sys
import os
import cv2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blob_manager import getCameraSetup, setCameraSetup

MAX_INDEX = 10

ROLES = {
    ord("f"): "feeder",
    ord("F"): "feeder",
    ord("b"): "classification_bottom",
    ord("B"): "classification_bottom",
    ord("t"): "classification_top",
    ord("T"): "classification_top",
}

MENU_LINES = ["F - feeder", "B - classification bottom", "T - classification top", "N - skip", "Q - quit"]


def main():
    caps = []
    for i in range(MAX_INDEX):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            ret, _ = cap.read()
            if ret:
                caps.append((i, cap))
                continue
        cap.release()

    if not caps:
        print("no cameras found")
        sys.exit(1)

    print(f"found {len(caps)} camera(s): {[i for i, _ in caps]}")

    setup = getCameraSetup() or {}
    assigned = {v: k for k, v in setup.items() if isinstance(v, int)}  # index -> role

    window = "Camera Setup"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window, 800, 600)

    for index, cap in caps:
        while True:
            ret, frame = cap.read()
            if ret:
                role = assigned.get(index, "")
                header = f"Camera {index}" + (f"  [{role}]" if role else "")
                cv2.putText(frame, header, (20, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 4)
                cv2.putText(frame, header, (20, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
                for i, line in enumerate(MENU_LINES):
                    y = 85 + i * 34
                    cv2.putText(frame, line, (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 3)
                    cv2.putText(frame, line, (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1)
                cv2.imshow(window, frame)

            key = cv2.waitKey(1) & 0xFF

            if key in ROLES:
                role = ROLES[key]
                assigned = {i: r for i, r in assigned.items() if r != role}
                assigned[index] = role
                setup = {r: i for i, r in assigned.items()}
                print(f"camera {index} -> {role}")
                break
            elif key in (ord("n"), ord("N")):
                print(f"camera {index} -> skipped")
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
    for role, index in setup.items():
        print(f"  {role}: {index}")
    missing = [r for r in ["feeder", "classification_bottom", "classification_top"] if r not in setup]
    if missing:
        print(f"not assigned: {', '.join(missing)}")


if __name__ == "__main__":
    main()
