from typing import TypedDict, List, NotRequired


class BrickognizeExternalSite(TypedDict):
    name: str
    url: str


class BrickognizeBoundingBox(TypedDict):
    left: float
    upper: float
    right: float
    lower: float
    image_width: float
    image_height: float
    score: float


class BrickognizeItem(TypedDict):
    id: str
    name: str
    img_url: str
    external_sites: List[BrickognizeExternalSite]
    category: str
    type: str
    score: float
    # Zero-based position of this item in Brickognize's UNFILTERED response,
    # injected by _classifyImages before category filtering. This is the
    # ``item_rank`` the Brickognize feedback API expects, so it must reflect the
    # original ordering even after we drop primo/duplo items.
    rank: NotRequired[int]


class BrickognizeColor(TypedDict):
    id: str
    name: str
    score: float
    # Zero-based position of this color in the response, injected by
    # _classifyImages. This is the ``color_rank`` the color-feedback API expects.
    rank: NotRequired[int]


class BrickognizeResponse(TypedDict):
    listing_id: str
    bounding_box: BrickognizeBoundingBox
    items: List[BrickognizeItem]
    colors: List[BrickognizeColor]
