"""Frame output encoders for MJPEG streaming and WebSocket delivery."""

from .base import FrameOutput
from .mjpeg import MjpegOutput
from .base64 import Base64Output

__all__ = ["FrameOutput", "MjpegOutput", "Base64Output"]
