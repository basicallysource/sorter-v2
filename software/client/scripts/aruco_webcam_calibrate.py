import cv2
import cv2.aruco as aruco
import numpy as np
import time
from pathlib import Path
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from blob_manager import getCameraSetup
from irl.config import mkArucoTagConfig


# Get expected tag IDs from config
def getExpectedTagIds():
    config = mkArucoTagConfig()
    expected_ids = set()

    # Channel tags
    expected_ids.add(config.second_c_channel_center_id)
    expected_ids.add(config.second_c_channel_radius1_id)
    expected_ids.add(config.second_c_channel_radius2_id)
    expected_ids.add(config.third_c_channel_center_id)
    expected_ids.add(config.third_c_channel_radius1_id)
    expected_ids.add(config.third_c_channel_radius2_id)

    # Carousel platform tags
    for platform in [
        config.carousel_platform1,
        config.carousel_platform2,
        config.carousel_platform3,
        config.carousel_platform4,
    ]:
        expected_ids.add(platform.corner1_id)
        expected_ids.add(platform.corner2_id)
        expected_ids.add(platform.corner3_id)
        expected_ids.add(platform.corner4_id)

    return expected_ids


# Parameter search space
# Expanded for small tags on wide-angle lenses
PARAM_GRID = {
    "minMarkerPerimeterRate": [0.003, 0.005, 0.01, 0.02],  # lower = detect smaller tags
    "perspectiveRemovePixelPerCell": [4, 6, 8, 10],
    "perspectiveRemoveIgnoredMarginPerCell": [0.13, 0.2, 0.3, 0.4],
    "adaptiveThreshWinSizeMin": [3, 5, 7],
    "adaptiveThreshWinSizeMax": [
        23,
        35,
        53,
        71,
        89,
    ],  # higher = better for varying lighting
    "adaptiveThreshWinSizeStep": [4, 6, 10],
    "errorCorrectionRate": [0.6, 0.8, 1.0],
    "polygonalApproxAccuracyRate": [
        0.03,
        0.05,
        0.08,
    ],  # lower = more precise contour fitting
    "minDistanceToBorder": [0, 1, 3],  # lower = detect tags closer to edges
    "maxErroneousBitsInBorderRate": [
        0.35,
        0.5,
        0.65,
    ],  # higher = more tolerant of distortion
    "cornerRefinementMethod": [0, 1, 2, 3],  # 0=none, 1=subpix, 2=contour, 3=apriltag
    "cornerRefinementWinSize": [3, 5, 7],  # window size for corner refinement
}


def createDetectorParams(config):
    params = aruco.DetectorParameters()
    params.minMarkerPerimeterRate = config["minMarkerPerimeterRate"]
    params.perspectiveRemovePixelPerCell = config["perspectiveRemovePixelPerCell"]
    params.perspectiveRemoveIgnoredMarginPerCell = config[
        "perspectiveRemoveIgnoredMarginPerCell"
    ]
    params.adaptiveThreshWinSizeMin = config["adaptiveThreshWinSizeMin"]
    params.adaptiveThreshWinSizeMax = config["adaptiveThreshWinSizeMax"]
    params.adaptiveThreshWinSizeStep = config["adaptiveThreshWinSizeStep"]
    params.errorCorrectionRate = config["errorCorrectionRate"]
    params.polygonalApproxAccuracyRate = config["polygonalApproxAccuracyRate"]
    params.minDistanceToBorder = config["minDistanceToBorder"]
    params.maxErroneousBitsInBorderRate = config["maxErroneousBitsInBorderRate"]
    params.cornerRefinementMethod = config["cornerRefinementMethod"]
    params.cornerRefinementWinSize = config["cornerRefinementWinSize"]
    return params


def scoreDetection(detected_ids, expected_ids):
    detected_set = set(detected_ids) if detected_ids is not None else set()
    expected_found = len(detected_set & expected_ids)
    unexpected_found = len(detected_set - expected_ids)

    # Punish false positives (means detector is overtuned)
    score = expected_found * 2 - unexpected_found * 3
    return score, expected_found, unexpected_found


