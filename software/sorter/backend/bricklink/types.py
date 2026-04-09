from typing_extensions import TypedDict, NotRequired


class BricklinkPartData(TypedDict):
    no: str
    name: str
    type: str
    category_id: NotRequired[int]
    image_url: NotRequired[str]
    thumbnail_url: NotRequired[str]
    weight: NotRequired[str]
    dim_x: NotRequired[str]
    dim_y: NotRequired[str]
    dim_z: NotRequired[str]
    year_released: NotRequired[int]
    is_obsolete: NotRequired[bool]
