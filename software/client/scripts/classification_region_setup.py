import sys
import os
import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blob_manager import (
    getCameraSetup,
    getClassificationRegions,
    setClassificationRegions,
)

CAMERAS = [("top", "classification_top"), ("bottom", "classification_bottom")]
WINDOW = "Classification Region Setup"
POINT_COLOR = (0, 255, 0)
POLY_COLOR = (0, 200, 255)
POINT_RADIUS = 6


def drawOverlay(frame, points, label):
    out = frame.copy()
    h, w = out.shape[:2]

    instructions = [
        f"Camera: {label}",
        f"Points: {len(points)}/4 — click to place",
        "R: reset  |  Enter: confirm  |  Q: quit without saving",
    ]
    for i, line in enumerate(instructions):
        y = 30 + i * 28
        cv2.putText(out, line, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 3)
        cv2.putText(
            out, line, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 1
        )

    for pt in points:
        cv2.circle(out, pt, POINT_RADIUS, POINT_COLOR, -1)

    if len(points) >= 2:
        pts = np.array(points, dtype=np.int32)
        cv2.polylines(
            out, [pts], isClosed=(len(points) == 4), color=POLY_COLOR, thickness=2
        )

    if len(points) == 4:
        overlay = out.copy()
        cv2.fillPoly(overlay, [np.array(points, dtype=np.int32)], POLY_COLOR)
        out = cv2.addWeighted(out, 0.75, overlay, 0.25, 0)

    return out


def collectPoints(cap, label, existing):
    points = list(existing) if existing else []

    def onClick(event, x, y, flags, _):
        if event == cv2.EVENT_LBUTTONDOWN and len(points) < 4:
            points.append((x, y))

    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW, 960, 720)
    cv2.setMouseCallback(WINDOW, onClick)

    while True:
        ret, frame = cap.read()
        if ret:
            cv2.imshow(WINDOW, drawOverlay(frame, points, label))

        key = cv2.waitKey(1) & 0xFF
        if key in (ord("r"), ord("R")):
            points.clear()
        elif key in (13, 10):  # Enter
            if len(points) == 4:
                return points
        elif key in (ord("q"), ord("Q")):
            return None

    return None


def main():
    camera_setup = getCameraSetup()
    if camera_setup is None:
        print("no camera setup found — run scripts/camera_setup.py first")
        sys.exit(1)

    existing = getClassificationRegions() or {}
    result = {}

    for role_label, role_key in CAMERAS:
        if role_key not in camera_setup:
            print(f"camera '{role_key}' not in setup, skipping")
            result[role_label] = existing.get(role_label)
            continue

        index = camera_setup[role_key]
        cap = cv2.VideoCapture(index)
        if not cap.isOpened():
            print(f"could not open camera {index} for {role_key}, skipping")
            result[role_label] = existing.get(role_label)
            continue

        print(f"\n{role_label} camera — click 4 points to define the valid region")
        points = collectPoints(cap, role_label, existing.get(role_label))
        cap.release()

        if points is None:
            print("quit — nothing saved")
            cv2.destroyAllWindows()
            return

        result[role_label] = points
        print(f"  {role_label}: {points}")

    cv2.destroyAllWindows()
    setClassificationRegions(result)
    print("\nsaved classification regions")
    for role_label, pts in result.items():
        print(f"  {role_label}: {pts}")


if __name__ == "__main__":
    main()
