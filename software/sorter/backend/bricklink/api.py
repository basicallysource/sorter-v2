from typing import Optional
import requests

from .auth import getAuth
from .types import BricklinkPartData

BL_API_BASE = "https://api.bricklink.com/api/store/v1"


def getPartInfo(part_id: str) -> Optional[BricklinkPartData]:
    url = f"{BL_API_BASE}/items/part/{part_id}"
    try:
        response = requests.get(url, auth=getAuth(), timeout=10)
        if response.status_code != 200:
            return None
        data = response.json()
        if data.get("meta", {}).get("code") != 200:
            return None
        return data.get("data")
    except Exception:
        return None
