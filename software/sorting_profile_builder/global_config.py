import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

REBRICKABLE_BASE_URL = "https://rebrickable.com/api/v3/lego"
REBRICKABLE_PAGE_SIZE = 1000


class GlobalConfig:
    rebrickable_api_key: str
    bl_affiliate_api_key: str
    db_path: str
    brickstore_db_path: str
    profiles_dir: str
    port: int

    def __init__(self):
        pass


def mkGlobalConfig() -> GlobalConfig:
    gc = GlobalConfig()
    gc.rebrickable_api_key = os.environ.get("REBRICKABLE_API_KEY", "")
    gc.bl_affiliate_api_key = os.environ.get("BL_AFFILIATE_API_KEY", "")
    gc.db_path = os.environ.get("PARTS_DB_PATH", "./parts.db")
    gc.brickstore_db_path = os.environ.get(
        "BRICKSTORE_DB_PATH",
        os.path.expanduser("~/Library/Caches/BrickStore/database-v12"),
    )
    gc.profiles_dir = os.environ.get("PROFILES_DIR", "./profiles")
    gc.port = int(os.environ.get("PORT", "8001"))
    return gc
