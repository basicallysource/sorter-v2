from .types import VisionResult, CameraFrame

__all__ = ["VisionManager", "VisionResult", "CameraFrame"]


def __getattr__(name: str):
    if name == "VisionManager":
        from .vision_manager import VisionManager

        return VisionManager
    raise AttributeError(f"module 'vision' has no attribute {name!r}")
