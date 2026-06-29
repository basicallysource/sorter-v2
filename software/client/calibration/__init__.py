"""Web-driven calibration routines (replace the old standalone scripts/).

Each module exposes a session/job object the Station server owns while in CALIBRATING
mode, plus persistence via blob_manager. No cv2 windows, no keyboard — everything is
driven from the browser over the API.
"""