def testParams(cap, aruco_dict, params_config, expected_ids, display_time_ms=500):
    params = createDetectorParams(params_config)
    detector = aruco.ArucoDetector(aruco_dict, params)

    scores = []
    expected_counts = []
    unexpected_counts = []

    # Test over multiple frames
    start_time = time.time()
    frame_count = 0

    while (time.time() - start_time) < (display_time_ms / 1000.0):
        ret, frame = cap.read()
        if not ret:
            break

        frame_count += 1
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Try to detect markers, catch OpenCV errors from bad parameter combinations
        try:
            corners, ids, _ = detector.detectMarkers(gray)
        except cv2.error:
            # Some parameter combinations cause OpenCV assertions (e.g., contour refinement)
            # Return a very bad score to skip this config
            return -999, 0, 0

        # Calculate score for this frame
        score, expected_found, unexpected_found = scoreDetection(
            ids.flatten() if ids is not None else None, expected_ids
        )
        scores.append(score)
        expected_counts.append(expected_found)
        unexpected_counts.append(unexpected_found)

        # Annotate frame
        annotated = frame.copy()
        if ids is not None:
            aruco.drawDetectedMarkers(
                annotated, corners, ids, borderColor=(0, 255, 255)
            )

            for i, tag_id in enumerate(ids.flatten()):
                tag_corners = corners[i][0]
                center_x = int(np.mean(tag_corners[:, 0]))
                center_y = int(np.mean(tag_corners[:, 1]))

                # Color code: green for expected, red for unexpected
                color = (0, 255, 0) if tag_id in expected_ids else (0, 0, 255)

                cv2.putText(
                    annotated,
                    str(tag_id),
                    (center_x - 20, center_y + 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1.2,
                    color,
                    3,
                )

        # Display stats
        avg_score = np.mean(scores) if scores else 0
        avg_expected = np.mean(expected_counts) if expected_counts else 0
        avg_unexpected = np.mean(unexpected_counts) if unexpected_counts else 0

        cv2.putText(
            annotated,
            f"Expected: {avg_expected:.1f}/{len(expected_ids)} | Unexpected: {avg_unexpected:.1f} | Score: {avg_score:.1f}",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
        )

        cv2.imshow("ArUco Calibration", annotated)
        cv2.waitKey(1)

    # Return average score
    return (
        np.mean(scores) if scores else -999,
        np.mean(expected_counts),
        np.mean(unexpected_counts),
    )


def main():
    # Load camera setup
    camera_setup = getCameraSetup()
    if camera_setup is None:
        print("Error: No camera setup found. Run client/scripts/camera_setup.py first.")
        return

    if "feeder" not in camera_setup:
        print("Error: Feeder camera not found in setup.")
        return

    feeder_camera_idx = camera_setup["feeder"]
    print(f"Using feeder camera at index {feeder_camera_idx}")

    # Open camera
    cap = cv2.VideoCapture(feeder_camera_idx)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    cap.set(cv2.CAP_PROP_FPS, 30)

    if not cap.isOpened():
        print(f"Error: Could not open camera {feeder_camera_idx}")
        return

    # Get expected tag IDs
    expected_ids = getExpectedTagIds()
    print(f"Expected tag IDs: {sorted(expected_ids)}")
    print(f"Total expected tags: {len(expected_ids)}")
    print()

    # ArUco dictionary
    aruco_dict = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)

    # Start with current best-known params (from vision_manager.py + defaults)
    best_config = {
        "minMarkerPerimeterRate": 0.01,
        "perspectiveRemovePixelPerCell": 8,
        "perspectiveRemoveIgnoredMarginPerCell": 0.3,
        "adaptiveThreshWinSizeMin": 3,
        "adaptiveThreshWinSizeMax": 53,
        "adaptiveThreshWinSizeStep": 4,
        "errorCorrectionRate": 1.0,
        "polygonalApproxAccuracyRate": 0.05,
        "minDistanceToBorder": 3,
        "maxErroneousBitsInBorderRate": 0.35,
        "cornerRefinementMethod": 0,  # 0=none, will test others
        "cornerRefinementWinSize": 5,
    }

    print("Testing baseline configuration...")
    best_score, best_expected, best_unexpected = testParams(
        cap, aruco_dict, best_config, expected_ids, display_time_ms=1000
    )
    print(
        f"Baseline: Score={best_score:.2f}, Expected={best_expected:.1f}, Unexpected={best_unexpected:.1f}"
    )
    print()

    # Grid search - try varying one parameter at a time
    total_tests = sum(len(values) for values in PARAM_GRID.values())
    test_num = 0

    print("Starting parameter search...")
    print(f"Will test {total_tests} configurations (one param at a time)")
    print()

    for param_name, param_values in PARAM_GRID.items():
        print(f"Testing {param_name}...")

        for value in param_values:
            test_num += 1
            test_config = best_config.copy()
            test_config[param_name] = value

            score, expected_found, unexpected_found = testParams(
                cap, aruco_dict, test_config, expected_ids, display_time_ms=300
            )

            if score == -999:
                print(
                    f"  [{test_num}/{total_tests}] {param_name}={value}: SKIPPED (OpenCV error)"
                )
            else:
                print(
                    f"  [{test_num}/{total_tests}] {param_name}={value}: "
                    f"Score={score:.2f}, Expected={expected_found:.1f}, Unexpected={unexpected_found:.1f}"
                )

            if score > best_score:
                print(f"    *** New best! (previous: {best_score:.2f})")
                best_score = score
                best_config = test_config.copy()
                best_expected = expected_found
                best_unexpected = unexpected_found

        print()

    # Display final results with best config
    print("\n" + "=" * 70)
    print("CALIBRATION COMPLETE")
    print("=" * 70)
    print()
    print("Best Configuration:")
    for param_name, value in best_config.items():
        print(f"  {param_name}: {value}")
    print()
    print(f"Performance:")
    print(f"  Expected tags found: {best_expected:.1f}/{len(expected_ids)}")
    print(f"  Unexpected tags: {best_unexpected:.1f}")
    print(f"  Score: {best_score:.2f}")
    print()
    print("Copy these values to vision_manager.py:")
    print()
    print(
        f"self._aruco_params.minMarkerPerimeterRate = {best_config['minMarkerPerimeterRate']}"
    )
    print(
        f"self._aruco_params.perspectiveRemovePixelPerCell = {best_config['perspectiveRemovePixelPerCell']}"
    )
    print(
        f"self._aruco_params.perspectiveRemoveIgnoredMarginPerCell = {best_config['perspectiveRemoveIgnoredMarginPerCell']}"
    )
    print(
        f"self._aruco_params.adaptiveThreshWinSizeMin = {best_config['adaptiveThreshWinSizeMin']}"
    )
    print(
        f"self._aruco_params.adaptiveThreshWinSizeMax = {best_config['adaptiveThreshWinSizeMax']}"
    )
    print(
        f"self._aruco_params.adaptiveThreshWinSizeStep = {best_config['adaptiveThreshWinSizeStep']}"
    )
    print(
        f"self._aruco_params.errorCorrectionRate = {best_config['errorCorrectionRate']}"
    )
    print(
        f"self._aruco_params.polygonalApproxAccuracyRate = {best_config['polygonalApproxAccuracyRate']}"
    )
    print(
        f"self._aruco_params.minDistanceToBorder = {best_config['minDistanceToBorder']}"
    )
    print(
        f"self._aruco_params.maxErroneousBitsInBorderRate = {best_config['maxErroneousBitsInBorderRate']}"
    )
    print(
        f"self._aruco_params.cornerRefinementMethod = {best_config['cornerRefinementMethod']}  # 0=none, 1=subpix, 2=contour, 3=apriltag"
    )
    print(
        f"self._aruco_params.cornerRefinementWinSize = {best_config['cornerRefinementWinSize']}"
    )
    print()
    print("Showing best configuration. Press Ctrl+C to exit...")

    # Show best config continuously until user interrupts
    params = createDetectorParams(best_config)
    detector = aruco.ArucoDetector(aruco_dict, params)

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # Try to detect markers, handle OpenCV errors gracefully
            try:
                corners, ids, _ = detector.detectMarkers(gray)
            except cv2.error:
                # Some parameter combinations can fail - just skip this frame
                corners, ids = None, None

            # Annotate frame
            annotated = frame.copy()
            if ids is not None and corners is not None:
                aruco.drawDetectedMarkers(
                    annotated, corners, ids, borderColor=(0, 255, 255)
                )

                for i, tag_id in enumerate(ids.flatten()):
                    tag_corners = corners[i][0]
                    center_x = int(np.mean(tag_corners[:, 0]))
                    center_y = int(np.mean(tag_corners[:, 1]))

                    # Color code: green for expected, red for unexpected
                    color = (0, 255, 0) if tag_id in expected_ids else (0, 0, 255)

                    cv2.putText(
                        annotated,
                        str(tag_id),
                        (center_x - 20, center_y + 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        1.2,
                        color,
                        3,
                    )

            # Calculate current stats
            score, expected_found, unexpected_found = scoreDetection(
                ids.flatten() if ids is not None else None, expected_ids
            )

            cv2.putText(
                annotated,
                f"BEST CONFIG - Expected: {expected_found}/{len(expected_ids)} | Unexpected: {unexpected_found} | Score: {score:.1f}",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2,
            )

            cv2.imshow("ArUco Calibration", annotated)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    except KeyboardInterrupt:
        print("\nExiting...")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
