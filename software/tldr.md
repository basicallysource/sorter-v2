# Assign camera indicies
    uv run python scripts/camera_setup.py

# Draw the polygons
    uv run python scripts/polygon_editor.py

    go to http://127.0.0.1:8100

# (Optional) Calibrate camera colors (shouldn't be needed)
    put color calibration target in tray (grayscale against wall)

    uv run python scripts/calibrate_camera_color.py roi

    select colors in window

    uv run python scripts/calibrate_camera_color.py reference
    uv run python scripts/calibrate_camera_color.py sweep --fine --wipe

    copy values into irl/config.py

    uv run python scripts/calibrate_camera_color.py roi --camera carousel

    select colors in window

    uv run python scripts/calibrate_camera_color.py reference --camera carousel
    uv run python scripts/calibrate_camera_color.py sweep --reset --fine --camera carousel

    copy values into irl/config.py

# Required Calibration of Classification & Carousel Cameras (do the wiggle)
    uv run python scripts/calibrate_classification_baseline.py --camera all --wipe

# View detections
    uv run python scripts/tune_classification_detection.py --cam carousel
    uv run python scripts/tune_classification_detection.py --cam top

# Run the main program
    uv run python main.py



# Debugging:

# Carousel moving constantly with no pieces in it:
    Check detections using:
    uv run python scripts/tune_classification_detection.py --cam carousel

    if detections are showing up without pieces on the tray, it could be one of two reasons:
    1. They carousel alignment is off (angle of carousel trays is misaligned)
        a. power off machine for 10s
        b. Stop any running tasks on computer
        c. hold carousel tray counterclockwise against stop while powering on machine
        d. redraw polygons:
            uv run python scripts/polygon_editor.py
        e. redo calibration:
            uv run python scripts/calibrate_classification_baseline.py --camera all --wipe
        f. restart main task:
            uv run python main.py
    
    or

    2. Abient lighting changed
        a. redo calibration:
            uv run python scripts/calibrate_classification_baseline.py --camera all --wipe
        b. restart main task:
            uv run python main.py

# chute making grinding sound
    1. power off machine
    2. stop running tasks on computer
    3. check all bins for blockages / clogs
    4. check chute range of motion / check for chute ribbon cable binding
        ensure full range of motion of chute (limit switch click to limit switch click)
    5. hold carousel tray counterclockwise against stop while powering on machine
    6. restart main task:
            uv run python main.py
    