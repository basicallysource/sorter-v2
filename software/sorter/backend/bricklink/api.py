from typing import Optional
import requests

from .auth import getAuth
from .types import BricklinkPartData

BL_API_BASE = "https://api.bricklink.com/api/store/v1"
# Generous timeout for the same reason as Brickognize: the machine often runs on
# slow internet, where a short timeout turns a slow lookup into an outright failure.
BL_API_TIMEOUT_S = 60


def getPartInfo(part_id: str) -> Optional[BricklinkPartData]:
    url = f"{BL_API_BASE}/items/part/{part_id}"
    try:
        response = requests.get(url, auth=getAuth(), timeout=BL_API_TIMEOUT_S)
        if response.status_code != 200:
            return None
        data = response.json()
        if data.get("meta", {}).get("code") != 200:
            return None
        return data.get("data")
    except Exception:
        return None
