import os
from dotenv import load_dotenv

load_dotenv()

REBRICKABLE_BASE_URL = "https://rebrickable.com/api/v3/lego"
REBRICKABLE_PAGE_SIZE = 1000


class GlobalConfig:
    rebrickable_api_key: str
    parts_json_path: str
    profiles_dir: str
    port: int

    def __init__(self):
        pass


def mkGlobalConfig() -> GlobalConfig:
    gc = GlobalConfig()
    gc.rebrickable_api_key = os.environ["REBRICKABLE_API_KEY"]
    parts_path = os.environ.get("PARTS_JSON_PATH")
    if not parts_path:
        raise RuntimeError("PARTS_JSON_PATH env var is required")
    gc.parts_json_path = parts_path
    gc.profiles_dir = os.environ.get("PROFILES_DIR", "./profiles")
    gc.port = int(os.environ.get("PORT", "8001"))
    return gc
