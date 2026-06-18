uv run python scripts/camera_setup.py
uv run python scripts/polygon_editor.py

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

uv run python scripts/calibrate_classification_baseline.py --camera all --wipe

optional tuning:
uv run python scripts/tune_classification_detection.py --cam carousel
uv run python scripts/tune_classification_detection.py --cam top

uv run python main.py