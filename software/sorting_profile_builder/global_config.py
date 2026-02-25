import os
from dotenv import load_dotenv

load_dotenv()

REBRICKABLE_BASE_URL = "https://rebrickable.com/api/v3/lego"
REBRICKABLE_PAGE_SIZE = 1000


class GlobalConfig:
    rebrickable_api_key: str
    bl_consumer_key: str
    bl_consumer_secret: str
    bl_token_value: str
    bl_token_secret: str
    bl_price_guide_type: str
    bl_price_guide_new_or_used: str
    bl_price_guide_currency_code: str
    bl_price_guide_country_code: str
    parts_json_path: str
    profiles_dir: str
    port: int

    def __init__(self):
        pass


def mkGlobalConfig() -> GlobalConfig:
    gc = GlobalConfig()
    gc.rebrickable_api_key = os.environ["REBRICKABLE_API_KEY"]
    gc.bl_consumer_key = os.environ.get("BL_CONSUMER_KEY", "")
    gc.bl_consumer_secret = os.environ.get("BL_CONSUMER_SECRET", "")
    gc.bl_token_value = os.environ.get("BL_TOKEN_VALUE", "")
    gc.bl_token_secret = os.environ.get("BL_TOKEN_SECRET", "")
    gc.bl_price_guide_type = os.environ.get("BL_PRICE_GUIDE_TYPE", "sold")
    gc.bl_price_guide_new_or_used = os.environ.get("BL_PRICE_GUIDE_NEW_OR_USED", "N")
    gc.bl_price_guide_currency_code = os.environ.get("BL_PRICE_GUIDE_CURRENCY_CODE", "USD")
    gc.bl_price_guide_country_code = os.environ.get("BL_PRICE_GUIDE_COUNTRY_CODE", "US")
    parts_path = os.environ.get("PARTS_JSON_PATH")
    if not parts_path:
        raise RuntimeError("PARTS_JSON_PATH env var is required")
    gc.parts_json_path = parts_path
    gc.profiles_dir = os.environ.get("PROFILES_DIR", "./profiles")
    gc.port = int(os.environ.get("PORT", "8001"))
    return gc
